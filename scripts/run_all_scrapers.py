"""
Run all data scrapers in sequence

Usage:
    python scripts/run_all_scrapers.py
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from helpers.utils import get_logger

logger = get_logger(__name__)


async def run_all():
    """Run all scrapers in dependency order"""
    start_time = datetime.now()

    logger.info("=" * 80)
    logger.info("Starting all data scrapers")
    logger.info("=" * 80)

    scrapers = [
        ("Marketplaces", "scripts.scrapers.sync_marketplaces"),
        ("Crops", "scripts.scrapers.sync_crops"),
        ("Livestock", "scripts.scrapers.sync_livestock"),
        ("Crop Varieties", "scripts.scrapers.sync_crop_varieties"),
        ("Livestock Varieties", "scripts.scrapers.sync_livestock_varieties"),
        ("Crop Prices", "scripts.scrapers.sync_crop_prices"),
        ("Livestock Prices", "scripts.scrapers.sync_livestock_prices"),
    ]

    results = {}

    for name, module_path in scrapers:
        logger.info(f"\n{'=' * 80}")
        logger.info(f"Starting scraper: {name}")
        logger.info(f"{'=' * 80}")
        try:
            # Dynamically import and run the scraper
            module = __import__(module_path, fromlist=['main'])
            await module.main()
            results[name] = "success"
        except Exception as e:
            logger.error(f"Scraper {name} failed: {e}", exc_info=True)
            results[name] = f"failed: {str(e)}"

    duration = (datetime.now() - start_time).total_seconds()

    logger.info(f"\n{'=' * 80}")
    logger.info(f"All scrapers completed in {duration:.2f}s")
    logger.info(f"{'=' * 80}")

    # Print summary
    logger.info("\nSummary:")
    for name, result in results.items():
        status_symbol = "✓" if result == "success" else "✗"
        logger.info(f"  {status_symbol} {name}: {result}")


if __name__ == "__main__":
    asyncio.run(run_all())
