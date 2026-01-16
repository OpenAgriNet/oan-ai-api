"""
Sync crop varieties from NMIS API to database

Usage:
    python scripts/scrapers/sync_crop_varieties.py
"""

import asyncio
import sys
import os
from pathlib import Path
import httpx
from typing import Dict, Any
from sqlalchemy import select, and_

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import async_session_maker
from app.models.market import Crop, CropVariety, Marketplace
from helpers.utils import get_logger

logger = get_logger(__name__)


async def fetch_marketplace_crops(marketplace_id: int):
    """Fetch crop data including varieties for a specific marketplace in both English and Amharic"""
    url_en = f"http://nmis.et/api/web/getCurrentMarketData/{marketplace_id}/en"
    url_am = f"http://nmis.et/api/web/getCurrentMarketData/{marketplace_id}/am"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Fetch both languages
            response_en = await client.get(url_en)
            response_am = await client.get(url_am)

            en_data = response_en.json() if response_en.status_code == 200 else []
            am_data = response_am.json() if response_am.status_code == 200 else []

            # Match by index since API returns items in same order
            merged_data = []
            for idx, en_item in enumerate(en_data):
                crop_name_en = en_item.get("cName", "").strip()
                variety_name_en = en_item.get("varietyName", "").strip()

                if not variety_name_en or not crop_name_en:
                    continue

                # Get corresponding Amharic item by index
                am_item = am_data[idx] if idx < len(am_data) else {}
                crop_name_am = am_item.get("cName", "").strip()
                variety_name_am = am_item.get("varietyName", "").strip()

                merged_data.append({
                    "cName": crop_name_en,
                    "cName_am": crop_name_am,
                    "varietyName": variety_name_en,
                    "varietyName_am": variety_name_am
                })

            return merged_data
        except Exception:
            return []


async def upsert_variety(db, variety_data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update crop variety"""
    try:
        crop_name_en = variety_data.get("cName", "").strip()
        crop_name_am = variety_data.get("cName_am", "").strip()
        variety_name = variety_data.get("varietyName", "").strip()
        variety_name_am = variety_data.get("varietyName_am", "").strip()

        if not variety_name or not crop_name_en:
            raise ValueError("Both crop name and variety name are required")

        # Find crop by English name
        crop_en_result = await db.execute(
            select(Crop).where(Crop.name == crop_name_en)
        )
        crop_en = crop_en_result.scalar_one_or_none()

        if not crop_en:
            raise ValueError(f"Crop '{crop_name_en}' not found")

        # Find crop by Amharic name if available
        crop_am = None
        if crop_name_am:
            crop_am_result = await db.execute(
                select(Crop).where(Crop.name_amharic == crop_name_am)
            )
            crop_am = crop_am_result.scalar_one_or_none()

        # Verify both searches return the same crop
        if crop_am and crop_en.crop_id != crop_am.crop_id:
            raise ValueError(f"Crop mismatch: English '{crop_name_en}' (id={crop_en.crop_id}) != Amharic '{crop_name_am}' (id={crop_am.crop_id})")

        crop_id = crop_en.crop_id

        # Check if variety exists by (crop_id, name)
        variety_result = await db.execute(
            select(CropVariety).where(
                and_(
                    CropVariety.crop_id == crop_id,
                    CropVariety.name == variety_name
                )
            )
        )
        existing = variety_result.scalar_one_or_none()

        if existing:
            # Update existing variety
            if variety_name_am:
                existing.name_amharic = variety_name_am
            action = "updated"
            variety_id = existing.variety_id
        else:
            # Insert new variety
            variety = CropVariety(
                crop_id=crop_id,
                name=variety_name,
                name_amharic=variety_name_am if variety_name_am else None
            )
            db.add(variety)
            await db.flush()
            action = "inserted"
            variety_id = variety.variety_id

        await db.commit()
        return {
            "action": action,
            "variety_id": variety_id,
            "variety_name": variety_name,
            "crop_name": crop_en.name
        }

    except Exception as e:
        await db.rollback()
        raise


async def sync_varieties():
    """Main sync function"""

    async with async_session_maker() as db:
        try:
            logger.info("Starting crop varieties sync from NMIS API...")
            print("=" * 80)

            # Get all marketplaces
            result = await db.execute(select(Marketplace).where(Marketplace.marketplace_type == "crop"))
            marketplaces = result.scalars().all()

            logger.info(f"Found {len(marketplaces)} marketplaces")

            stats = {
                "marketplaces_processed": 0,
                "varieties_inserted": 0,
                "varieties_updated": 0,
                "errors": 0
            }

            varieties_seen = set()

            for i, marketplace in enumerate(marketplaces, 1):
                try:
                    # Fetch crops with varieties for this marketplace
                    crop_data_list = await fetch_marketplace_crops(marketplace.marketplace_id)

                    if crop_data_list:
                        print(f"\n[{i}/{len(marketplaces)}] {marketplace.name}")
                        print(f"  Found {len(crop_data_list)} crop items")

                        for crop_data in crop_data_list:
                            crop_name = crop_data.get("cName")
                            variety_name = crop_data.get("varietyName")

                            if not variety_name or not crop_name:
                                continue

                            # Create unique key (cName, varietyName)
                            variety_key = (crop_name, variety_name)

                            # Skip if already processed
                            if variety_key in varieties_seen:
                                continue

                            varieties_seen.add(variety_key)

                            try:
                                result = await upsert_variety(db, crop_data)

                                if result["action"] == "inserted":
                                    stats["varieties_inserted"] += 1
                                    print(f"    ✓ Inserted: {result['crop_name']} - {result['variety_name']}")
                                else:
                                    stats["varieties_updated"] += 1

                            except Exception as e:
                                stats["errors"] += 1
                                logger.error(f"Error processing variety {variety_name}: {e}")

                    stats["marketplaces_processed"] += 1

                except Exception as e:
                    logger.error(f"Error for marketplace {marketplace.name}: {e}")

            print("\n" + "=" * 80)
            logger.info("✓ Crop varieties sync complete!")
            logger.info(f"  Marketplaces processed:  {stats['marketplaces_processed']}")
            logger.info(f"  Varieties inserted:      {stats['varieties_inserted']}")
            logger.info(f"  Varieties updated:       {stats['varieties_updated']}")
            logger.info(f"  Errors:                  {stats['errors']}")

        except Exception as e:
            logger.error(f"✗ Fatal error: {e}", exc_info=True)
            raise


async def main():
    """Main function"""
    try:
        await sync_varieties()
    except Exception as e:
        logger.error(f"✗ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
