"""
Google Trends Collector
Tracks trending searches and breakout terms
Uses pytrends library (no API key needed)
Resilient to Google's blocking - retries with backoff
"""

import asyncio
import json
import random
from datetime import datetime, timezone
from typing import Optional
import sys
sys.path.append('..')
from utils.stopwords import is_valid_entity

# pytrends is synchronous, we'll run it in executor
from pytrends.request import TrendReq


class GoogleTrendsCollector:
    # Categories for Google Trends
    CATEGORIES = {
        0: 'all',
        5: 'computers',
        16: 'news',
        3: 'entertainment',
        12: 'business',
    }

    # Retry settings
    MAX_RETRIES = 3
    BASE_DELAY = 2  # Base delay in seconds
    MAX_DELAY = 10  # Max delay between retries

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.pytrends = None

    async def __aenter__(self):
        # Initialize pytrends with resilient settings
        loop = asyncio.get_event_loop()
        self.pytrends = await loop.run_in_executor(
            None,
            lambda: TrendReq(
                hl='en-US',
                tz=360,
                timeout=(10, 25),
                retries=3,
                backoff_factor=0.5
            )
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def collect(self) -> int:
        """Main collection routine - resilient to failures"""
        print("[GoogleTrends] Starting collection...")

        # Initial delay to avoid hitting Google too fast after other collectors
        await asyncio.sleep(random.uniform(5, 10))

        total_signals = 0

        # Try daily trends first (most reliable)
        count = await self._safe_collect(self.collect_daily_trends, "daily trends")
        total_signals += count

        # Random delay between methods
        await asyncio.sleep(random.uniform(3, 6))

        # Try realtime trends (less reliable but worth trying)
        count = await self._safe_collect(self.collect_realtime_trends, "realtime trends")
        total_signals += count

        if total_signals > 0:
            print(f"[GoogleTrends] Stored {total_signals} signals")
        else:
            print("[GoogleTrends] No signals collected this cycle (Google may be blocking)")

        return total_signals

    async def _safe_collect(self, collect_func, name: str) -> int:
        """Safely run a collection method with retries"""
        for attempt in range(self.MAX_RETRIES):
            try:
                count = await collect_func()
                return count
            except Exception as e:
                error_str = str(e)

                # Check for known blocking errors
                if "404" in error_str or "429" in error_str or "response" in error_str.lower():
                    delay = min(self.BASE_DELAY * (2 ** attempt) + random.uniform(1, 3), self.MAX_DELAY)

                    if attempt < self.MAX_RETRIES - 1:
                        print(f"[GoogleTrends] {name} blocked (attempt {attempt + 1}), retrying in {delay:.1f}s...")
                        await asyncio.sleep(delay)
                    else:
                        print(f"[GoogleTrends] {name} failed after {self.MAX_RETRIES} attempts, skipping")
                else:
                    print(f"[GoogleTrends] {name} error: {error_str[:100]}")
                    break

        return 0

    async def collect_daily_trends(self) -> int:
        """Collect daily trending searches - most reliable method"""
        loop = asyncio.get_event_loop()

        # Get trending searches for US
        df = await loop.run_in_executor(
            None,
            lambda: self.pytrends.trending_searches(pn='united_states')
        )

        if df is None or df.empty:
            print("[GoogleTrends] No daily trends found")
            return 0

        trends = df[0].tolist()
        print(f"[GoogleTrends] Found {len(trends)} daily trending searches")

        signals = []
        for i, trend in enumerate(trends):
            if not trend or not isinstance(trend, str):
                continue

            trend = trend.strip()
            if len(trend) < 2:
                continue

            if not is_valid_entity(trend.lower()):
                continue

            # Rank-based score (higher rank = more trending)
            rank_score = max(1, 100 - i * 3)

            signals.append({
                'entity_raw': trend,
                'entity_normalized': trend.lower(),
                'platform': 'google_trends',
                'metric_type': 'daily_trend',
                'metric_value': rank_score,
                'url': f"https://trends.google.com/trends/explore?q={trend.replace(' ', '%20')}&geo=US",
                'metadata': {
                    'trend_type': 'daily',
                    'rank': i + 1,
                    'region': 'US',
                }
            })

        if signals:
            await self.store_signals(signals)

        return len(signals)

    async def collect_realtime_trends(self) -> int:
        """Collect realtime trending topics - less reliable"""
        loop = asyncio.get_event_loop()
        total = 0

        # Only try a few categories to reduce API calls
        categories_to_try = [(0, 'all'), (5, 'computers'), (3, 'entertainment')]

        for cat_id, cat_name in categories_to_try:
            try:
                # Random delay between category requests
                await asyncio.sleep(random.uniform(2, 4))

                df = await loop.run_in_executor(
                    None,
                    lambda cid=cat_id: self.pytrends.realtime_trending_searches(
                        pn='US',
                        cat=cid,
                        count=15
                    ) if cid > 0 else self.pytrends.realtime_trending_searches(pn='US', count=15)
                )

                if df is None or df.empty:
                    continue

                # Extract titles from the dataframe
                if 'title' in df.columns:
                    titles = df['title'].tolist()
                elif 'entityNames' in df.columns:
                    titles = df['entityNames'].tolist()
                else:
                    titles = df.iloc[:, 0].tolist()

                signals = []
                for i, title in enumerate(titles):
                    if not title:
                        continue

                    if isinstance(title, list):
                        title = title[0] if title else ''

                    title = str(title).strip()
                    if len(title) < 2:
                        continue

                    if not is_valid_entity(title.lower()):
                        continue

                    signals.append({
                        'entity_raw': title,
                        'entity_normalized': title.lower(),
                        'platform': 'google_trends',
                        'metric_type': 'realtime_trend',
                        'metric_value': 100 - i * 4,
                        'url': f"https://trends.google.com/trends/explore?q={title.replace(' ', '%20')}&geo=US",
                        'metadata': {
                            'trend_type': 'realtime',
                            'category': cat_name,
                            'rank': i + 1,
                            'region': 'US',
                        }
                    })

                if signals:
                    await self.store_signals(signals)
                    total += len(signals)
                    print(f"[GoogleTrends] Found {len(signals)} realtime trends in {cat_name}")

            except Exception as e:
                # Don't let one category failure stop others
                if "429" in str(e) or "404" in str(e):
                    print(f"[GoogleTrends] {cat_name} blocked, skipping...")
                    await asyncio.sleep(random.uniform(3, 5))
                continue

        return total

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
                    pass
