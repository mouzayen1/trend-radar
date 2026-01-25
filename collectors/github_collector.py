"""
GitHub Trending Collector
Scrapes github.com/trending (no API needed)
Tracks repository momentum with full owner/repo format
"""

import aiohttp
from bs4 import BeautifulSoup
import re
from typing import Optional
import json
import sys
sys.path.append('..')
from utils.stopwords import is_valid_entity, normalize_entity


class GitHubCollector:
    BASE_URL = "https://github.com/trending"

    # Pages to scrape
    PAGES = [
        ('', 'daily'),           # All languages, daily
        ('', 'weekly'),          # All languages, weekly
        ('/python', 'daily'),
        ('/javascript', 'daily'),
        ('/typescript', 'daily'),
        ('/rust', 'daily'),
        ('/go', 'daily'),
    ]

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def parse_number(self, text: str) -> int:
        """Parse numbers like '1,234' or '1.2k' """
        if not text:
            return 0
        text = text.strip().lower().replace(',', '')
        try:
            if 'k' in text:
                return int(float(text.replace('k', '')) * 1000)
            elif 'm' in text:
                return int(float(text.replace('m', '')) * 1000000)
            return int(float(text))
        except ValueError:
            return 0

    async def fetch_page(self, language: str, since: str) -> str | None:
        """Fetch trending page HTML"""
        url = f"{self.BASE_URL}{language}?since={since}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        try:
            async with self.session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    print(f"[GitHub] Got status {resp.status} for {url}")
        except Exception as e:
            print(f"[GitHub] Error fetching {url}: {e}")
        return None

    def parse_trending_page(self, html: str, language: str, since: str) -> list[dict]:
        """Parse trending repos from HTML"""
        repos = []
        soup = BeautifulSoup(html, 'lxml')

        # Find all repo articles
        articles = soup.select('article.Box-row')

        for article in articles:
            try:
                # Repo name (owner/repo)
                repo_link = article.select_one('h2 a')
                if not repo_link:
                    continue

                href = repo_link.get('href', '').strip('/')
                if '/' not in href:
                    continue

                repo_name = href  # Full owner/repo format

                # Description
                desc_elem = article.select_one('p')
                description = desc_elem.get_text(strip=True) if desc_elem else ''

                # Language
                lang_elem = article.select_one('[itemprop="programmingLanguage"]')
                lang = lang_elem.get_text(strip=True) if lang_elem else language.strip('/') or 'Unknown'

                # Total stars
                stars_elem = article.select_one('a[href$="/stargazers"]')
                total_stars = 0
                if stars_elem:
                    total_stars = self.parse_number(stars_elem.get_text())

                # Stars today/this week
                stars_today_elem = article.select_one('span.d-inline-block.float-sm-right')
                stars_today = 0
                if stars_today_elem:
                    text = stars_today_elem.get_text(strip=True)
                    match = re.search(r'([\d,]+)', text)
                    if match:
                        stars_today = self.parse_number(match.group(1))

                # Forks
                forks_elem = article.select_one('a[href$="/forks"]')
                forks = self.parse_number(forks_elem.get_text()) if forks_elem else 0

                # Calculate "new hot" ratio
                new_hot_ratio = 0
                if total_stars > 0:
                    new_hot_ratio = stars_today / total_stars

                repos.append({
                    'repo_name': repo_name,  # owner/repo
                    'short_name': repo_name.split('/')[-1],  # Just repo name
                    'owner': repo_name.split('/')[0],
                    'description': description[:500] if description else f"GitHub repository: {repo_name}",
                    'language': lang or 'Unknown',
                    'total_stars': total_stars,
                    'stars_today': stars_today,
                    'forks': forks,
                    'new_hot_ratio': new_hot_ratio,
                    'since': since,
                    'filter_language': language.strip('/') or 'all'
                })

            except Exception as e:
                print(f"[GitHub] Error parsing repo: {e}")
                continue

        return repos

    async def collect(self) -> int:
        """Main collection routine"""
        print("[GitHub] Starting collection...")

        if not self.session:
            self.session = aiohttp.ClientSession()

        all_repos = {}  # Dedupe by repo_name

        for language, since in self.PAGES:
            html = await self.fetch_page(language, since)
            if html:
                repos = self.parse_trending_page(html, language, since)
                print(f"[GitHub] Found {len(repos)} repos in {language or 'all'}/{since}")

                for repo in repos:
                    key = repo['repo_name']
                    # Keep the one with higher stars_today
                    if key not in all_repos or repo['stars_today'] > all_repos[key]['stars_today']:
                        all_repos[key] = repo

        print(f"[GitHub] Total unique repos: {len(all_repos)}")

        # Store signals
        signals_count = 0

        async with self.db_pool.acquire() as conn:
            for repo_name, data in all_repos.items():
                url = f"https://github.com/{repo_name}"

                # Use owner/repo as the entity (this is the unique identifier)
                entity_raw = repo_name
                entity_normalized = repo_name.lower()

                # Build rich metadata with description
                metadata = {
                    'full_name': repo_name,
                    'short_name': data['short_name'],
                    'owner': data['owner'],
                    'description': data['description'],
                    'title': f"{data['short_name']} - {data['description'][:100]}",
                    'language': data['language'],
                    'total_stars': data['total_stars'],
                    'stars_today': data['stars_today'],
                    'forks': data['forks'],
                    'since': data['since'],
                    'new_hot_ratio': round(data['new_hot_ratio'], 4),
                    'source_url': url,
                }

                # Store main signal with stars_today as velocity
                await conn.execute('''
                    INSERT INTO signals (platform, entity_raw, entity_normalized,
                                       metric_type, metric_value, url, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                ''', 'github', entity_raw, entity_normalized, 'velocity',
                    data['stars_today'], url, json.dumps(metadata))
                signals_count += 1

                # Flag "new hot" repos (stars_today / total > 0.1 and stars_today > 50)
                if data['new_hot_ratio'] > 0.1 and data['stars_today'] > 50:
                    await conn.execute('''
                        INSERT INTO signals (platform, entity_raw, entity_normalized,
                                           metric_type, metric_value, url, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ''', 'github', entity_raw, entity_normalized, 'new_hot',
                        data['new_hot_ratio'], url, json.dumps(metadata))
                    signals_count += 1
                    print(f"[GitHub] NEW HOT: {repo_name} ({data['new_hot_ratio']:.1%}) - {data['stars_today']} stars today")

        print(f"[GitHub] Stored {signals_count} signals")
        return signals_count
