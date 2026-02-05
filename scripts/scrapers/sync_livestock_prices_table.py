"""
Sync livestock market prices from NMIS API (Table Endpoint) to database

This script uses the 'getMarketTable' endpoint which provides historical data and precise collection dates.
Only updates existing records with correct dates - does not insert new records.

Usage:
    python scripts/scrapers/sync_livestock_prices_table.py
"""

import asyncio
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
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

# API has a limit on how many IDs can be passed at once
MAX_IDS_PER_REQUEST = 10


async def get_livestock_nmis_ids(db) -> List[int]:
    """Get all nmis_livestock_id values from database"""
    result = await db.execute(
        select(Livestock.nmis_livestock_id).where(
            Livestock.nmis_livestock_id.isnot(None)
        )
    )
    return [row[0] for row in result.fetchall()]


async def fetch_livestock_prices_table(marketplace_id: int, livestock_ids: List[int]) -> List[dict]:
    """
    Fetch livestock prices using getMarketTable endpoint.
    Pass IDs in chunks to avoid API limits.
    """
    all_data = []
    
    # Split IDs into chunks to avoid API errors with too many IDs
    for i in range(0, len(livestock_ids), MAX_IDS_PER_REQUEST):
        chunk = livestock_ids[i:i + MAX_IDS_PER_REQUEST]
        ids_str = ",".join(str(id) for id in chunk)
        
        # API requires quotes around path parameters
        url = f"https://nmis.et/api/web-livestock/getMarketTable/'{marketplace_id}'/'{ids_str}'/en/null/null"

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            try:
                response = await client.get(url)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if isinstance(data, list):
                            all_data.extend(data)
                    except ValueError as e:
                        logger.warning(f"Failed to parse JSON response from {url}: {e}")
                else:
                    logger.warning(f"API returned status {response.status_code} for {url}")
            except httpx.TimeoutException as e:
                logger.error(f"Timeout fetching from {url}: {e}")
            except httpx.RequestError as e:
                logger.error(f"Request error fetching from {url}: {e}")
    
    return all_data


def parse_livestock_string(variety_string: str) -> Tuple[str, Optional[str]]:
    """
    Parse 'Variety Name' from API which often contains 'Name(Breed)'.
    Example: 'Ox(Indegenous)' -> ('Ox', 'Indegenous')
    Example: 'Male Young Goat' -> ('Male Young Goat', None)
    """
    if not variety_string:
        return "", None
    
    # Check for format "Name(Breed)"
    match = re.match(r"^(.*)\((.*)\)$", variety_string.strip())
    if match:
        name = match.group(1).strip()
        breed = match.group(2).strip()
        return name, breed
    
    return variety_string.strip(), None


