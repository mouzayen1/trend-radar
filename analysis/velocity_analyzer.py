"""
Velocity Analyzer - Strict Version
Only alerts on REAL trends with cross-platform validation
Requires significant signal volume and proper growth tracking
"""

import math
from datetime import datetime, timezone, timedelta
import json
import sys
sys.path.append('..')
from utils.stopwords import is_valid_entity


class VelocityAnalyzer:
    # STRICT thresholds - only real trends get through
    THRESHOLDS = {
        'emergence': {
            'trend_score_min': 80,
            'novelty_min': 85,
            'signals_min': 20,
            'platforms_min': 2,  # MUST be cross-platform
        },
        'acceleration': {
            'trend_score_min': 80,
            'acceleration_min': 5.0,  # 5x growth
            'signals_min': 25,
            'platforms_min': 2,  # MUST be cross-platform
        },
        'cross_platform': {
            'platform_count_min': 2,  # This is the key requirement
            'trend_score_min': 80,
            'signals_min': 15,
        },
        'anomaly': {
            'spike_ratio_min': 10,  # 10x baseline
            'signals_min': 20,
            'platforms_min': 2,
            'min_baseline_hours': 6,  # Need 6+ hours of baseline data
        }
    }

    # Minimum requirements for ANY alert
    MIN_SIGNALS_FOR_ALERT = 15
    MIN_PLATFORMS_FOR_ALERT = 2  # Cross-platform required
    MIN_DATA_POINTS_FOR_GROWTH = 3  # Need 3+ data points
    MIN_HOURS_FOR_BASELINE = 6  # Need 6+ hours of data

    # GitHub quality filter
    MIN_GITHUB_STARS_TODAY = 100

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def analyze(self) -> list[dict]:
        """
        Main analysis routine - only returns entities worth alerting
        """
        print("[Analyzer] Starting analysis...")
        now = datetime.now(timezone.utc)

        async with self.db_pool.acquire() as conn:
            # Get entities that appear on BOTH platforms (cross-platform only)
            cross_platform_entities = await conn.fetch('''
                SELECT entity_normalized,
                       COUNT(DISTINCT platform) as platform_count,
                       COUNT(*) as signal_count
                FROM signals
                WHERE timestamp > $1
                  AND entity_normalized IS NOT NULL
                  AND LENGTH(entity_normalized) >= 2
                GROUP BY entity_normalized
                HAVING COUNT(DISTINCT platform) >= 2
                   AND COUNT(*) >= $2
                ORDER BY COUNT(*) DESC
            ''', now - timedelta(hours=24), self.MIN_SIGNALS_FOR_ALERT)

            print(f"[Analyzer] Found {len(cross_platform_entities)} cross-platform entities with {self.MIN_SIGNALS_FOR_ALERT}+ signals")

            results = []
            for row in cross_platform_entities:
                entity = row['entity_normalized']

                # Skip invalid entities
                if not is_valid_entity(entity):
                    continue

                metrics = await self.calculate_metrics(conn, entity, now)
                if metrics and self.passes_quality_filter(metrics):
                    results.append(metrics)
                    await self.store_metrics(conn, metrics)

            # Sort by trend score
            results.sort(key=lambda x: x['trend_score'], reverse=True)
            print(f"[Analyzer] {len(results)} entities pass quality filters")

            # Log top entities
            if results:
                print("[Analyzer] Top trending (cross-platform, quality-filtered):")
                for i, m in enumerate(results[:10], 1):
                    growth_str = f"growth: {m['growth_rate']:.1f}x" if m.get('growth_rate') else "growth: calculating..."
                    print(f"  {i}. {m['entity_display']} (signals: {m['signals_24h']}, "
                          f"platforms: {m['platforms_seen']}, {growth_str})")

            return results

    def passes_quality_filter(self, metrics: dict) -> bool:
        """Check if entity passes minimum quality requirements"""
        # Must have minimum signals
        if metrics['signals_24h'] < self.MIN_SIGNALS_FOR_ALERT:
            return False

        # Must be cross-platform
        if metrics['platform_count'] < self.MIN_PLATFORMS_FOR_ALERT:
            return False

        # If from GitHub, must have significant stars
        if 'github' in metrics['platforms_seen']:
            github_stars = metrics.get('github_stars_today', 0)
            if github_stars < self.MIN_GITHUB_STARS_TODAY:
                return False

        return True

    async def calculate_metrics(self, conn, entity: str, now: datetime) -> dict | None:
        """Calculate comprehensive metrics for an entity"""

        # Get signal counts at different time windows
        signals_1h = await conn.fetchval('''
            SELECT COUNT(*) FROM signals
            WHERE entity_normalized = $1 AND timestamp > $2
        ''', entity, now - timedelta(hours=1))

        signals_3h = await conn.fetchval('''
            SELECT COUNT(*) FROM signals
            WHERE entity_normalized = $1 AND timestamp > $2
        ''', entity, now - timedelta(hours=3))

        signals_6h = await conn.fetchval('''
            SELECT COUNT(*) FROM signals
            WHERE entity_normalized = $1 AND timestamp > $2
        ''', entity, now - timedelta(hours=6))

        signals_12h = await conn.fetchval('''
            SELECT COUNT(*) FROM signals
            WHERE entity_normalized = $1 AND timestamp > $2
        ''', entity, now - timedelta(hours=12))

        signals_24h = await conn.fetchval('''
            SELECT COUNT(*) FROM signals
            WHERE entity_normalized = $1 AND timestamp > $2
        ''', entity, now - timedelta(hours=24))

        if signals_24h < self.MIN_SIGNALS_FOR_ALERT:
            return None

        # Get platforms
        platforms = await conn.fetch('''
            SELECT DISTINCT platform FROM signals
            WHERE entity_normalized = $1 AND timestamp > $2
        ''', entity, now - timedelta(hours=24))
        platforms_seen = [p['platform'] for p in platforms]
        platform_count = len(platforms_seen)

        if platform_count < self.MIN_PLATFORMS_FOR_ALERT:
            return None

        # Get first seen timestamp
        first_seen = await conn.fetchval('''
            SELECT MIN(timestamp) FROM signals
            WHERE entity_normalized = $1
        ''', entity)

        # Calculate data age (for baseline validity)
        data_age_hours = (now - first_seen).total_seconds() / 3600 if first_seen else 0

        # Calculate REAL growth rate (hour-over-hour comparison)
        growth_rate = None
        acceleration = 0

        if data_age_hours >= self.MIN_HOURS_FOR_BASELINE:
            # Get signals from 6-12 hours ago (baseline period)
            baseline_signals = await conn.fetchval('''
                SELECT COUNT(*) FROM signals
                WHERE entity_normalized = $1
                  AND timestamp > $2
                  AND timestamp <= $3
            ''', entity, now - timedelta(hours=12), now - timedelta(hours=6))

            # Get signals from last 6 hours (recent period)
            recent_signals = signals_6h

            if baseline_signals and baseline_signals >= self.MIN_DATA_POINTS_FOR_GROWTH:
                # Calculate growth rate
                growth_rate = recent_signals / baseline_signals if baseline_signals > 0 else None

                # Calculate acceleration (change in velocity)
                baseline_velocity = baseline_signals / 6.0  # signals per hour in baseline
                recent_velocity = recent_signals / 6.0  # signals per hour recently

                if baseline_velocity > 0:
                    acceleration = (recent_velocity - baseline_velocity) / baseline_velocity

        # Get GitHub stars if applicable
        github_stars_today = 0
        if 'github' in platforms_seen:
            stars_row = await conn.fetchrow('''
                SELECT metadata->>'stars_today' as stars
                FROM signals
                WHERE entity_normalized = $1
                  AND platform = 'github'
                  AND metadata->>'stars_today' IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT 1
            ''', entity)
            if stars_row and stars_row['stars']:
                try:
                    github_stars_today = int(stars_row['stars'])
                except:
                    pass

        # Calculate trend score (weighted by cross-platform and growth)
        base_score = math.log1p(signals_24h) * 10
        platform_multiplier = 1 + (platform_count - 1) * 0.5  # Bonus for cross-platform
        growth_bonus = 0
        if growth_rate and growth_rate > 1:
            growth_bonus = min(growth_rate - 1, 5) * 20  # Cap at 5x growth bonus

        trend_score = (base_score + growth_bonus) * platform_multiplier

        # Calculate novelty score
        if data_age_hours < 6:
            novelty_score = 95
        elif data_age_hours < 12:
            novelty_score = 85
        elif data_age_hours < 24:
            novelty_score = 70
        elif data_age_hours < 48:
            novelty_score = 50
        else:
            novelty_score = max(20, 50 - (data_age_hours - 48) / 24)

        # Get display name
        raw_name = await conn.fetchval('''
            SELECT entity_raw FROM signals
            WHERE entity_normalized = $1
            ORDER BY timestamp DESC
            LIMIT 1
        ''', entity)

        # Get description
        description = await conn.fetchval('''
            SELECT metadata->>'description' FROM signals
            WHERE entity_normalized = $1 AND metadata->>'description' IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 1
        ''', entity)

        # Get URLs
        urls = await conn.fetch('''
            SELECT DISTINCT url FROM signals
            WHERE entity_normalized = $1 AND timestamp > $2 AND url IS NOT NULL
            LIMIT 5
        ''', entity, now - timedelta(hours=24))
        all_urls = [u['url'] for u in urls]

        return {
            'entity': entity,
            'entity_display': raw_name or entity,
            'description': description or f"Trending: {raw_name or entity}",
            'signals_1h': signals_1h,
            'signals_3h': signals_3h,
            'signals_6h': signals_6h,
            'signals_12h': signals_12h,
            'signals_24h': signals_24h,
            'growth_rate': growth_rate,
            'acceleration': acceleration,
            'platform_count': platform_count,
            'platforms_seen': platforms_seen,
            'trend_score': round(trend_score, 2),
            'novelty_score': round(novelty_score, 2),
            'first_seen': first_seen,
            'data_age_hours': data_age_hours,
            'github_stars_today': github_stars_today,
            'sample_url': all_urls[0] if all_urls else None,
            'all_urls': all_urls,
            'has_valid_baseline': data_age_hours >= self.MIN_HOURS_FOR_BASELINE,
        }

    async def store_metrics(self, conn, metrics: dict):
        """Store computed metrics"""
        await conn.execute('''
            INSERT INTO velocity_metrics
            (entity_normalized, platform, current_value, velocity_1h, velocity_6h,
             velocity_24h, acceleration, platform_count, platforms_seen,
             trend_score, novelty_score, confidence_score)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        ''',
            metrics['entity'],
            ','.join(metrics['platforms_seen']),
            metrics['signals_24h'],
            metrics['signals_1h'],
            metrics['signals_6h'],
            metrics['signals_24h'] / 24.0,
            metrics['acceleration'],
            metrics['platform_count'],
            metrics['platforms_seen'],
            metrics['trend_score'],
            metrics['novelty_score'],
            50  # placeholder confidence
        )

    async def detect_anomalies(self) -> list[dict]:
        """Find entities with unusual spikes - requires valid baseline"""
        now = datetime.now(timezone.utc)
        anomalies = []

        async with self.db_pool.acquire() as conn:
            # Only check entities with 6+ hours of data and cross-platform presence
            entities = await conn.fetch('''
                SELECT entity_normalized,
                       COUNT(*) as recent_count,
                       MIN(timestamp) as first_seen
                FROM signals
                WHERE timestamp > $1
                GROUP BY entity_normalized
                HAVING COUNT(*) >= $2
                   AND COUNT(DISTINCT platform) >= 2
            ''', now - timedelta(hours=1), self.THRESHOLDS['anomaly']['signals_min'])

            for row in entities:
                entity = row['entity_normalized']
                first_seen = row['first_seen']

                if not is_valid_entity(entity):
                    continue

                # Check data age
                data_age = (now - first_seen).total_seconds() / 3600
                if data_age < self.THRESHOLDS['anomaly']['min_baseline_hours']:
                    continue  # Not enough baseline data

                count_1h = row['recent_count']

                # Get baseline (6-24 hours ago)
                baseline = await conn.fetchval('''
                    SELECT COUNT(*) / 18.0 FROM signals
                    WHERE entity_normalized = $1
                      AND timestamp > $2
                      AND timestamp <= $3
                ''', entity, now - timedelta(hours=24), now - timedelta(hours=6))

                if not baseline or baseline < 1:
                    continue  # Need real baseline, not 0

                spike_ratio = count_1h / baseline

                if spike_ratio >= self.THRESHOLDS['anomaly']['spike_ratio_min']:
                    metrics = await self.calculate_metrics(conn, entity, now)
                    if metrics and self.passes_quality_filter(metrics):
                        anomalies.append({
                            **metrics,
                            'spike_ratio': spike_ratio,
                            'baseline_per_hour': baseline,
                            'count_1h': count_1h
                        })

            anomalies.sort(key=lambda x: x['spike_ratio'], reverse=True)
            if anomalies:
                print(f"[Analyzer] Detected {len(anomalies)} real anomalies (with valid baselines)")

            return anomalies

    def qualifies_for_alert(self, metrics: dict, alert_type: str) -> bool:
        """Check if metrics qualify for a specific alert type - STRICT"""
        t = self.THRESHOLDS.get(alert_type, {})

        # Global requirements - ALL alerts need these
        if metrics['signals_24h'] < self.MIN_SIGNALS_FOR_ALERT:
            return False
        if metrics['platform_count'] < self.MIN_PLATFORMS_FOR_ALERT:
            return False

        if alert_type == 'emergence':
            return (
                metrics['trend_score'] >= t.get('trend_score_min', 80) and
                metrics['novelty_score'] >= t.get('novelty_min', 85) and
                metrics['signals_24h'] >= t.get('signals_min', 20) and
                metrics['platform_count'] >= t.get('platforms_min', 2)
            )
        elif alert_type == 'acceleration':
            # Need valid growth rate calculation
            if not metrics.get('has_valid_baseline'):
                return False
            if not metrics.get('growth_rate'):
                return False
            return (
                metrics['trend_score'] >= t.get('trend_score_min', 80) and
                metrics['growth_rate'] >= t.get('acceleration_min', 5.0) and
                metrics['signals_24h'] >= t.get('signals_min', 25) and
                metrics['platform_count'] >= t.get('platforms_min', 2)
            )
        elif alert_type == 'cross_platform':
            return (
                metrics['platform_count'] >= t.get('platform_count_min', 2) and
                metrics['trend_score'] >= t.get('trend_score_min', 80) and
                metrics['signals_24h'] >= t.get('signals_min', 15)
            )
        elif alert_type == 'anomaly':
            if not metrics.get('has_valid_baseline'):
                return False
            return (
                metrics.get('spike_ratio', 0) >= t.get('spike_ratio_min', 10) and
                metrics['signals_24h'] >= t.get('signals_min', 20) and
                metrics['platform_count'] >= t.get('platforms_min', 2)
            )

        return False
