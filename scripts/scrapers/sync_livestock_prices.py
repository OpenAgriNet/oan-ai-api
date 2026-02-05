"""
Sync livestock market prices from NMIS API to database

This script:
1. Gets all livestock marketplaces from database (marketplace_type='livestock')
2. For each marketplace, fetches current livestock price data from NMIS API
3. Inserts or updates prices in the market_prices table using livestock_id/breed_id

Usage:
    python scripts/scrapers/sync_livestock_prices.py
"""

import asyncio
import sys
import os
from pathlib import Path
from typing import Dict, Any
import httpx
from datetime import date, datetime, timezone
from sqlalchemy import select, and_
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import async_session_maker
from app.models.market import Livestock, LivestockBreed, MarketPrice, Marketplace
from helpers.utils import get_logger

logger = get_logger(__name__)


async def fetch_livestock_prices(marketplace_id: int):
    """Fetch current livestock prices for a specific marketplace"""
    url = f"https://nmis.et/api/web-livestock/getCurrentMarketData/{marketplace_id}/en"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()
            else:
                return []
        except Exception:
            return []


async def upsert_livestock_price(db, marketplace_id: int, price_data_list: list) -> Dict[str, Any]:
    """Insert or update livestock price in market_prices table (aggregates multiple variations)"""
    # Group by (livestock_name, breed_name) - these should all be the same
    first_item = price_data_list[0]
    livestock_name = first_item.get("cName", "").strip()  # Strip whitespace!
    breed_name = first_item.get("varietyName", "").strip() if first_item.get("varietyName") else None

    if not livestock_name:
        raise ValueError("cName (livestock name) is required")

    # Find livestock by name - use case-insensitive matching
    livestock_result = await db.execute(
        select(Livestock).where(Livestock.name.ilike(livestock_name))
    )
    livestock = livestock_result.scalar_one_or_none()

    if not livestock:
        raise ValueError(f"Livestock '{livestock_name}' not found in database")

    livestock_id = livestock.livestock_id

    # Handle breed if present
    breed_id = None
    if breed_name:
        breed_result = await db.execute(
            select(LivestockBreed).where(
                and_(
                    LivestockBreed.livestock_id == livestock_id,
                    LivestockBreed.name == breed_name
                )
            )
        )
        breed = breed_result.scalar_one_or_none()
        if breed:
            breed_id = breed.breed_id
    # Aggregate prices from all variations
    all_mins = []
    all_maxs = []
    variations = []

    for item in price_data_list:
        # Convert to float to handle both string and numeric values
        pmin = float(item.get("pmin", 0) or 0)
        pmax = float(item.get("pmax", 0) or 0)

        if pmin > 0:
            all_mins.append(pmin)
        if pmax > 0:
            all_maxs.append(pmax)

        # Store full variation details
        variations.append({
            "grade": item.get("grade"),
            "productionType": item.get("productionType"),
            "location": item.get("location"),
            "gender": item.get("gender"),
            "age": item.get("age"),
            "pmin": pmin if pmin > 0 else None,
            "pmax": pmax if pmax > 0 else None,
            "volume": item.get("volume")
        })

    # Calculate aggregated prices
    if all_mins or all_maxs:
        min_price = min(all_mins) if all_mins else (min(all_maxs) if all_maxs else None)
        max_price = max(all_maxs) if all_maxs else (max(all_mins) if all_mins else None)

        # Average of all individual prices
        all_prices = all_mins + all_maxs
        avg_price = sum(all_prices) / len(all_prices) if all_prices else None
    else:
        min_price = None
        max_price = None
        avg_price = None

    # Use today's date as price date
    price_date = date.today()

    # Check if price exists
    result = await db.execute(
        select(MarketPrice).where(
            and_(
                MarketPrice.marketplace_id == marketplace_id,
                MarketPrice.livestock_id == livestock_id,
                MarketPrice.breed_id == breed_id if breed_id else MarketPrice.breed_id.is_(None),
                MarketPrice.price_date == price_date
            )
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update
        existing.min_price = min_price
        existing.max_price = max_price
        existing.avg_price = avg_price
        existing.unit = "Head"
        existing.meta_data = {"variations": variations, "variation_count": len(variations)}
        existing.fetched_at = datetime.now(timezone.utc)
        action = "updated"
    else:
        # Insert
        price = MarketPrice(
            marketplace_id=marketplace_id,
            livestock_id=livestock_id,
            breed_id=breed_id,
            min_price=min_price,
            max_price=max_price,
            avg_price=avg_price,
            unit="Head",
            price_date=price_date,
            meta_data={"variations": variations, "variation_count": len(variations)}
        )
        db.add(price)
        action = "inserted"

    await db.flush()  # Use flush instead of commit - commit will be called by caller
    return {"action": action, "livestock_name": livestock_name, "breed_name": breed_name, "variation_count": len(variations)}


async def sync_livestock_prices():
    """Main sync function"""

    async with async_session_maker() as db:
        try:
            logger.info("Starting livestock prices sync from NMIS API...")
            print("=" * 80)

            # Get all livestock marketplaces from database
            result = await db.execute(select(Marketplace).where(Marketplace.marketplace_type == "livestock"))
            marketplaces = result.scalars().all()

            logger.info(f"Found {len(marketplaces)} marketplaces")

            stats = {
                "marketplaces_processed": 0,
                "marketplaces_with_prices": 0,
                "marketplaces_without_prices": 0,
                "prices_inserted": 0,
                "prices_updated": 0,
                "errors": 0
            }

            for i, marketplace in enumerate(marketplaces, 1):
                try:
                    # Extract marketplace info early to avoid lazy loading issues
                    marketplace_id = marketplace.marketplace_id
                    marketplace_name = marketplace.name
                    
                    # Fetch prices for this marketplace
                    prices = await fetch_livestock_prices(marketplace_id)

                    if prices:
                        stats["marketplaces_with_prices"] += 1
                        print(f"\n[{i}/{len(marketplaces)}] {marketplace_name}")
                        print(f"  Found {len(prices)} livestock price entries")

                        # Group prices by (livestock_name, breed_name) to aggregate variations
                        grouped_prices = defaultdict(list)
                        for price_data in prices:
                            livestock_name = price_data.get("cName")
                            breed_name = price_data.get("varietyName", "").strip() if price_data.get("varietyName") else ""
                            key = (livestock_name, breed_name)
                            grouped_prices[key].append(price_data)

                        print(f"  Grouped into {len(grouped_prices)} unique livestock/breed combinations")

                        for (livestock_name, breed_name), price_list in grouped_prices.items():
                            try:
                                # Insert/update aggregated price
                                result = await upsert_livestock_price(db, marketplace_id, price_list)

                                if result["action"] == "inserted":
                                    stats["prices_inserted"] += 1
                                    variation_count = result.get("variation_count", 1)
                                    if breed_name:
                                        print(f"    ✓ Inserted: {livestock_name} - {breed_name} ({variation_count} variations)")
                                    else:
                                        print(f"    ✓ Inserted: {livestock_name} ({variation_count} variations)")
                                else:
                                    stats["prices_updated"] += 1

                            except Exception as e:
                                stats["errors"] += 1
                                logger.error(f"Error processing price {livestock_name}: {e}")

                        # Commit all changes after processing all items for this marketplace
                        await db.commit()

                    else:
                        stats["marketplaces_without_prices"] += 1

                    stats["marketplaces_processed"] += 1

                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Error for marketplace {marketplace_name if 'marketplace_name' in locals() else 'unknown'}: {e}")

            print("\n" + "=" * 80)
            logger.info("✓ Livestock prices sync complete!")
            logger.info(f"  Marketplaces processed:         {stats['marketplaces_processed']}")
            logger.info(f"  Marketplaces with prices:       {stats['marketplaces_with_prices']}")
            logger.info(f"  Marketplaces without prices:    {stats['marketplaces_without_prices']}")
            logger.info(f"  Prices inserted:                {stats['prices_inserted']}")
            logger.info(f"  Prices updated:                 {stats['prices_updated']}")
            logger.info(f"  Errors:                         {stats['errors']}")

        except Exception as e:
            logger.error(f"✗ Fatal error: {e}", exc_info=True)
            raise


async def main():
    """Main function"""
    try:
        await sync_livestock_prices()
    except Exception as e:
        logger.error(f"✗ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
