"""
Sync crop prices from NMIS API to database

Usage:
    python scripts/scrapers/sync_crop_prices.py
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
from app.models.market import Crop, CropVariety, MarketPrice, Marketplace
from helpers.utils import get_logger

logger = get_logger(__name__)


async def fetch_marketplace_crops(marketplace_id: int):
    """Fetch crop price data for a specific marketplace"""
    url = f"https://nmis.et/api/web/getCurrentMarketData/{marketplace_id}/en"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()
            else:
                return []
        except Exception:
            return []


async def upsert_crop_price(db, marketplace_id: int, price_data_list: list) -> Dict[str, Any]:
    """Insert or update crop price (aggregates multiple variations if present)"""
    try:
        # Group by (crop_name, variety_name) - these should all be the same
        first_item = price_data_list[0]
        crop_name = first_item.get("cName", "").strip()
        variety_name = first_item.get("varietyName", "").strip() if first_item.get("varietyName") else None
        nmis_crop_id = first_item.get("cropId")

        if not crop_name:
            raise ValueError("cName (crop name) is required")

        # Find crop by nmis_crop_id or name
        crop = None
        if nmis_crop_id:
            crop_result = await db.execute(
                select(Crop).where(
                    and_(
                        Crop.nmis_crop_id == nmis_crop_id,
                        Crop.category == "agricultural"
                    )
                )
            )
            crop = crop_result.scalar_one_or_none()

        if not crop:
            crop_result = await db.execute(
                select(Crop).where(
                    and_(
                        Crop.name == crop_name,
                        Crop.category == "agricultural"
                    )
                )
            )
            crop = crop_result.scalar_one_or_none()

        if not crop:
            raise ValueError(f"Crop '{crop_name}' not found in database")

        crop_id = crop.crop_id

        # Handle variety if present
        variety_id = None
        if variety_name:
            variety_result = await db.execute(
                select(CropVariety).where(
                    and_(
                        CropVariety.crop_id == crop_id,
                        CropVariety.name == variety_name
                    )
                )
            )
            variety = variety_result.scalar_one_or_none()
            if variety:
                variety_id = variety.variety_id

        # Aggregate prices from all variations
        all_retail_mins = []
        all_retail_maxs = []
        all_producer_mins = []
        all_producer_maxs = []
        all_wholesale_mins = []
        all_wholesale_maxs = []
        variations = []

        for item in price_data_list:
            rmin = item.get("rmin", 0) or 0
            rmax = item.get("rmax", 0) or 0
            pmin = item.get("pmin", 0) or 0
            pmax = item.get("pmax", 0) or 0
            wmin = item.get("wmin", 0) or 0
            wmax = item.get("wmax", 0) or 0

            if rmin > 0:
                all_retail_mins.append(rmin)
            if rmax > 0:
                all_retail_maxs.append(rmax)
            if pmin > 0:
                all_producer_mins.append(pmin)
            if pmax > 0:
                all_producer_maxs.append(pmax)
            if wmin > 0:
                all_wholesale_mins.append(wmin)
            if wmax > 0:
                all_wholesale_maxs.append(wmax)

            # Store full variation details
            variations.append({
                "rmin": rmin if rmin > 0 else None,
                "rmax": rmax if rmax > 0 else None,
                "pmin": pmin if pmin > 0 else None,
                "pmax": pmax if pmax > 0 else None,
                "wmin": wmin if wmin > 0 else None,
                "wmax": wmax if wmax > 0 else None,
                "volume": item.get("volume")
            })

        # Calculate aggregated prices (prefer retail, fallback to producer, then wholesale)
        all_mins = []
        all_maxs = []

        if all_retail_mins or all_retail_maxs:
            all_mins.extend(all_retail_mins)
            all_maxs.extend(all_retail_maxs)
        elif all_producer_mins or all_producer_maxs:
            all_mins.extend(all_producer_mins)
            all_maxs.extend(all_producer_maxs)
        elif all_wholesale_mins or all_wholesale_maxs:
            all_mins.extend(all_wholesale_mins)
            all_maxs.extend(all_wholesale_maxs)

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

        # Extract unit from variety name if present
        unit = None
        if variety_name and "(" in variety_name and ")" in variety_name:
            unit = variety_name[variety_name.rfind("(") + 1:variety_name.rfind(")")]

        # Use today's date as price date
        price_date = date.today()

        # Check if price exists
        result = await db.execute(
            select(MarketPrice).where(
                and_(
                    MarketPrice.marketplace_id == marketplace_id,
                    MarketPrice.crop_id == crop_id,
                    MarketPrice.variety_id == variety_id if variety_id else MarketPrice.variety_id.is_(None),
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
            existing.unit = unit
            existing.meta_data = {"variations": variations, "variation_count": len(variations)}
            existing.fetched_at = datetime.now(timezone.utc)
            action = "updated"
        else:
            # Insert
            price = MarketPrice(
                marketplace_id=marketplace_id,
                crop_id=crop_id,
                variety_id=variety_id,
                min_price=min_price,
                max_price=max_price,
                avg_price=avg_price,
                unit=unit,
                price_date=price_date,
                meta_data={"variations": variations, "variation_count": len(variations)}
            )
            db.add(price)
            action = "inserted"

        await db.commit()
        return {"action": action, "crop_name": crop_name, "variety_name": variety_name, "variation_count": len(variations)}

    except Exception as e:
        await db.rollback()
        raise


async def sync_prices():
    """Main sync function"""

    async with async_session_maker() as db:
        try:
            logger.info("Starting crop prices sync from NMIS API...")
            print("=" * 80)

            # Get all marketplaces
            result = await db.execute(select(Marketplace).where(Marketplace.marketplace_type == "crop"))
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
                    # Fetch prices for this marketplace
                    crop_data_list = await fetch_marketplace_crops(marketplace.marketplace_id)

                    if crop_data_list:
                        stats["marketplaces_with_prices"] += 1
                        print(f"\n[{i}/{len(marketplaces)}] {marketplace.name}")
                        print(f"  Found {len(crop_data_list)} crop price entries")

                        # Group prices by (crop_name, variety_name) to aggregate variations
                        grouped_prices = defaultdict(list)
                        for price_data in crop_data_list:
                            crop_name = price_data.get("cName", "").strip()
                            variety_name = price_data.get("varietyName", "").strip() if price_data.get("varietyName") else ""
                            key = (crop_name, variety_name)
                            grouped_prices[key].append(price_data)

                        print(f"  Grouped into {len(grouped_prices)} unique crop/variety combinations")

                        for (crop_name, variety_name), price_list in grouped_prices.items():
                            try:
                                result = await upsert_crop_price(db, marketplace.marketplace_id, price_list)

                                if result["action"] == "inserted":
                                    stats["prices_inserted"] += 1
                                    variation_count = result.get("variation_count", 1)
                                    if variety_name:
                                        print(f"    ✓ Inserted: {crop_name} - {variety_name} ({variation_count} variations)")
                                    else:
                                        print(f"    ✓ Inserted: {crop_name} ({variation_count} variations)")
                                else:
                                    stats["prices_updated"] += 1

                            except Exception as e:
                                stats["errors"] += 1
                                logger.error(f"Error processing price {crop_name}: {e}")

                    else:
                        stats["marketplaces_without_prices"] += 1

                    stats["marketplaces_processed"] += 1

                except Exception as e:
                    logger.error(f"Error for marketplace {marketplace.name}: {e}")

            print("\n" + "=" * 80)
            logger.info("✓ Crop prices sync complete!")
            logger.info(f"  Marketplaces processed:       {stats['marketplaces_processed']}")
            logger.info(f"  Marketplaces with prices:     {stats['marketplaces_with_prices']}")
            logger.info(f"  Marketplaces without prices:  {stats['marketplaces_without_prices']}")
            logger.info(f"  Prices inserted:              {stats['prices_inserted']}")
            logger.info(f"  Prices updated:               {stats['prices_updated']}")
            logger.info(f"  Errors:                       {stats['errors']}")

        except Exception as e:
            logger.error(f"✗ Fatal error: {e}", exc_info=True)
            raise


async def main():
    """Main function"""
    try:
        await sync_prices()
    except Exception as e:
        logger.error(f"✗ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
