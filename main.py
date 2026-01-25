"""
Trend Radar 2.0 - Main Orchestrator
Multi-platform early trend detection system
With 24-hour warmup period for baseline collection
"""

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import asyncpg

# Load environment variables
load_dotenv()

# Import our modules
from collectors import HackerNewsCollector, GitHubCollector, YouTubeCollector, GoogleTrendsCollector
from analysis import VelocityAnalyzer
from alerts import AlertManager


class TrendRadar:
    WARMUP_HOURS = 24  # 24 hours to collect baseline data

    def __init__(self):
        self.db_pool = None
        self.database_url = os.getenv('DATABASE_URL')
        self.discord_webhook = os.getenv('DISCORD_WEBHOOK_URL')
        self.analyzer = None

        if not self.database_url:
            raise ValueError("DATABASE_URL not set in environment")
        if not self.discord_webhook:
            raise ValueError("DISCORD_WEBHOOK_URL not set in environment")

    async def init_database(self):
        """Initialize database connection pool"""
        print("[Main] Connecting to database...")
        self.db_pool = await asyncpg.create_pool(
            self.database_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        print("[Main] Database connection established")

    async def setup_schema(self):
        """Create database tables if they don't exist"""
        print("[Main] Setting up database schema...")
        schema_path = os.path.join(os.path.dirname(__file__), 'database', 'schema.sql')

        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        async with self.db_pool.acquire() as conn:
            await conn.execute(schema_sql)

        print("[Main] Database schema ready")

    async def get_warmup_status(self) -> tuple[bool, float, int, int]:
        """
        Check warmup status from database.
        Returns (is_complete, hours_remaining, total_signals, unique_entities)
        """
        async with self.db_pool.acquire() as conn:
            # Check if warmup is complete
            complete = await conn.fetchval('''
                SELECT value FROM system_state WHERE key = 'warmup_complete'
            ''')

            if complete == 'true':
                return True, 0, 0, 0

            # Get warmup start time
            started = await conn.fetchval('''
                SELECT value FROM system_state WHERE key = 'warmup_started'
            ''')

            now = datetime.now(timezone.utc)

            if not started:
                # First run - set warmup start
                await conn.execute('''
                    UPDATE system_state SET value = $1, updated_at = NOW()
                    WHERE key = 'warmup_started'
                ''', now.isoformat())
                hours_remaining = self.WARMUP_HOURS
            else:
                try:
                    start_time = datetime.fromisoformat(started.replace('Z', '+00:00'))
                    elapsed = (now - start_time).total_seconds() / 3600
                    hours_remaining = max(0, self.WARMUP_HOURS - elapsed)

                    if hours_remaining <= 0:
                        # Warmup complete!
                        await conn.execute('''
                            UPDATE system_state SET value = 'true', updated_at = NOW()
                            WHERE key = 'warmup_complete'
                        ''')
                        return True, 0, 0, 0
                except:
                    hours_remaining = self.WARMUP_HOURS

            # Get collection stats
            total_signals = await conn.fetchval('SELECT COUNT(*) FROM signals') or 0
            unique_entities = await conn.fetchval('''
                SELECT COUNT(DISTINCT entity_normalized) FROM signals
                WHERE entity_normalized IS NOT NULL
            ''') or 0

            return False, hours_remaining, total_signals, unique_entities

    async def run_hn_collection(self):
        """Run Hacker News collection"""
        try:
            async with HackerNewsCollector(self.db_pool) as collector:
                count = await collector.collect()
                return count
        except Exception as e:
            print(f"[Main] HN collection error: {e}")
            return 0

    async def run_github_collection(self):
        """Run GitHub collection"""
        try:
            async with GitHubCollector(self.db_pool) as collector:
                count = await collector.collect()
                return count
        except Exception as e:
            print(f"[Main] GitHub collection error: {e}")
            return 0

    async def run_youtube_collection(self):
        """Run YouTube collection"""
        try:
            async with YouTubeCollector(self.db_pool) as collector:
                count = await collector.collect()
                return count
        except Exception as e:
            print(f"[Main] YouTube collection error: {e}")
            return 0

    async def run_google_trends_collection(self):
        """Run Google Trends collection"""
        try:
            async with GoogleTrendsCollector(self.db_pool) as collector:
                count = await collector.collect()
                return count
        except Exception as e:
            print(f"[Main] Google Trends collection error: {e}")
            return 0

    async def run_analysis(self) -> tuple[list, list]:
        """Run velocity analysis"""
        try:
            if not self.analyzer:
                self.analyzer = VelocityAnalyzer(self.db_pool)
            metrics = await self.analyzer.analyze()
            anomalies = await self.analyzer.detect_anomalies()
            return metrics, anomalies
        except Exception as e:
            print(f"[Main] Analysis error: {e}")
            import traceback
            traceback.print_exc()
            return [], []

    async def run_alerts(self, metrics: list, anomalies: list):
        """Check and send alerts (only if warmup complete)"""
        warmup_done, _, _, _ = await self.get_warmup_status()

        if not warmup_done:
            return

        try:
            async with AlertManager(self.db_pool, self.discord_webhook) as alert_mgr:
                if not self.analyzer:
                    self.analyzer = VelocityAnalyzer(self.db_pool)
                await alert_mgr.check_and_alert(metrics, anomalies, self.analyzer)
        except Exception as e:
            print(f"[Main] Alert error: {e}")
            import traceback
            traceback.print_exc()

    async def collection_loop(self, name: str, interval_minutes: int, collect_func):
        """Generic collection loop"""
        while True:
            try:
                print(f"\n[{name}] Starting collection cycle...")
                count = await collect_func()
                print(f"[{name}] Collected {count} signals")
            except Exception as e:
                print(f"[{name}] Error in collection loop: {e}")

            await asyncio.sleep(interval_minutes * 60)

    async def analysis_loop(self, interval_minutes: int = 15):
        """Analysis and alerting loop"""
        while True:
            try:
                warmup_done, hours_remaining, total_signals, unique_entities = await self.get_warmup_status()

                print("\n" + "=" * 60)
                if not warmup_done:
                    print(f"[WARMUP MODE] {hours_remaining:.1f} hours remaining")
                    print(f"[WARMUP MODE] Collected {total_signals} signals for {unique_entities} entities")
                    print(f"[WARMUP MODE] NO ALERTS - Building baseline data...")
                    print("=" * 60)
                else:
                    print("[ACTIVE MODE] Warmup complete - Alerts enabled")
                    print("=" * 60)

                print("\n[Analysis] Starting analysis cycle...")
                metrics, anomalies = await self.run_analysis()

                if warmup_done and metrics:
                    await self.run_alerts(metrics, anomalies)
                elif not warmup_done:
                    # Log what would be alerted (for debugging)
                    if metrics:
                        qualifying = [m for m in metrics if m['signals_24h'] >= 15 and m['platform_count'] >= 2]
                        if qualifying:
                            print(f"[WARMUP MODE] {len(qualifying)} entities would qualify for alerts:")
                            for m in qualifying[:5]:
                                print(f"  - {m['entity_display']}: {m['signals_24h']} signals, "
                                      f"{m['platform_count']} platforms, score: {m['trend_score']:.0f}")

            except Exception as e:
                print(f"[Analysis] Error in analysis loop: {e}")
                import traceback
                traceback.print_exc()

            await asyncio.sleep(interval_minutes * 60)

    async def run(self):
        """Main run loop"""
        print("=" * 60)
        print("  Trend Radar 2.0 - Early Trend Detection System")
        print("  STRICT MODE: Cross-platform validation required")
        print("=" * 60)
        print()

        # Initialize
        await self.init_database()
        await self.setup_schema()

        # Initialize analyzer
        self.analyzer = VelocityAnalyzer(self.db_pool)

        # Check warmup status
        warmup_done, hours_remaining, total_signals, unique_entities = await self.get_warmup_status()

        # Send appropriate startup notification
        async with AlertManager(self.db_pool, self.discord_webhook) as alert_mgr:
            if warmup_done:
                await alert_mgr.send_startup_message()
            else:
                await alert_mgr.send_warmup_message(hours_remaining)

        print()
        if not warmup_done:
            print("=" * 60)
            print(f"  WARMUP MODE: {hours_remaining:.1f} hours remaining")
            print(f"  Signals collected: {total_signals}")
            print(f"  Unique entities: {unique_entities}")
            print("  NO ALERTS will be sent during warmup")
            print("=" * 60)
        else:
            print("=" * 60)
            print("  ACTIVE MODE: Warmup complete")
            print("  Alerts ENABLED for real trends only")
            print("=" * 60)
        print()

        # Do initial collection
        print("[Main] Running initial data collection...")
        hn_count = await self.run_hn_collection()
        gh_count = await self.run_github_collection()
        yt_count = await self.run_youtube_collection()
        gt_count = await self.run_google_trends_collection()
        print(f"[Main] Initial collection: HN={hn_count}, GitHub={gh_count}, YouTube={yt_count}, GoogleTrends={gt_count}")

        # Run initial analysis
        print("\n[Main] Running initial analysis...")
        metrics, anomalies = await self.run_analysis()

        # Only alert if warmup is done
        warmup_done, _, _, _ = await self.get_warmup_status()
        if warmup_done and metrics:
            await self.run_alerts(metrics, anomalies)

        # Start concurrent loops
        print("\n[Main] Starting scheduled collection loops...")
        print("  - Hacker News: every 10 minutes")
        print("  - GitHub: every 30 minutes")
        print("  - YouTube: every 30 minutes")
        print("  - Google Trends: every 60 minutes")
        print("  - Analysis: every 15 minutes")
        print()

        await asyncio.gather(
            self.collection_loop("HN", 10, self.run_hn_collection),
            self.collection_loop("GitHub", 30, self.run_github_collection),
            self.collection_loop("YouTube", 30, self.run_youtube_collection),
            self.collection_loop("GoogleTrends", 60, self.run_google_trends_collection),
            self.analysis_loop(15),
        )

    async def cleanup(self):
        """Cleanup resources"""
        if self.db_pool:
            await self.db_pool.close()
            print("[Main] Database connection closed")


async def main():
    radar = TrendRadar()
    try:
        await radar.run()
    except KeyboardInterrupt:
        print("\n[Main] Shutting down...")
    finally:
        await radar.cleanup()


if __name__ == "__main__":
    # Windows event loop policy fix
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
