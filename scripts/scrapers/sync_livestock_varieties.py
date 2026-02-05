"""
Sync livestock varieties (breeds) from NMIS API to database

Usage:
    python scripts/scrapers/sync_livestock_varieties.py
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
from app.models.market import Livestock, LivestockBreed, Marketplace
from helpers.utils import get_logger

logger = get_logger(__name__)


async def fetch_marketplace_livestock(marketplace_id: int):
    """Fetch livestock data including varieties for a specific marketplace in both English and Amharic"""
    url_en = f"https://nmis.et/api/web-livestock/getCurrentMarketData/{marketplace_id}/en"
    url_am = f"https://nmis.et/api/web-livestock/getCurrentMarketData/{marketplace_id}/am"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            # Fetch both languages
            response_en = await client.get(url_en)
            response_am = await client.get(url_am)

            en_data = response_en.json() if response_en.status_code == 200 else []
            am_data = response_am.json() if response_am.status_code == 200 else []

            # Create lookup by ID from Amharic data
            am_lookup = {item["livestockId"]: item for item in am_data if "livestockId" in item}

            merged_data = []
            for en_item in en_data:
                livestock_id = en_item.get("livestockId")
                variety_name = en_item.get("varietyName", "").strip()

                if not variety_name or not livestock_id:
                    continue

                # Match by ID
                am_item = am_lookup.get(livestock_id, {})
                merged_data.append({
                    "livestockId": livestock_id,
                    "varietyName": variety_name,
                    "varietyName_am": am_item.get("varietyName", "")
                })

            return merged_data
        except Exception:
            return []


async def upsert_variety(db, variety_data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update livestock variety (breed)"""
    try:
        nmis_livestock_id = variety_data.get("livestockId")
        variety_name = variety_data.get("varietyName", "").strip()
        variety_name_am = variety_data.get("varietyName_am", "").strip()

        if not variety_name or not nmis_livestock_id:
            raise ValueError("Both livestock ID and variety name are required")

        # Find the parent livestock by nmis_livestock_id
        livestock_result = await db.execute(
            select(Livestock).where(Livestock.nmis_livestock_id == nmis_livestock_id)
        )
        livestock = livestock_result.scalar_one_or_none()

        if not livestock:
            raise ValueError(f"Livestock with nmis_livestock_id {nmis_livestock_id} not found")

        livestock_id = livestock.livestock_id

        # Check if variety exists by (livestock_id, name)
        breed_result = await db.execute(
            select(LivestockBreed).where(
                and_(
                    LivestockBreed.livestock_id == livestock_id,
                    LivestockBreed.name == variety_name
                )
            )
        )
        existing = breed_result.scalar_one_or_none()

        if existing:
            # Update existing variety
            if variety_name_am:
                existing.name_amharic = variety_name_am
            if nmis_livestock_id:
                existing.nmis_breed_id = nmis_livestock_id
            action = "updated"
            variety_id = existing.breed_id
        else:
            # Insert new variety
            variety = LivestockBreed(
                livestock_id=livestock_id,
                nmis_breed_id=nmis_livestock_id,
                name=variety_name,
                name_amharic=variety_name_am if variety_name_am else None
            )
            db.add(variety)
            await db.flush()
            action = "inserted"
            variety_id = variety.breed_id

        await db.flush()  # Use flush instead of commit - commit will be called by caller
        return {
            "action": action,
            "variety_id": variety_id,
            "variety_name": variety_name,
            "livestock_name": livestock.name
        }

    except Exception as e:
        logger.error(f"Error processing livestock variety : {str(e)}")
        return {"action": "error", "variety_name": None, "error": str(e)}


async def sync_varieties():
    """Main sync function"""

    async with async_session_maker() as db:
        try:
            logger.info("Starting livestock varieties sync from NMIS API...")
            print("=" * 80)

            # Get all marketplaces
            result = await db.execute(select(Marketplace).where(Marketplace.marketplace_type == "livestock"))
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
                    # Extract marketplace info early to avoid lazy loading issues
                    marketplace_id = marketplace.marketplace_id
                    marketplace_name = marketplace.name
                    
                    # Fetch livestock with varieties for this marketplace
                    livestock_data_list = await fetch_marketplace_livestock(marketplace_id)

                    if livestock_data_list:
                        print(f"\n[{i}/{len(marketplaces)}] {marketplace_name}")
                        print(f"  Found {len(livestock_data_list)} livestock items")

                        for livestock_data in livestock_data_list:
                            nmis_livestock_id = livestock_data.get("livestockId")
                            variety_name = livestock_data.get("varietyName")

                            if not variety_name or not nmis_livestock_id:
                                continue

                            # Create unique key (livestockId, varietyName)
                            variety_key = (nmis_livestock_id, variety_name)

                            # Skip if already processed
                            if variety_key in varieties_seen:
                                continue

                            varieties_seen.add(variety_key)

                            try:
                                result = await upsert_variety(db, livestock_data)

                                if result["action"] == "inserted":
                                    stats["varieties_inserted"] += 1
                                    print(f"    ✓ Inserted: {result['livestock_name']} - {result['variety_name']}")
                                else:
                                    stats["varieties_updated"] += 1

                            except Exception as e:
                                stats["errors"] += 1
                                logger.error(f"Error processing variety {variety_name}: {e}")

                        # Commit all changes after processing all items for this marketplace
                        await db.commit()

                    stats["marketplaces_processed"] += 1

                except Exception as e:
                    logger.error(f"Error for marketplace {marketplace_name if 'marketplace_name' in locals() else 'unknown'}: {e}")

            print("\n" + "=" * 80)
            logger.info("✓ Livestock varieties sync complete!")
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