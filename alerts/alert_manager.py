"""
Alert Manager - Strict Version
Only sends alerts for REAL cross-platform trends
Max 5 high-quality alerts per day expected
"""

import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
from typing import Optional
import sys
sys.path.append('..')
from utils.stopwords import is_valid_entity


class AlertManager:
    # Strict rate limiting - quality over quantity
    MAX_ALERTS_PER_HOUR = 5
    MAX_ALERTS_PER_DAY = 10
    RATE_LIMIT_DELAY = 3.0  # Seconds between Discord messages

    # Colors for Discord embeds
    COLORS = {
        'emergence': 0x2ECC71,      # Green
        'acceleration': 0xE67E22,   # Orange
        'cross_platform': 0x3498DB, # Blue
        'anomaly': 0xE74C3C,        # Red
        'digest': 0x9B59B6,         # Purple
        'startup': 0x9B59B6,        # Purple
        'warmup': 0xF39C12,         # Yellow
    }

    def __init__(self, db_pool, webhook_url: str):
        self.db_pool = db_pool
        self.webhook_url = webhook_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.alerts_this_hour = 0
        self.hour_start = datetime.now(timezone.utc)

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def reset_hourly_counter(self):
        """Reset the hourly alert counter if an hour has passed"""
        now = datetime.now(timezone.utc)
        if (now - self.hour_start).total_seconds() >= 3600:
            self.alerts_this_hour = 0
            self.hour_start = now

    async def get_alerts_today(self) -> int:
        """Get count of alerts sent today"""
        async with self.db_pool.acquire() as conn:
            count = await conn.fetchval('''
                SELECT COUNT(*) FROM alerts
                WHERE timestamp > NOW() - INTERVAL '24 hours'
            ''')
            return count or 0

    async def already_alerted(self, entity: str, alert_type: str, hours: int = 48) -> bool:
        """Check if we've already sent this alert recently (48h default)"""
        async with self.db_pool.acquire() as conn:
            count = await conn.fetchval('''
                SELECT COUNT(*) FROM alerts
                WHERE entity_normalized = $1
                  AND alert_type = $2
                  AND timestamp > $3
            ''', entity, alert_type, datetime.now(timezone.utc) - timedelta(hours=hours))
            return count > 0

    async def record_alert(self, entity: str, alert_type: str, trend_score: float,
                          platforms: list, message: str):
        """Record that we sent an alert"""
        async with self.db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO alerts (entity_normalized, alert_type, trend_score,
                                   platforms, message, sent_to)
                VALUES ($1, $2, $3, $4, $5, $6)
            ''', entity, alert_type, trend_score, platforms, message, ['discord'])

    async def send_discord(self, embed: dict, retries: int = 3) -> bool:
        """Send embed to Discord webhook with retry on rate limit"""
        if not self.session:
            self.session = aiohttp.ClientSession()

        payload = {
            'embeds': [embed],
            'username': 'Trend Radar 2.0',
            'avatar_url': 'https://i.imgur.com/AfFp7pu.png'
        }

        for attempt in range(retries):
            try:
                async with self.session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status in (200, 204):
                        return True
                    elif resp.status == 429:
                        try:
                            data = await resp.json()
                            retry_after = data.get('retry_after', 2)
                        except:
                            retry_after = 2
                        print(f"[Alert] Rate limited, waiting {retry_after}s...")
                        await asyncio.sleep(retry_after + 0.5)
                        continue
                    else:
                        text = await resp.text()
                        print(f"[Alert] Discord error {resp.status}: {text[:100]}")
                        return False
            except Exception as e:
                print(f"[Alert] Failed to send Discord alert: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                    continue
                return False

        return False

    def format_time_ago(self, hours: float) -> str:
        """Format hours into a human-readable string"""
        if hours < 1:
            return f"{int(hours * 60)} minutes ago"
        elif hours < 24:
            return f"{hours:.1f} hours ago"
        else:
            days = hours / 24
            return f"{days:.1f} days ago"

    def create_rich_embed(self, metrics: dict, alert_type: str) -> dict:
        """Create a detailed, informative Discord embed"""
        color = self.COLORS.get(alert_type, 0x808080)

        entity_name = metrics['entity_display']
        description = metrics.get('description', '')[:300]

        # Build title based on alert type
        if alert_type == 'emergence':
            title = f"🌱 NEW TREND: {entity_name}"
        elif alert_type == 'acceleration':
            title = f"🚀 ACCELERATING: {entity_name}"
        elif alert_type == 'cross_platform':
            title = f"🌐 CROSS-PLATFORM TREND: {entity_name}"
        elif alert_type == 'anomaly':
            title = f"⚡ UNUSUAL SPIKE: {entity_name}"
        else:
            title = f"📊 TREND: {entity_name}"

        # Build description
        desc_parts = []

        # What is it
        desc_parts.append("**📝 What is it:**")
        if description and description.lower() != entity_name.lower():
            desc_parts.append(f"{description}")
        else:
            desc_parts.append(f"_Trending topic across multiple platforms_")
        desc_parts.append("")

        # Why it's trending
        desc_parts.append("**📈 Why it's trending:**")

        # First seen
        data_age = metrics.get('data_age_hours', 0)
        if data_age > 0:
            desc_parts.append(f"• First seen: {self.format_time_ago(data_age)}")

        # Signal growth
        signals_24h = metrics.get('signals_24h', 0)
        signals_6h = metrics.get('signals_6h', 0)
        signals_1h = metrics.get('signals_1h', 0)
        desc_parts.append(f"• Mentions: {signals_24h} total (last hour: {signals_1h}, last 6h: {signals_6h})")

        # Growth rate
        growth_rate = metrics.get('growth_rate')
        if growth_rate and growth_rate > 1:
            desc_parts.append(f"• Growth rate: **{growth_rate:.1f}x** vs baseline")
        elif alert_type == 'anomaly':
            spike = metrics.get('spike_ratio', 0)
            desc_parts.append(f"• Spike: **{spike:.1f}x** normal activity")

        # Platforms
        platforms = metrics.get('platforms_seen', [])
        if platforms:
            platform_str = ' + '.join([p.title() for p in platforms])
            desc_parts.append(f"• Platforms: **{platform_str}**")

        # GitHub stars if applicable
        github_stars = metrics.get('github_stars_today', 0)
        if github_stars > 0:
            desc_parts.append(f"• GitHub: **{github_stars:,}** stars today")

        desc_parts.append("")

        # Links
        desc_parts.append("**🔗 Check it out:**")
        urls = metrics.get('all_urls', [])
        if not urls and metrics.get('sample_url'):
            urls = [metrics['sample_url']]
        for url in urls[:3]:
            desc_parts.append(f"• {url}")

        desc_parts.append("")
        desc_parts.append("━━━━━━━━━━━━━━━━━━━━━━")
        desc_parts.append(f"_Trend Radar 2.0 | Cross-platform validated trend_")

        embed = {
            'title': title,
            'description': '\n'.join(desc_parts),
            'color': color,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

        return embed

    async def check_and_alert(self, metrics_list: list, anomalies: list = None, analyzer=None) -> int:
        """Check all metrics and send alerts for qualifying trends"""
        print("[Alert] Checking for alertable trends...")
        self.reset_hourly_counter()

        # Check daily limit
        alerts_today = await self.get_alerts_today()
        if alerts_today >= self.MAX_ALERTS_PER_DAY:
            print(f"[Alert] Daily limit reached ({alerts_today}/{self.MAX_ALERTS_PER_DAY})")
            return 0

        if self.alerts_this_hour >= self.MAX_ALERTS_PER_HOUR:
            print(f"[Alert] Hourly limit reached ({self.alerts_this_hour}/{self.MAX_ALERTS_PER_HOUR})")
            return 0

        alerts_sent = 0
        pending_alerts = []

        # Collect qualifying alerts - only cross-platform entities
        for metrics in metrics_list:
            entity = metrics['entity']

            # Skip invalid entities
            if not is_valid_entity(entity):
                continue

            # Must be cross-platform
            if metrics['platform_count'] < 2:
                continue

            # Check each alert type
            if analyzer:
                if analyzer.qualifies_for_alert(metrics, 'cross_platform'):
                    if not await self.already_alerted(entity, 'cross_platform'):
                        # Priority: signals + growth rate
                        priority = metrics['signals_24h']
                        if metrics.get('growth_rate'):
                            priority *= metrics['growth_rate']
                        pending_alerts.append((metrics, 'cross_platform', priority))

                if analyzer.qualifies_for_alert(metrics, 'emergence'):
                    if not await self.already_alerted(entity, 'emergence'):
                        priority = metrics['signals_24h'] + (100 - metrics['data_age_hours'])
                        pending_alerts.append((metrics, 'emergence', priority))

                if analyzer.qualifies_for_alert(metrics, 'acceleration'):
                    if not await self.already_alerted(entity, 'acceleration'):
                        growth = metrics.get('growth_rate', 1)
                        priority = metrics['signals_24h'] * growth
                        pending_alerts.append((metrics, 'acceleration', priority))

        # Check anomalies
        if anomalies and analyzer:
            for metrics in anomalies:
                entity = metrics['entity']
                if not is_valid_entity(entity):
                    continue
                if metrics['platform_count'] < 2:
                    continue
                if analyzer.qualifies_for_alert(metrics, 'anomaly'):
                    if not await self.already_alerted(entity, 'anomaly', hours=24):
                        priority = metrics.get('spike_ratio', 1) * metrics['signals_24h']
                        pending_alerts.append((metrics, 'anomaly', priority))

        # Sort by priority and limit
        pending_alerts.sort(key=lambda x: x[2], reverse=True)

        remaining_hourly = self.MAX_ALERTS_PER_HOUR - self.alerts_this_hour
        remaining_daily = self.MAX_ALERTS_PER_DAY - alerts_today
        max_to_send = min(remaining_hourly, remaining_daily)

        print(f"[Alert] Found {len(pending_alerts)} qualifying alerts, can send {max_to_send}")

        for metrics, alert_type, _ in pending_alerts[:max_to_send]:
            entity = metrics['entity']

            embed = self.create_rich_embed(metrics, alert_type)
            if await self.send_discord(embed):
                await self.record_alert(
                    entity, alert_type, metrics['trend_score'],
                    metrics['platforms_seen'],
                    f"{alert_type}: {metrics['entity_display']}"
                )
                alerts_sent += 1
                self.alerts_this_hour += 1
                print(f"[Alert] Sent {alert_type.upper()} for: {entity} "
                      f"(signals: {metrics['signals_24h']}, platforms: {metrics['platform_count']})")
                await asyncio.sleep(self.RATE_LIMIT_DELAY)

        alerts_today_new = alerts_today + alerts_sent
        print(f"[Alert] Sent {alerts_sent} alerts ({alerts_today_new}/{self.MAX_ALERTS_PER_DAY} today)")
        return alerts_sent

    async def send_startup_message(self):
        """Send a message when the system starts in active mode"""
        embed = {
            'title': '🔬 Trend Radar 2.0 - ACTIVE',
            'description': (
                'Trend detection system is now monitoring.\n\n'
                '**Requirements for alerts:**\n'
                '• Must appear on BOTH GitHub AND HackerNews\n'
                '• Minimum 15 signals required\n'
                '• Must show real growth (not just existence)\n\n'
                '**Expected:** 1-5 high-quality alerts per day\n\n'
                '_Only real viral trends will trigger alerts._'
            ),
            'color': 0x2ECC71,  # Green
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'footer': {
                'text': 'Trend Radar 2.0 | Cross-platform validation enabled'
            }
        }
        await self.send_discord(embed)
        print("[Alert] Sent active mode startup message")

    async def send_warmup_message(self, hours_remaining: float):
        """Send warmup status message"""
        embed = {
            'title': '🔄 Trend Radar 2.0 - WARMUP MODE',
            'description': (
                f'Building baseline data before alerting.\n\n'
                f'**Status:** Collecting data silently\n'
                f'**Time remaining:** ~{hours_remaining:.1f} hours\n\n'
                '**Why warmup?**\n'
                '• Need baseline data to detect real spikes\n'
                '• Prevents false positives on first run\n'
                '• Ensures only real trends trigger alerts\n\n'
                '_No alerts until warmup completes._'
            ),
            'color': self.COLORS['warmup'],
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'footer': {
                'text': 'Trend Radar 2.0 | 24-hour warmup period'
            }
        }
        await self.send_discord(embed)
        print(f"[Alert] Sent warmup message ({hours_remaining:.1f}h remaining)")

    async def send_warmup_complete_message(self, total_signals: int, unique_entities: int):
        """Send message when warmup is complete"""
        embed = {
            'title': '✅ Trend Radar 2.0 - WARMUP COMPLETE',
            'description': (
                f'Baseline data collected. Now actively monitoring.\n\n'
                f'**Baseline stats:**\n'
                f'• {total_signals:,} signals collected\n'
                f'• {unique_entities:,} unique entities tracked\n\n'
                '**What happens now:**\n'
                '• Cross-platform trends will trigger alerts\n'
                '• Growth rates calculated against baseline\n'
                '• Max 5 alerts/hour, 10 alerts/day\n\n'
                '_You\'ll only be notified for real viral trends._'
            ),
            'color': 0x2ECC71,  # Green
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'footer': {
                'text': 'Trend Radar 2.0 | Active monitoring enabled'
            }
        }
        await self.send_discord(embed)
        print("[Alert] Sent warmup complete message")
