"""
Run all data scrapers in sequence

Usage:
    python scripts/run_all_scrapers.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete
from app.database import async_session_maker
from app.models.market import MarketPrice, ScraperLog
from helpers.utils import get_logger

logger = get_logger(__name__)


async def clear_prices():
    """Delete all prices before fresh sync"""
    async with async_session_maker() as db:
        await db.execute(delete(MarketPrice))
        await db.commit()
        logger.info("Cleared market_prices table")


async def log_scraper(scraper_type: str, status: str, started_at: datetime, stats: dict = None, error: str = None):
    """Log scraper run to database"""
    async with async_session_maker() as db:
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        log = ScraperLog(
            scraper_type=scraper_type,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            records_fetched=stats.get("fetched", 0) if stats else 0,
            records_inserted=stats.get("inserted", 0) if stats else 0,
            records_updated=stats.get("updated", 0) if stats else 0,
            records_failed=stats.get("errors", 0) if stats else 0,
            error_message=error,
            meta_data=stats or {}
        )
        db.add(log)
        await db.commit()


async def run_all():
    """Run all scrapers in dependency order"""
    start_time = datetime.now(timezone.utc)

    logger.info("=" * 60)
    logger.info("Starting all data scrapers")
    logger.info("=" * 60)

    # NOTE: Removed clear_prices() call - individual scrapers do safe upserts
    # Wiping the table on every startup caused queries to fail during the ~10min sync window

    scrapers = [
        ("marketplaces", "scripts.scrapers.sync_marketplaces"),
        ("crops", "scripts.scrapers.sync_crops"),
        ("livestock", "scripts.scrapers.sync_livestock"),
        ("crop_varieties", "scripts.scrapers.sync_crop_varieties"),
        ("livestock_varieties", "scripts.scrapers.sync_livestock_varieties"),
        ("crop_prices", "scripts.scrapers.sync_crop_prices"),
        ("livestock_prices", "scripts.scrapers.sync_livestock_prices"),
        ("crop_prices_collected_at", "scripts.scrapers.sync_crop_prices_table"),
        ("livestock_prices_collected_at", "scripts.scrapers.sync_livestock_prices_table"),
    ]

    results = {}

    for name, module_path in scrapers:
        scraper_start = datetime.now(timezone.utc)
        logger.info(f"\n[{name}] Starting...")

        try:
            module = __import__(module_path, fromlist=['main'])
            await module.main()
            results[name] = "success"
            await log_scraper(name, "success", scraper_start)
        except Exception as e:
            logger.error(f"[{name}] Failed: {e}")
            results[name] = "failed"
            await log_scraper(name, "failed", scraper_start, error=str(e))

    duration = (datetime.now(timezone.utc) - start_time).total_seconds()

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Completed in {duration:.2f}s")
    for name, result in results.items():
        logger.info(f"  {'✓' if result == 'success' else '✗'} {name}")


if __name__ == "__main__":
    asyncio.run(run_all())
