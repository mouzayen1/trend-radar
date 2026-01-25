"""
YouTube Trending Collector
Tracks trending videos and extracts entities from viral content
Uses YouTube Data API v3
"""

import asyncio
import aiohttp
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
import sys
sys.path.append('..')
from utils.stopwords import is_valid_entity


class YouTubeCollector:
    BASE_URL = "https://www.googleapis.com/youtube/v3"

    # Category IDs for trending topics
    CATEGORIES = {
        '20': 'gaming',
        '24': 'entertainment',
        '10': 'music',
        '28': 'science_tech',
        '25': 'news',
    }

    # Velocity thresholds (views per hour)
    HIGH_VELOCITY_THRESHOLD = 10000  # 10k views/hour is notable
    VIRAL_VELOCITY_THRESHOLD = 50000  # 50k views/hour is viral

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.api_key = os.getenv('YOUTUBE_API_KEY')
        self.session: Optional[aiohttp.ClientSession] = None

        if not self.api_key:
            print("[YouTube] WARNING: YOUTUBE_API_KEY not set")

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def collect(self) -> int:
        """Main collection routine"""
        if not self.api_key:
            print("[YouTube] Skipping - no API key")
            return 0

        print("[YouTube] Starting collection...")
        total_signals = 0

        # Collect trending videos from each category
        for category_id, category_name in self.CATEGORIES.items():
            try:
                count = await self.collect_trending(category_id, category_name)
                total_signals += count
                await asyncio.sleep(0.5)  # Rate limit courtesy
            except Exception as e:
                print(f"[YouTube] Error collecting {category_name}: {e}")

        # Also collect overall trending (no category filter)
        try:
            count = await self.collect_trending(None, 'all')
            total_signals += count
        except Exception as e:
            print(f"[YouTube] Error collecting all trending: {e}")

        print(f"[YouTube] Stored {total_signals} signals")
        return total_signals

    async def collect_trending(self, category_id: Optional[str], category_name: str) -> int:
        """Collect trending videos for a category"""
        params = {
            'part': 'snippet,statistics',
            'chart': 'mostPopular',
            'regionCode': 'US',
            'maxResults': 50,
            'key': self.api_key,
        }

        if category_id:
            params['videoCategoryId'] = category_id

        try:
            async with self.session.get(
                f"{self.BASE_URL}/videos",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[YouTube] API error {resp.status}: {text[:100]}")
                    return 0

                data = await resp.json()
                videos = data.get('items', [])
                print(f"[YouTube] Found {len(videos)} trending in {category_name}")

                signals = []
                for video in videos:
                    signal = await self.process_video(video, category_name)
                    if signal:
                        signals.append(signal)

                if signals:
                    await self.store_signals(signals)

                return len(signals)

        except asyncio.TimeoutError:
            print(f"[YouTube] Timeout fetching {category_name}")
            return 0
        except Exception as e:
            print(f"[YouTube] Error: {e}")
            return 0

    async def process_video(self, video: dict, category: str) -> Optional[dict]:
        """Process a video and extract signal data"""
        try:
            snippet = video.get('snippet', {})
            stats = video.get('statistics', {})
            video_id = video.get('id')

            title = snippet.get('title', '')
            channel = snippet.get('channelTitle', '')
            published_at = snippet.get('publishedAt', '')

            view_count = int(stats.get('viewCount', 0))
            like_count = int(stats.get('likeCount', 0))
            comment_count = int(stats.get('commentCount', 0))

            # Calculate velocity (views per hour since upload)
            velocity = 0
            hours_since_upload = 0
            if published_at:
                try:
                    pub_time = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                    hours_since_upload = (datetime.now(timezone.utc) - pub_time).total_seconds() / 3600
                    if hours_since_upload > 0:
                        velocity = view_count / hours_since_upload
                except:
                    pass

            # Extract entities from title
            entities = self.extract_entities(title)

            if not entities:
                return None

            # Determine if this is notably viral
            is_viral = velocity >= self.VIRAL_VELOCITY_THRESHOLD
            is_high_velocity = velocity >= self.HIGH_VELOCITY_THRESHOLD

            # Use primary entity (first valid one)
            primary_entity = entities[0]

            return {
                'entity_raw': primary_entity,
                'entity_normalized': primary_entity.lower(),
                'platform': 'youtube',
                'metric_type': 'trending_video',
                'metric_value': velocity,
                'url': f"https://youtube.com/watch?v={video_id}",
                'metadata': {
                    'title': title[:200],
                    'channel': channel,
                    'category': category,
                    'view_count': view_count,
                    'like_count': like_count,
                    'comment_count': comment_count,
                    'velocity_views_per_hour': round(velocity, 2),
                    'hours_since_upload': round(hours_since_upload, 2),
                    'is_viral': is_viral,
                    'is_high_velocity': is_high_velocity,
                    'all_entities': entities[:5],
                }
            }

        except Exception as e:
            print(f"[YouTube] Error processing video: {e}")
            return None

    def extract_entities(self, title: str) -> list:
        """Extract meaningful entities from video title"""
        entities = []

        # Remove common YouTube title patterns
        title = re.sub(r'\s*[\|\-\#]\s*', ' ', title)
        title = re.sub(r'\s*\([^)]*official[^)]*\)\s*', ' ', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*\[[^\]]*\]\s*', ' ', title)

        # Extract quoted strings
        quoted = re.findall(r'"([^"]+)"', title)
        for q in quoted:
            if len(q) >= 3 and is_valid_entity(q.lower()):
                entities.append(q)

        # Extract CamelCase words
        camel = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', title)
        for c in camel:
            if is_valid_entity(c.lower()):
                entities.append(c)

        # Extract capitalized phrases (potential names/titles)
        caps = re.findall(r'\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b', title)
        for c in caps:
            if len(c) >= 5 and is_valid_entity(c.lower()):
                entities.append(c)

        # Extract hashtag-style words
        hashtags = re.findall(r'#(\w+)', title)
        for h in hashtags:
            if len(h) >= 3 and is_valid_entity(h.lower()):
                entities.append(h)

        # Extract standalone capitalized words (potential product names)
        words = re.findall(r'\b([A-Z][A-Z0-9]{2,})\b', title)
        for w in words:
            if is_valid_entity(w.lower()):
                entities.append(w)

        # Deduplicate while preserving order
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
                        signal['metadata']
                    )
                except Exception as e:
                    print(f"[YouTube] DB error: {e}")
