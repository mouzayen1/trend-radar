"""
Google Trends Collector - DISABLED
Google has deprecated RSS feeds and blocks pytrends from cloud servers.
This collector is kept for structure but returns 0 signals.
"""

import asyncio
from typing import Optional


class GoogleTrendsCollector:
    """
    Google Trends is currently disabled because:
    - RSS feeds return 404 (deprecated)
    - pytrends gets blocked from cloud servers

    We have 5 other reliable sources:
    - HackerNews, GitHub, YouTube, Reddit
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def collect(self) -> int:
        """Google Trends disabled - returns 0"""
        # Silently skip - don't log errors since it's intentionally disabled
        return 0