async def upsert_aggregated_prices(
    db,
    marketplace_id: int,
    marketplace_name: str,
    grouped_entries: Dict[Tuple, List[dict]]
) -> Dict[str, any]:
    """Upsert aggregated livestock price records"""
    stats = {
        "inserted": 0, 
        "updated": 0, 
        "skipped": 0,
        "skipped_details": [],
        "updated_price_ids": set()  # Track which price records were updated
    }
    
    for (livestock_name, breed_name, p_date), entries in grouped_entries.items():
        try:
            # 1. Resolve Livestock & Breed IDs
            livestock_result = await db.execute(
                select(Livestock).where(Livestock.name == livestock_name)
            )
            livestock = livestock_result.scalar_one_or_none()
            if not livestock:
                stats["skipped"] += 1
                stats["skipped_details"].append({
                    "marketplace": marketplace_name,
                    "item": livestock_name,
                    "breed": breed_name,
                    "date": p_date,
                    "reason": f"Livestock '{livestock_name}' not found in DB"
                })
                continue
                
            livestock_id = livestock.livestock_id
            
            breed_id = None
            if breed_name:
                breed_result = await db.execute(select(LivestockBreed).where(
                    and_(
                        LivestockBreed.livestock_id == livestock_id,
                        LivestockBreed.name == breed_name
                    )
                ))
                breed = breed_result.scalar_one_or_none()
                if breed:
                    breed_id = breed.breed_id

            # 2. Aggregate data - ONLY using latest date entries (already filtered)
            all_mins = []
            all_maxs = []
            variations = []
            
            for item in entries:
                pmin = float(item.get("pmin", 0) or 0)
                pmax = float(item.get("pmax", 0) or 0)
                if pmin > 0:
                    all_mins.append(pmin)
                if pmax > 0:
                    all_maxs.append(pmax)
                
                variations.append({
                    "grade": item.get("grade"),
                    "productionType": item.get("productionType"),
                    "location": item.get("location"),
                    "gender": item.get("gender"),
                    "age": item.get("age"),
                    "pmin": pmin if pmin > 0 else None,
                    "pmax": pmax if pmax > 0 else None,
                    "volume": item.get("volume"),
                    "collectedDate": str(p_date),
                })
            
            min_price = min(all_mins) if all_mins else (min(all_maxs) if all_maxs else None)
            max_price = max(all_maxs) if all_maxs else (max(all_mins) if all_mins else None)
            
            avg_price = None
            if all_mins or all_maxs:
                all_vals = all_mins + all_maxs
                avg_price = sum(all_vals) / len(all_vals)

            # 3. Find existing record (UPDATE ONLY mode)
            if breed_id is not None:
                result = await db.execute(
                    select(MarketPrice).where(
                        and_(
                            MarketPrice.marketplace_id == marketplace_id,
                            MarketPrice.livestock_id == livestock_id,
                            MarketPrice.breed_id == breed_id
                        )
                    ).order_by(MarketPrice.price_date.desc()).limit(1)
                )
            else:
                result = await db.execute(
                    select(MarketPrice).where(
                        and_(
                            MarketPrice.marketplace_id == marketplace_id,
                            MarketPrice.livestock_id == livestock_id,
                            MarketPrice.breed_id.is_(None)
                        )
                    ).order_by(MarketPrice.price_date.desc()).limit(1)
                )
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update existing record with correct date if needed
                if existing.price_date != p_date:
                    existing.price_date = p_date

                existing.min_price = min_price
                existing.max_price = max_price
                existing.avg_price = avg_price
                existing.unit = "Head"
                existing.meta_data = {"variations": variations, "variation_count": len(variations)}
                existing.fetched_at = datetime.now(timezone.utc)
                stats["updated"] += 1
                stats["updated_price_ids"].add(existing.price_id)  # Track this update

                print(f"    ✓ Updated {livestock_name} ({breed_name}): Date -> {p_date}")

            else:
                # No insert - update only mode
                stats["skipped"] += 1
                stats["skipped_details"].append({
                    "marketplace": marketplace_name,
                    "item": livestock_name,
                    "breed": breed_name,
                    "date": p_date,
                    "reason": "No existing record to update"
                })
                
        except Exception as e:
            logger.error(f"Error aggregating {livestock_name}: {e}")
            stats["skipped"] += 1
            stats["skipped_details"].append({
                "marketplace": marketplace_name,
                "item": livestock_name,
                "breed": breed_name if 'breed_name' in locals() else None,
                "date": p_date if 'p_date' in locals() else None,
                "reason": f"Error: {str(e)}"
            })

    await db.commit()
    return stats


