"""
Sync marketplace data from NMIS API to database with English and Amharic names

Usage:
    python scripts/scrapers/sync_marketplaces.py
"""

import asyncio
import sys
import os
from pathlib import Path
import httpx
from typing import List, Dict, Any, Tuple
from sqlalchemy import select

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import async_session_maker
from app.models.market import Marketplace
from helpers.utils import get_logger

logger = get_logger(__name__)

# API URL patterns for both languages and types
API_PATTERNS = {
    "crop": {
        "en": "https://nmis.et/api/web/listMarketPlaces/en/0",
        "am": "https://nmis.et/api/web/listMarketPlaces/am/0"
    },
    "livestock": {
        "en": "https://nmis.et/api/web-livestock/listMarketPlaces/en/0",
        "am": "https://nmis.et/api/web-livestock/listMarketPlaces/am/0"
    }
}


async def fetch_marketplaces_bilingual(market_type: str) -> Tuple[List[Dict], List[Dict]]:
    """Fetch marketplace data in both English and Amharic"""
    urls = API_PATTERNS[market_type]
    
    logger.info(f"Fetching {market_type} marketplace data in English and Amharic...")
    
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # Fetch both languages concurrently
        en_response, am_response = await asyncio.gather(
            client.get(urls["en"]),
            client.get(urls["am"])
        )
        
        en_response.raise_for_status()
        am_response.raise_for_status()
        
        en_data = en_response.json()
        am_data = am_response.json()
    
    logger.info(f"✓ Fetched {len(en_data)} English and {len(am_data)} Amharic {market_type} marketplaces")
    return en_data, am_data


def merge_bilingual_data(en_data: List[Dict], am_data: List[Dict]) -> Dict[int, Dict]:
    """Merge English and Amharic data by marketplace ID"""
    merged = {}
    
    # Create lookup dict from Amharic data
    am_lookup = {item["id"]: item for item in am_data}
    
    # Merge with English data
    for en_item in en_data:
        marketplace_id = en_item["id"]
        am_item = am_lookup.get(marketplace_id, {})
        
        merged[marketplace_id] = {
            "id": marketplace_id,
            "marketName": en_item.get("marketName", ""),
            "marketName_am": am_item.get("marketName", "")
        }
    
    return merged


def parse_marketplace_name(market_name: str) -> Tuple[str, str]:
    """Extract region and name from marketName (format: 'Region - Market Name')"""
    if " - " in market_name:
        parts = market_name.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return None, market_name


async def upsert_marketplace(db, marketplace_data: Dict[str, Any], marketplace_type: str) -> Dict[str, str]:
    """Insert or update marketplace with bilingual names"""
    try:
        marketplace_id = marketplace_data.get("id")
        market_name_en = marketplace_data.get("marketName", "")
        market_name_am = marketplace_data.get("marketName_am", "")

        # Extract region and name from English
        region, name = parse_marketplace_name(market_name_en)

        # Extract region and name from Amharic
        region_am, name_am = parse_marketplace_name(market_name_am)

        # Check if exists
        result = await db.execute(
            select(Marketplace).where(Marketplace.marketplace_id == marketplace_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing marketplace
            existing.name = name
            existing.name_amharic = name_am
            existing.marketplace_type = marketplace_type
            existing.region = region
            existing.region_amharic = region_am
            action = "updated"
        else:
            # Insert new marketplace
            marketplace = Marketplace(
                marketplace_id=marketplace_id,
                name=name,
                name_amharic=name_am,
                marketplace_type=marketplace_type,
                region=region,
                region_amharic=region_am
            )
            db.add(marketplace)
            action = "inserted"

        await db.commit()
        return {"action": action, "marketplace_id": marketplace_id}

    except Exception as e:
        await db.rollback()
        logger.error(f"Error upserting marketplace {marketplace_id}: {e}", exc_info=True)
        raise


async def sync_to_database(marketplaces: Dict[int, Dict], marketplace_type: str):
    """Sync marketplace data to database"""
    async with async_session_maker() as db:
        stats = {"inserted": 0, "updated": 0, "errors": 0}

        logger.info(f"Syncing {len(marketplaces)} marketplaces to database...")
        print("-" * 80)

        for i, (marketplace_id, marketplace_data) in enumerate(marketplaces.items(), 1):
            try:
                result = await upsert_marketplace(db, marketplace_data, marketplace_type)
                action = result.get("action", "unknown")

                if action == "inserted":
                    stats["inserted"] += 1
                elif action == "updated":
                    stats["updated"] += 1

                # Print progress every 10 items
                if i % 10 == 0:
                    print(f"  Progress: {i}/{len(marketplaces)} processed...")

            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error processing marketplace {marketplace_id}: {e}")

        print("-" * 80)
        logger.info(f"✓ Sync complete!")
        logger.info(f"  Inserted: {stats['inserted']}")
        logger.info(f"  Updated:  {stats['updated']}")
        logger.info(f"  Errors:   {stats['errors']}")
        logger.info(f"  Total:    {len(marketplaces)}")


async def main():
    """Main function"""
    try:
        for market_type in ["crop", "livestock"]:
            logger.info(f"\n{'=' * 80}")
            logger.info(f"Processing {market_type.upper()} marketplaces")
            logger.info(f"{'=' * 80}\n")
            
            # Fetch data in both languages
            en_data, am_data = await fetch_marketplaces_bilingual(market_type)

            if not en_data:
                logger.warning(f"No {market_type} marketplace data received from API")
                continue

            # Merge bilingual data
            merged_data = merge_bilingual_data(en_data, am_data)
            
            # Show sample data
            logger.info(f"Sample {market_type} marketplace data:")
            for marketplace_id, mp in list(merged_data.items())[:3]:
                print(f"  - ID {marketplace_id}:")
                print(f"    EN: {mp['marketName']}")
                print(f"    AM: {mp['marketName_am']}")
            print(f"  ... and {len(merged_data) - 3} more\n")

            # Sync to database
            await sync_to_database(merged_data, market_type)

        logger.info(f"\n{'=' * 80}")
        logger.info("All marketplace types synced successfully!")
        logger.info(f"{'=' * 80}")

    except httpx.HTTPError as e:
        logger.error(f"✗ HTTP error fetching data: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"✗ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())