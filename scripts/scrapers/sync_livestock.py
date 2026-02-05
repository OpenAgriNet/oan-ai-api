"""
Sync livestock types from NMIS API to database

Syncs livestock types to the dedicated livestock table (NOT crop table)

Usage:
    python scripts/scrapers/sync_livestock.py
"""

import asyncio
import sys
import os
from pathlib import Path
import httpx
from typing import List, Dict, Any
from sqlalchemy import select

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import async_session_maker
from app.models.market import Livestock, Marketplace
from helpers.utils import get_logger

logger = get_logger(__name__)


async def fetch_marketplace_livestock(marketplace_id: int):
    """Fetch livestock data for a specific marketplace in both English and Amharic"""
    url_en = f"https://nmis.et/api/web-livestock/getMarketCrop/{marketplace_id}/en"
    url_am = f"https://nmis.et/api/web-livestock/getMarketCrop/{marketplace_id}/am"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            # Fetch both languages
            response_en = await client.get(url_en)
            response_am = await client.get(url_am)

            en_data = response_en.json() if response_en.status_code == 200 else []
            am_data = response_am.json() if response_am.status_code == 200 else []

            # Create lookup by ID from Amharic data
            am_lookup = {item["id"]: item for item in am_data if "id" in item}

            merged_data = []
            for en_item in en_data:
                livestock_id = en_item.get("id")
                livestock_name = en_item.get("cropName", "")

                # Match by ID
                am_item = am_lookup.get(livestock_id, {})

                merged_data.append({
                    "id": livestock_id,
                    "cropName": livestock_name,
                    "cropName_am": am_item.get("cropName", "")
                })

            return merged_data
        except Exception:
            return []


async def upsert_livestock(db, livestock_data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update livestock"""
    try:
        livestock_name = livestock_data.get("cropName", "")
        livestock_name_am = livestock_data.get("cropName_am", "")
        nmis_livestock_id = livestock_data.get("id")
        if not livestock_name:
            raise ValueError("cropName (livestock name) is required")

        # Find by NMIS ID first, then by name
        existing = None
        if nmis_livestock_id:
            result = await db.execute(
                select(Livestock).where(Livestock.nmis_livestock_id == nmis_livestock_id)
            )
            existing = result.scalar_one_or_none()

        if not existing:
            result = await db.execute(
                select(Livestock).where(Livestock.name == livestock_name)
            )
            existing = result.scalar_one_or_none()

        if existing:
            # Update existing livestock
            existing.nmis_livestock_id = nmis_livestock_id
            existing.name_amharic = livestock_name_am
            action = "updated"
            livestock_id = existing.livestock_id
        else:
            # Insert new livestock
            livestock = Livestock(
                nmis_livestock_id=nmis_livestock_id,
                name=livestock_name,
                name_amharic=livestock_name_am,
                unit="Head"
            )
            db.add(livestock)
            await db.flush()
            action = "inserted"
            livestock_id = livestock.livestock_id

        await db.commit()
        return {"action": action, "livestock_id": livestock_id, "livestock_name": livestock_name}

    except Exception as e:
        await db.rollback()
        raise


async def sync_livestock():
    """Main sync function"""

    async with async_session_maker() as db:
        try:
            logger.info("Starting livestock sync from NMIS API...")
            print("=" * 80)

            # Get all marketplaces
            result = await db.execute(select(Marketplace).where(Marketplace.marketplace_type == "livestock"))
            marketplaces = result.scalars().all()

            logger.info(f"Found {len(marketplaces)} marketplaces")

            stats = {
                "marketplaces_processed": 0,
                "livestock_inserted": 0,
                "livestock_updated": 0,
                "errors": 0
            }

            livestock_seen = set()

            for i, marketplace in enumerate(marketplaces, 1):
                try:
                    # Fetch livestock for this marketplace
                    livestock_data_list = await fetch_marketplace_livestock(marketplace.marketplace_id)

                    if livestock_data_list:
                        print(f"\n[{i}/{len(marketplaces)}] {marketplace.name}")
                        print(f"  Found {len(livestock_data_list)} items")

                        for livestock_data in livestock_data_list:
                            livestock_name = livestock_data.get("cropName")

                            # Skip if already processed
                            if livestock_name in livestock_seen:
                                continue

                            livestock_seen.add(livestock_name)

                            try:
                                result = await upsert_livestock(db, livestock_data)

                                if result["action"] == "inserted":
                                    stats["livestock_inserted"] += 1
                                    print(f"    ✓ Inserted: {result['livestock_name']}")
                                else:
                                    stats["livestock_updated"] += 1

                            except Exception as e:
                                stats["errors"] += 1
                                logger.error(f"Error processing livestock {livestock_name}: {e}")

                    stats["marketplaces_processed"] += 1

                except Exception as e:
                    logger.error(f"Error for marketplace {marketplace.name}: {e}")

            print("\n" + "=" * 80)
            logger.info("✓ Livestock sync complete!")
            logger.info(f"  Marketplaces processed: {stats['marketplaces_processed']}")
            logger.info(f"  Livestock inserted:     {stats['livestock_inserted']}")
            logger.info(f"  Livestock updated:      {stats['livestock_updated']}")
            logger.info(f"  Errors:                 {stats['errors']}")

        except Exception as e:
            logger.error(f"✗ Fatal error: {e}", exc_info=True)
            raise


async def main():
    """Main function"""
    try:
        await sync_livestock()
    except Exception as e:
        logger.error(f"✗ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
