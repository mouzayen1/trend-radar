"""
Google Trends Collector
Tracks trending searches and breakout terms
Uses pytrends library (no API key needed)
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
import sys
sys.path.append('..')
from utils.stopwords import is_valid_entity

# pytrends is synchronous, we'll run it in executor
from pytrends.request import TrendReq


class GoogleTrendsCollector:
    # Categories for Google Trends
    # https://github.com/pat310/google-trends-api/wiki/Google-Trends-Categories
    CATEGORIES = {
        0: 'all',           # All categories
        5: 'computers',     # Computers & Electronics
        16: 'news',         # News
        3: 'entertainment', # Arts & Entertainment
        12: 'business',     # Business & Industrial
        174: 'gaming',      # Games
    }

    BREAKOUT_THRESHOLD = 5000  # 5000% growth = breakout

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.pytrends = None

    async def __aenter__(self):
        # Initialize pytrends in executor since it makes network calls
        loop = asyncio.get_event_loop()
        self.pytrends = await loop.run_in_executor(
            None,
            lambda: TrendReq(hl='en-US', tz=360)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def collect(self) -> int:
        """Main collection routine"""
        print("[GoogleTrends] Starting collection...")
        total_signals = 0

        # Collect daily trending searches
        try:
            count = await self.collect_daily_trends()
            total_signals += count
        except Exception as e:
            print(f"[GoogleTrends] Error collecting daily trends: {e}")

        await asyncio.sleep(1)  # Be nice to Google

        # Collect realtime trending searches
        try:
            count = await self.collect_realtime_trends()
            total_signals += count
        except Exception as e:
            print(f"[GoogleTrends] Error collecting realtime trends: {e}")

        print(f"[GoogleTrends] Stored {total_signals} signals")
        return total_signals

    async def collect_daily_trends(self) -> int:
        """Collect daily trending searches"""
        loop = asyncio.get_event_loop()

        try:
            # Get trending searches for US
            df = await loop.run_in_executor(
                None,
                lambda: self.pytrends.trending_searches(pn='united_states')
            )

            if df is None or df.empty:
                print("[GoogleTrends] No daily trends found")
                return 0

            trends = df[0].tolist()  # First column contains the trends
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
                rank_score = max(1, 100 - i * 3)  # Top result gets 100, decreasing

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

        except Exception as e:
            print(f"[GoogleTrends] Daily trends error: {e}")
            return 0

    async def collect_realtime_trends(self) -> int:
        """Collect realtime trending topics"""
        loop = asyncio.get_event_loop()
        total = 0

        for cat_id, cat_name in self.CATEGORIES.items():
            try:
                # realtime_trending_searches returns trending stories
                df = await loop.run_in_executor(
                    None,
                    lambda cid=cat_id: self.pytrends.realtime_trending_searches(
                        pn='US',
                        cat=cid,
                        count=20
                    ) if cid > 0 else self.pytrends.realtime_trending_searches(pn='US', count=20)
                )

                if df is None or df.empty:
                    continue

                # Extract titles from the dataframe
                if 'title' in df.columns:
                    titles = df['title'].tolist()
                elif 'entityNames' in df.columns:
                    titles = df['entityNames'].tolist()
                else:
                    # Try first column
                    titles = df.iloc[:, 0].tolist()

                signals = []
                for i, title in enumerate(titles):
                    if not title:
                        continue

                    # Handle list of entity names
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
                        'metric_value': 100 - i * 4,  # Score based on rank
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

                await asyncio.sleep(0.5)  # Rate limit

            except Exception as e:
                # Realtime trends often fails, just log and continue
                if "429" in str(e) or "rate" in str(e).lower():
                    print(f"[GoogleTrends] Rate limited on {cat_name}, skipping...")
                    await asyncio.sleep(2)
                continue

        return total

    async def collect_related_queries(self, keyword: str) -> list:
        """Get related queries for a keyword (for enrichment)"""
        loop = asyncio.get_event_loop()

        try:
            await loop.run_in_executor(
                None,
                lambda: self.pytrends.build_payload([keyword], timeframe='now 1-d', geo='US')
            )

            related = await loop.run_in_executor(
                None,
                lambda: self.pytrends.related_queries()
            )

            if not related or keyword not in related:
                return []

            results = []

            # Get rising queries (these show growth %)
            rising = related[keyword].get('rising')
            if rising is not None and not rising.empty:
                for _, row in rising.iterrows():
                    query = row.get('query', '')
                    value = row.get('value', 0)

                    # Check for breakout terms
                    is_breakout = False
                    if isinstance(value, str) and 'Breakout' in value:
                        is_breakout = True
                        value = self.BREAKOUT_THRESHOLD

                    results.append({
                        'query': query,
                        'growth': value,
                        'is_breakout': is_breakout
                    })

            return results

        except Exception as e:
            return []

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
                        signal['metadata']
                    )
                except Exception as e:
                    # Likely duplicate, skip
                    pass
