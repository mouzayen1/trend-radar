"""
Reddit Collector - STRICT Version
Uses public JSON endpoints (no API key needed)
Heavy filtering to match Trend Radar quality standards
Only captures high-signal posts that indicate real trends
"""

import asyncio
import aiohttp
import json
import re
from datetime import datetime, timezone
from typing import Optional
import sys
sys.path.append('..')
from utils.stopwords import is_valid_entity


class RedditCollector:
    BASE_URL = "https://www.reddit.com"

    # Subreddits to track - focused on tech/trends
    SUBREDDITS = {
        'technology': 'tech',
        'programming': 'tech',
        'MachineLearning': 'ai',
        'opensource': 'tech',
        'SideProject': 'launches',
        'webdev': 'tech',
    }

    # STRICT thresholds - only high-quality signals
    MIN_UPVOTES = 100           # Must have real traction
    MIN_COMMENTS = 10           # Must have discussion
    MIN_UPVOTE_RATIO = 0.70     # Must be well-received
    MIN_VELOCITY = 20           # Upvotes per hour minimum
    MAX_POST_AGE_HOURS = 24     # Only recent posts

    # Patterns to SKIP (noise filters)
    SKIP_TITLE_PATTERNS = [
        r'^(how|why|what|when|where|who|which|can|should|would|could|is|are|do|does|did)\s',  # Questions
        r'^(i |my |we |our |just |finally |today i |til |tifu )',  # Personal posts
        r'(\?|asking for|help|advice|suggest|recommend|opinion|thoughts\??)',  # Asking for help
        r'^(rant|unpopular opinion|hot take|am i the only|dae |does anyone)',  # Opinion posts
        r'(meme|funny|lol|lmao|haha|😂|🤣)',  # Meme content
        r'^(update:|part \d|chapter \d)',  # Series posts
        r'(hiring|job|resume|interview|salary|offer)',  # Job posts
        r'(upvote|downvote|karma|award|gold|silver)',  # Meta reddit
        r'^r/',  # Subreddit references
    ]

    # Patterns that indicate REAL trends (boost these)
    BOOST_PATTERNS = [
        r'(launched|releases?|announcing|introducing|now available)',
        r'(open.?source[ds]?|github|gitlab)',
        r'(v\d+\.\d+|version \d+)',  # Version releases
        r'(acquired|acquisition|funding|raised|series [abc])',
        r'(breakthrough|milestone|achievement)',
    ]

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        # Reddit requires a user-agent
        headers = {
            'User-Agent': 'TrendRadar/2.0 (Trend Detection Bot)'
        }
        self.session = aiohttp.ClientSession(headers=headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def collect(self) -> int:
        """Main collection routine"""
        print("[Reddit] Starting collection...")
        total_signals = 0

        for subreddit, category in self.SUBREDDITS.items():
            try:
                count = await self.collect_subreddit(subreddit, category)
                total_signals += count
                # Rate limit - be nice to Reddit
                await asyncio.sleep(2)
            except Exception as e:
                print(f"[Reddit] Error collecting r/{subreddit}: {e}")

        print(f"[Reddit] Stored {total_signals} high-quality signals")
        return total_signals

    async def collect_subreddit(self, subreddit: str, category: str) -> int:
        """Collect from a single subreddit"""
        url = f"{self.BASE_URL}/r/{subreddit}/hot.json?limit=50"

        try:
            async with self.session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 429:
                    print(f"[Reddit] Rate limited on r/{subreddit}, skipping...")
                    await asyncio.sleep(5)
                    return 0

                if resp.status != 200:
                    return 0

                data = await resp.json()
                posts = data.get('data', {}).get('children', [])

                signals = []
                for post in posts:
                    signal = self.process_post(post.get('data', {}), subreddit, category)
                    if signal:
                        signals.append(signal)

                if signals:
                    await self.store_signals(signals)
                    print(f"[Reddit] r/{subreddit}: {len(signals)} quality signals (from {len(posts)} posts)")

                return len(signals)

        except asyncio.TimeoutError:
            print(f"[Reddit] Timeout on r/{subreddit}")
            return 0
        except Exception as e:
            print(f"[Reddit] Error: {e}")
            return 0

    def process_post(self, post: dict, subreddit: str, category: str) -> Optional[dict]:
        """Process a post with STRICT filtering"""
        try:
            title = post.get('title', '')
            upvotes = post.get('ups', 0)
            comments = post.get('num_comments', 0)
            upvote_ratio = post.get('upvote_ratio', 0)
            created_utc = post.get('created_utc', 0)
            permalink = post.get('permalink', '')
            is_self = post.get('is_self', False)
            url = post.get('url', '')

            # === STRICT FILTERING ===

            # 1. Must meet minimum engagement thresholds
            if upvotes < self.MIN_UPVOTES:
                return None
            if comments < self.MIN_COMMENTS:
                return None
            if upvote_ratio < self.MIN_UPVOTE_RATIO:
                return None

            # 2. Calculate velocity (upvotes per hour)
            now = datetime.now(timezone.utc).timestamp()
            age_hours = (now - created_utc) / 3600
            if age_hours > self.MAX_POST_AGE_HOURS:
                return None
            if age_hours < 0.1:
                age_hours = 0.1  # Prevent division issues

            velocity = upvotes / age_hours
            if velocity < self.MIN_VELOCITY:
                return None

            # 3. Skip noise patterns
            title_lower = title.lower()
            for pattern in self.SKIP_TITLE_PATTERNS:
                if re.search(pattern, title_lower, re.IGNORECASE):
                    return None

            # 4. Extract entities from title
            entities = self.extract_entities(title)
            if not entities:
                return None

            # 5. Use primary entity (Reddit already filtered by upvotes/comments)
            primary_entity = entities[0]

            # 6. Check for boost patterns (indicates real trend)
            is_boosted = any(re.search(p, title_lower) for p in self.BOOST_PATTERNS)

            # Build signal
            return {
                'entity_raw': primary_entity,
                'entity_normalized': primary_entity.lower(),
                'platform': 'reddit',
                'metric_type': 'trending_post',
                'metric_value': velocity,
                'url': f"https://reddit.com{permalink}",
                'metadata': {
                    'title': title[:200],
                    'subreddit': subreddit,
                    'category': category,
                    'upvotes': upvotes,
                    'comments': comments,
                    'upvote_ratio': upvote_ratio,
                    'velocity': round(velocity, 2),
                    'age_hours': round(age_hours, 2),
                    'is_boosted': is_boosted,
                    'all_entities': entities[:5],
                    'external_url': url if not is_self else None,
                }
            }

        except Exception as e:
            return None

    def extract_entities(self, title: str) -> list:
        """Extract meaningful entities from post title"""
        entities = []

        # Clean title
        title_clean = re.sub(r'\s*[\|\-\[\]()]\s*', ' ', title)

        # 1. Extract quoted strings (usually product/project names)
        quoted = re.findall(r'"([^"]+)"', title)
        for q in quoted:
            if 3 <= len(q) <= 50:
                entities.append(q)

        # 2. Extract CamelCase (ProductNames, LibraryNames)
        camel = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', title)
        entities.extend(camel)

        # 3. Extract GitHub-style repo names (owner/repo)
        repos = re.findall(r'\b([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)\b', title)
        for r in repos:
            if len(r) >= 5:
                entities.append(r)

        # 4. Extract proper nouns (capitalized words not at sentence start)
        words = title_clean.split()
        for i, word in enumerate(words):
            if i == 0:
                continue
            # Capitalized words (names, products, companies)
            if re.match(r'^[A-Z][a-z]{2,}$', word):
                entities.append(word)

        # 5. Extract ALL CAPS acronyms (allow more through for Reddit)
        acronyms = re.findall(r'\b([A-Z]{2,6})\b', title)
        entities.extend(acronyms)

        # 6. Extract version patterns like "Python 3.12", "React 19"
        versioned = re.findall(r'\b([A-Z][a-z]+)\s+\d+(?:\.\d+)*\b', title)
        entities.extend(versioned)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for e in entities:
            lower = e.lower()
            if lower not in seen and len(e) >= 2:
                seen.add(lower)
                unique.append(e)

        # FALLBACK: If no entities found, use first 2-3 key words from title
        if not unique:
            # Extract first meaningful capitalized phrase
            match = re.search(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b', title)
            if match:
                unique.append(match.group(1))

        return unique

    async def store_signals(self, signals: list):
        """Store signals in database"""
        async with self.db_pool.acquire() as conn:
            for signal in signals:
                try:
                    await conn.execute('''
                        INSERT INTO signals
                        (platform, entity_raw, entity_normalized, metric_type,
                         metric_value, url, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ''',
                        signal['platform'],
                        signal['entity_raw'],
                        signal['entity_normalized'],
                        signal['metric_type'],
                        signal['metric_value'],
                        signal['url'],
                        json.dumps(signal['metadata'])
                    )
                except Exception as e:
                    pass  # Skip duplicates
