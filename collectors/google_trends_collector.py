"""
Google Trends Collector - RSS Version
Uses public RSS feed (never gets blocked)
No API key needed, no pytrends dependency
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

import feedparser


class GoogleTrendsCollector:
    # Google Trends RSS feeds
    RSS_FEEDS = {
        'daily_us': 'https://trends.google.com/trends/trendingsearches/daily/rss?geo=US',
    }

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def collect(self) -> int:
        """Main collection routine using RSS feeds"""
        print("[GoogleTrends] Starting collection (RSS mode)...")
        total_signals = 0

        for feed_name, feed_url in self.RSS_FEEDS.items():
            try:
                count = await self.collect_feed(feed_url, feed_name)
                total_signals += count
            except Exception as e:
                print(f"[GoogleTrends] Error collecting {feed_name}: {e}")

        if total_signals > 0:
            print(f"[GoogleTrends] Stored {total_signals} signals")
        else:
            print("[GoogleTrends] No new signals this cycle")

        return total_signals

    async def collect_feed(self, feed_url: str, feed_name: str) -> int:
        """Collect trends from RSS feed"""
        try:
            async with self.session.get(
                feed_url,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    print(f"[GoogleTrends] RSS error {resp.status}")
                    return 0

                content = await resp.text()

            # Parse RSS feed
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(
                None,
                lambda: feedparser.parse(content)
            )

            if not feed.entries:
                print("[GoogleTrends] No entries in RSS feed")
                return 0

            print(f"[GoogleTrends] Found {len(feed.entries)} trending searches")

            signals = []
            for i, entry in enumerate(feed.entries):
                signal = self.process_entry(entry, i, feed_name)
                if signal:
                    signals.append(signal)

            if signals:
                await self.store_signals(signals)

            return len(signals)

        except asyncio.TimeoutError:
            print("[GoogleTrends] RSS feed timeout")
            return 0
        except Exception as e:
            print(f"[GoogleTrends] Error: {e}")
            return 0

    def process_entry(self, entry: dict, rank: int, feed_name: str) -> Optional[dict]:
        """Process a single RSS entry"""
        try:
            title = entry.get('title', '').strip()
            link = entry.get('link', '')

            if not title or len(title) < 2:
                return None

            # Skip if not a valid entity
            if not is_valid_entity(title.lower()):
                return None

            # Get traffic estimate if available (in ht:approx_traffic)
            traffic = 0
            if hasattr(entry, 'ht_approx_traffic'):
                traffic_str = entry.ht_approx_traffic.replace(',', '').replace('+', '')
                try:
                    traffic = int(traffic_str)
                except:
                    pass

            # Get related news if available
            related_news = []
            if hasattr(entry, 'ht_news_item'):
                news_items = entry.ht_news_item if isinstance(entry.ht_news_item, list) else [entry.ht_news_item]
                for news in news_items[:3]:
                    if hasattr(news, 'ht_news_item_title'):
                        related_news.append(news.ht_news_item_title)

            # Rank-based score (top = 100, decreasing)
            rank_score = max(1, 100 - rank * 3)

            # Extract additional entities from title
            entities = self.extract_entities(title)

            return {
                'entity_raw': title,
                'entity_normalized': title.lower(),
                'platform': 'google_trends',
                'metric_type': 'daily_trend',
                'metric_value': rank_score,
                'url': link or f"https://trends.google.com/trends/explore?q={title.replace(' ', '%20')}&geo=US",
                'metadata': {
                    'trend_type': 'daily',
                    'rank': rank + 1,
                    'region': 'US',
                    'traffic': traffic,
                    'related_news': related_news[:3],
                    'all_entities': entities[:5],
                }
            }

        except Exception as e:
            return None

    def extract_entities(self, title: str) -> list:
        """Extract additional entities from trend title"""
        entities = [title]  # Primary entity is the title itself

        # Extract quoted strings
        quoted = re.findall(r'"([^"]+)"', title)
        for q in quoted:
            if len(q) >= 2 and is_valid_entity(q.lower()):
                entities.append(q)

        # Extract capitalized words (proper nouns)
        caps = re.findall(r'\b([A-Z][a-z]{2,})\b', title)
        for c in caps:
            if is_valid_entity(c.lower()):
                entities.append(c)

        # Deduplicate
        seen = set()
        unique = []
        for e in entities:
            lower = e.lower()
            if lower not in seen:
                seen.add(lower)
                unique.append(e)

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
