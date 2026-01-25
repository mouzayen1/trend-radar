"""
Hacker News Collector
Uses Firebase API (free, no rate limits)
Extracts product/project names and stores descriptions
"""

import asyncio
import aiohttp
import re
from datetime import datetime, timezone
from typing import Optional
import json
import sys
sys.path.append('..')
from utils.stopwords import is_valid_entity, normalize_entity, extract_product_name, is_camel_case, has_version_number


class HackerNewsCollector:
    BASE_URL = "https://hacker-news.firebaseio.com/v0"

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def extract_show_hn_product(self, title: str) -> str | None:
        """Extract product name from Show HN posts"""
        # Skip common non-product patterns
        skip_patterns = [
            r'Show HN:\s*I\s+',
            r'Show HN:\s*My\s+',
            r'Show HN:\s*We\s+',
            r'Show HN:\s*A\s+',
            r'Show HN:\s*An\s+',
            r'Show HN:\s*The\s+',
            r'Show HN:\s*How\s+',
            r'Show HN:\s*Why\s+',
        ]
        for pattern in skip_patterns:
            if re.match(pattern, title, re.IGNORECASE):
                return None

        # Pattern 1: Show HN: ProductName - CamelCase or specific format
        match = re.match(
            r'Show HN:\s*([A-Z][A-Za-z0-9_\-\.]+(?:\s+[A-Z][A-Za-z0-9_\-\.]+)?)',
            title
        )
        if match:
            product = match.group(1).strip()
            product = re.sub(r'[\-–—:,\(\)]+$', '', product).strip()
            if len(product) >= 2 and is_valid_entity(product):
                return product

        # Pattern 2: Show HN: "Product Name" (quoted)
        match = re.search(r'Show HN:.*?"([^"]+)"', title)
        if match:
            product = match.group(1).strip()
            if len(product) >= 2 and is_valid_entity(product):
                return product

        # Pattern 3: Product name with tech domain (.io, .ai, .dev, etc)
        match = re.search(r'Show HN:\s*([A-Za-z][A-Za-z0-9]*\.(?:io|ai|dev|app|tools|sh))', title, re.IGNORECASE)
        if match:
            product = match.group(1).strip()
            if len(product) >= 2:
                return product

        return None

    def extract_entities(self, title: str, url: str = None) -> list[dict]:
        """
        Extract notable entities from a title.
        Returns list of {name, type} dicts.
        Only returns likely product/project names.
        """
        entities = []
        seen = set()

        def add_entity(name: str, entity_type: str):
            if not name or len(name) < 2:
                return
            norm = normalize_entity(name)
            if norm not in seen and is_valid_entity(name):
                seen.add(norm)
                entities.append({'name': name, 'type': entity_type, 'normalized': norm})

        # 1. Show HN products (highest priority)
        if title.lower().startswith('show hn:'):
            product = self.extract_show_hn_product(title)
            if product:
                add_entity(product, 'show_hn_product')

        # 2. CamelCase words (likely product names)
        camel_cases = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)\b', title)
        for cc in camel_cases:
            add_entity(cc, 'camelcase')

        # 3. ALL CAPS with numbers (GPT4, LLAMA3, etc)
        caps_with_nums = re.findall(r'\b([A-Z]+\d+(?:\.\d+)?)\b', title)
        for cwn in caps_with_nums:
            if len(cwn) >= 3:
                add_entity(cwn, 'acronym_version')

        # 4. Mixed case with numbers (Llama3, GPT4o, etc)
        mixed_nums = re.findall(r'\b([A-Z][a-z]*\d+[a-z]*)\b', title)
        for mn in mixed_nums:
            if len(mn) >= 3:
                add_entity(mn, 'product_version')

        # 5. Quoted names
        quoted = re.findall(r'"([^"]{2,30})"|\'([^\']{2,30})\'', title)
        for q in quoted:
            name = q[0] or q[1]
            if name:
                add_entity(name, 'quoted')

        # 6. Names with specific patterns (ending in .js, .py, etc)
        tech_names = re.findall(r'\b([A-Za-z][A-Za-z0-9]*\.(?:js|py|rs|go|io|ai|dev|app))\b', title, re.IGNORECASE)
        for tn in tech_names:
            add_entity(tn, 'tech_domain')

        # 7. GitHub-style names from URL
        if url and 'github.com' in url:
            gh_match = re.search(r'github\.com/([^/]+/[^/\?#]+)', url)
            if gh_match:
                repo = gh_match.group(1)
                add_entity(repo, 'github_repo')

        # 8. Standalone capitalized words that might be product names (more restrictive)
        # Only if they're not common words and have unusual patterns
        cap_words = re.findall(r'\b([A-Z][a-z]{2,}[A-Z][a-z]*|[A-Z]{2,}[a-z]+)\b', title)
        for cw in cap_words:
            add_entity(cw, 'proper_noun')

        # Limit to top 3 most likely entities
        return entities[:3]

    async def fetch_json(self, url: str) -> dict | list | None:
        """Fetch JSON from URL with error handling"""
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"[HN] Error fetching {url}: {e}")
        return None

    async def fetch_story(self, story_id: int) -> dict | None:
        """Fetch a single story's details"""
        url = f"{self.BASE_URL}/item/{story_id}.json"
        return await self.fetch_json(url)

    async def collect(self) -> int:
        """Main collection routine - returns number of signals stored"""
        print("[HN] Starting collection...")

        if not self.session:
            self.session = aiohttp.ClientSession()

        # Fetch story IDs from multiple endpoints
        endpoints = [
            ('topstories', f"{self.BASE_URL}/topstories.json"),
            ('newstories', f"{self.BASE_URL}/newstories.json"),
            ('showstories', f"{self.BASE_URL}/showstories.json"),
        ]

        all_story_ids = set()
        for name, url in endpoints:
            ids = await self.fetch_json(url)
            if ids:
                all_story_ids.update(ids[:100])
                print(f"[HN] Fetched {len(ids[:100])} from {name}")

        print(f"[HN] Total unique stories to process: {len(all_story_ids)}")

        # Fetch story details in parallel (batches of 50)
        stories = []
        story_ids = list(all_story_ids)

        for i in range(0, len(story_ids), 50):
            batch = story_ids[i:i+50]
            tasks = [self.fetch_story(sid) for sid in batch]
            results = await asyncio.gather(*tasks)
            stories.extend([s for s in results if s])

        print(f"[HN] Fetched {len(stories)} story details")

        # Process and store signals
        signals_count = 0
        now = datetime.now(timezone.utc)

        async with self.db_pool.acquire() as conn:
            for story in stories:
                if not story or story.get('type') != 'story':
                    continue

                title = story.get('title', '')
                score = story.get('score', 0)
                created = story.get('time', 0)
                story_url = story.get('url', f"https://news.ycombinator.com/item?id={story.get('id')}")
                hn_url = f"https://news.ycombinator.com/item?id={story.get('id')}"
                descendants = story.get('descendants', 0)

                # Calculate age in hours
                if created:
                    age_hours = (now.timestamp() - created) / 3600
                    age_hours = max(age_hours, 0.1)
                else:
                    age_hours = 1

                # Calculate velocity (points per hour)
                velocity = score / age_hours

                # Extract entities
                entities = self.extract_entities(title, story_url)

                for entity_info in entities:
                    entity_name = entity_info['name']
                    normalized = entity_info['normalized']
                    entity_type = entity_info['type']

                    # Build rich metadata with description
                    metadata = {
                        'title': title,
                        'description': title,  # Use title as description for HN
                        'score': score,
                        'comments': descendants,
                        'age_hours': round(age_hours, 2),
                        'story_id': story.get('id'),
                        'entity_type': entity_type,
                        'source_url': story_url,
                        'hn_url': hn_url,
                    }

                    # Store velocity signal
                    await conn.execute('''
                        INSERT INTO signals (platform, entity_raw, entity_normalized,
                                           metric_type, metric_value, url, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ''', 'hackernews', entity_name, normalized, 'velocity', velocity, hn_url, json.dumps(metadata))
                    signals_count += 1

        print(f"[HN] Stored {signals_count} signals")
        return signals_count
