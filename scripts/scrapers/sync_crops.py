"""
Sync agricultural crop data from NMIS API to database

Fetches crops with category='agricultural' (NOT livestock)

Usage:
    python scripts/scrapers/sync_crops.py
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
from app.models.market import Crop, Marketplace
from helpers.utils import get_logger

logger = get_logger(__name__)


async def fetch_marketplace_crops(marketplace_id: int):
    """Fetch crop data for a specific marketplace in both English and Amharic"""
    url_en = f"https://nmis.et/api/web/getMarketCrop/{marketplace_id}/en"
    url_am = f"https://nmis.et/api/web/getMarketCrop/{marketplace_id}/am"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            # Fetch both languages
            response_en = await client.get(url_en)
            response_am = await client.get(url_am)

            en_data = response_en.json() if response_en.status_code == 200 else []
            am_data = response_am.json() if response_am.status_code == 200 else []

            # Merge bilingual data by crop ID
            am_lookup = {item["id"]: item for item in am_data}

            merged_data = []
            for en_item in en_data:
                crop_id = en_item["id"]
                am_item = am_lookup.get(crop_id, {})

                merged_data.append({
                    "id": crop_id,
                    "cropName": en_item.get("cropName", ""),
                    "cropName_am": am_item.get("cropName", "")
                })

            return merged_data
        except Exception:
            return []


async def upsert_crop(db, crop_data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update crop (agricultural only)"""
    try:
        nmis_crop_id = crop_data.get("id")
        crop_name = crop_data.get("cropName", "")
        crop_name_am = crop_data.get("cropName_am", "")

        if not crop_name:
            raise ValueError("cropName is required")

        # Find by NMIS crop ID first
        result = await db.execute(
            select(Crop).where(Crop.nmis_crop_id == nmis_crop_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing crop
            existing.name = crop_name
            existing.name_amharic = crop_name_am
            existing.category = "agricultural"
            action = "updated"
            crop_id = existing.crop_id
        else:
            # Insert new crop
            crop = Crop(
                nmis_crop_id=nmis_crop_id,
                name=crop_name,
                name_amharic=crop_name_am,
                category="agricultural"
            )
            db.add(crop)
            await db.flush()
            action = "inserted"
            crop_id = crop.crop_id

        await db.commit()
        return {"action": action, "crop_id": crop_id, "crop_name": crop_name}

    except Exception as e:
        await db.rollback()
        raise


async def sync_crops():
    """Main sync function"""

    async with async_session_maker() as db:
        try:
            logger.info("Starting crop sync from NMIS API...")
            print("=" * 80)

            # Get all marketplaces
            result = await db.execute(select(Marketplace).where(Marketplace.marketplace_type == "crop"))
            marketplaces = result.scalars().all()

            logger.info(f"Found {len(marketplaces)} marketplaces")

            stats = {
                "marketplaces_processed": 0,
                "crops_inserted": 0,
                "crops_updated": 0,
                "errors": 0
            }

            crops_seen = set()

            for i, marketplace in enumerate(marketplaces, 1):
                try:
                    # Fetch crops for this marketplace
                    crop_data_list = await fetch_marketplace_crops(marketplace.marketplace_id)

                    if crop_data_list:
                        print(f"\n[{i}/{len(marketplaces)}] {marketplace.name}")
                        print(f"  Found {len(crop_data_list)} items")

                        for crop_data in crop_data_list:
                            crop_name = crop_data.get("cropName")

                            # Skip if already processed
                            if crop_name in crops_seen:
                                continue

                            crops_seen.add(crop_name)

                            try:
                                result = await upsert_crop(db, crop_data)

                                if result["action"] == "inserted":
                                    stats["crops_inserted"] += 1
                                    print(f"    ✓ Inserted: {result['crop_name']}")
                                else:
                                    stats["crops_updated"] += 1

                            except Exception as e:
                                stats["errors"] += 1
                                logger.error(f"Error processing crop {crop_name}: {e}")

                    stats["marketplaces_processed"] += 1

                except Exception as e:
                    logger.error(f"Error for marketplace {marketplace.name}: {e}")

            print("\n" + "=" * 80)
            logger.info("✓ Crop sync complete!")
            logger.info(f"  Marketplaces processed: {stats['marketplaces_processed']}")
            logger.info(f"  Crops inserted:         {stats['crops_inserted']}")
            logger.info(f"  Crops updated:          {stats['crops_updated']}")
            logger.info(f"  Errors:                 {stats['errors']}")

        except Exception as e:
            logger.error(f"✗ Fatal error: {e}", exc_info=True)
            raise


async def main():
    """Main function"""
    try:
        await sync_crops()
    except Exception as e:
        logger.error(f"✗ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