async def sync_livestock_prices():
    """Main sync function for livestock prices"""
    async with async_session_maker() as db:
        logger.info("Starting livestock prices sync (Table API)...")
        print("=" * 80)
        
        # Get all nmis_livestock_ids from database dynamically
        livestock_ids = await get_livestock_nmis_ids(db)
        if not livestock_ids:
            logger.warning("No livestock with nmis_livestock_id found in database!")
            return
        
        logger.info(f"Found {len(livestock_ids)} livestock IDs in database")
        
        result = await db.execute(
            select(Marketplace).where(Marketplace.marketplace_type == "livestock")
        )
        marketplaces = result.scalars().all()
        
        total_inserted = 0
        total_updated = 0
        total_skipped = 0
        all_skipped_details = []
        all_updated_price_ids = set()
        all_untouched_records = []
        
        for i, marketplace in enumerate(marketplaces, 1):
            try:
                # Extract marketplace info early to avoid lazy loading issues
                marketplace_id = marketplace.marketplace_id
                marketplace_name = marketplace.name
                
                # Get all existing price records for this marketplace (to track untouched ones)
                existing_prices_result = await db.execute(
                    select(MarketPrice.price_id, MarketPrice.livestock_id, MarketPrice.breed_id, MarketPrice.price_date)
                    .where(MarketPrice.marketplace_id == marketplace_id)
                )
                existing_prices = {row.price_id: row for row in existing_prices_result.fetchall()}
                
                # Fetch history table using dynamic IDs
                data = await fetch_livestock_prices_table(marketplace_id, livestock_ids)
                
                if not data:
                    print(f"[{i}/{len(marketplaces)}] {marketplace_name}: No data", end="\n")
                    continue
                    
                print(f"[{i}/{len(marketplaces)}] {marketplace_name}: Fetched {len(data)} rows", end="\n")
                
                # Group by (Name, Breed) to find LATEST date only
                latest_dates: Dict[Tuple[str, Optional[str]], date] = {}
                parsed_items: List[Tuple[str, Optional[str], date, dict]] = []
                
                for item in data:
                    v_str = item.get("varietyName", "")
                    name, breed = parse_livestock_string(v_str)
                    
                    d_str = item.get("collectionDate")
                    if not d_str:
                        continue
                    try:
                        p_date = datetime.strptime(d_str, "%Y-%m-%d").date()
                    except ValueError:
                        logger.warning(f"Invalid date format: {d_str}")
                        continue
                        
                    if name:
                        key = (name, breed)
                        # Track only the LATEST date for each item
                        if key not in latest_dates or p_date > latest_dates[key]:
                            latest_dates[key] = p_date
                        parsed_items.append((name, breed, p_date, item))

                # Group by (Name, Breed, Date) but ONLY for latest dates
                # This filters out all old dates!
                grouped: Dict[Tuple[str, Optional[str], date], List[dict]] = defaultdict(list)
                for name, breed, p_date, item in parsed_items:
                    if p_date == latest_dates.get((name, breed)):
                        grouped[(name, breed, p_date)].append(item)
                
                # Upsert only latest date records
                stats = await upsert_aggregated_prices(db, marketplace_id, marketplace_name, grouped)
                total_inserted += stats["inserted"]
                total_updated += stats["updated"]
                total_skipped += stats["skipped"]
                all_skipped_details.extend(stats["skipped_details"])
                all_updated_price_ids.update(stats["updated_price_ids"])
                
                # Find untouched records for this marketplace
                untouched_ids = set(existing_prices.keys()) - stats["updated_price_ids"]
                for price_id in untouched_ids:
                    record = existing_prices[price_id]
                    all_untouched_records.append({
                        "marketplace": marketplace_name,
                        "price_id": price_id,
                        "livestock_id": record.livestock_id,
                        "breed_id": record.breed_id,
                        "price_date": record.price_date
                    })
                
                print(f" -> {stats['updated']} updated, {stats['skipped']} skipped, {len(untouched_ids)} untouched")

            except Exception as e:
                logger.error(f"Error processing {marketplace_name if 'marketplace_name' in locals() else 'unknown'}: {e}")
                print()

        print("=" * 80)
        print(f"\nSUMMARY:")
        print(f"  Total Updated: {total_updated}")
        print(f"  Total Skipped: {total_skipped}")
        print(f"  Total Untouched: {len(all_untouched_records)}")
        
        if all_skipped_details:
            print(f"\nSKIPPED ITEMS DETAILS ({len(all_skipped_details)} items):")
            print("=" * 80)
            
            # Group by reason
            by_reason = defaultdict(list)
            for skip in all_skipped_details:
                by_reason[skip["reason"]].append(skip)
            
            for reason, items in by_reason.items():
                print(f"\n  Reason: {reason}")
                print(f"  Count: {len(items)}")
                print(f"  Examples:")
                for item in items:
                    breed_str = f" ({item['breed']})" if item['breed'] else ""
                    print(f"    - {item['marketplace']}: {item['item']}{breed_str} [{item['date']}]")

            
            print("\n" + "=" * 80)
        
        if all_untouched_records:
            print(f"\nUNTOUCHED RECORDS ({len(all_untouched_records)} records exist in DB but weren't updated):")
            print("=" * 80)
            
            # Get livestock and breed names for better reporting
            livestock_cache = {}
            breed_cache = {}
            
            # Fetch all livestock names
            livestock_result = await db.execute(select(Livestock.livestock_id, Livestock.name))
            for row in livestock_result.fetchall():
                livestock_cache[row.livestock_id] = row.name
            
            # Fetch all breed names
            breed_result = await db.execute(select(LivestockBreed.breed_id, LivestockBreed.name))
            for row in breed_result.fetchall():
                breed_cache[row.breed_id] = row.name
            
            # Group by marketplace
            by_marketplace = defaultdict(list)
            for record in all_untouched_records:
                by_marketplace[record["marketplace"]].append(record)
            
            for marketplace_name, records in list(by_marketplace.items()):
                print(f"\n  {marketplace_name}: {len(records)} untouched")
                for record in records:
                    livestock_name = livestock_cache.get(record["livestock_id"], f"ID:{record['livestock_id']}")
                    breed_name = breed_cache.get(record["breed_id"], "") if record["breed_id"] else None
                    breed_str = f" ({breed_name})" if breed_name else ""
                    print(f"    - {livestock_name}{breed_str} [Last: {record['price_date']}]")
            
            print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(sync_livestock_prices())
