"""
Sync crop market prices from NMIS API (Table Endpoint) to database

This script uses the 'getMarketTable' endpoint which provides historical data and precise collection dates.
Only updates existing records with correct dates - does not insert new records.

Usage:
    python scripts/scrapers/sync_crop_prices_table.py
"""

import asyncio
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple
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

# API has a limit on how many IDs can be passed at once
MAX_IDS_PER_REQUEST = 10


async def get_crop_nmis_ids(db) -> List[int]:
    """Get all nmis_crop_id values from database"""
    result = await db.execute(
        select(Crop.nmis_crop_id).where(
            and_(
                Crop.nmis_crop_id.isnot(None),
                Crop.category == "agricultural"
            )
        )
    )
    return [row[0] for row in result.fetchall()]


async def fetch_crop_prices_table(marketplace_id: int, crop_ids: List[int]) -> List[dict]:
    """
    Fetch crop prices using getMarketTable endpoint.
    Pass IDs in chunks to avoid API limits.
    """
    all_data = []
    crop_ids = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30]  # For testing - replace with dynamic crop_ids from DB
    
    # Split IDs into chunks to avoid API errors with too many IDs
    for i in range(0, len(crop_ids), MAX_IDS_PER_REQUEST):
        chunk = crop_ids[i:i + MAX_IDS_PER_REQUEST]
        ids_str = ",".join(str(id) for id in chunk)
        
        
        # API requires quotes around path parameters
        url = f"https://nmis.et/api/web/getMarketTable/'{marketplace_id}'/'{ids_str}'/en/null/null"

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


async def load_crops_cache(db) -> Dict[str, "Crop"]:
    """Load all crops to help with fuzzy matching names"""
    result = await db.execute(select(Crop).where(Crop.category == "agricultural"))
    crops = result.scalars().all()
    # Return dict of lowercase name -> Crop object
    return {c.name.lower(): c for c in crops}


def parse_crop_string(variety_string: str, crops_cache: Dict[str, "Crop"]) -> Tuple["Crop", str]:
    """
    Parse 'Variety Name' e.g. 'White Teff (Quintal)' into (Crop, Variety).
    Returns (CropObject, VarietyName)
    
    Simply uses the full variety_string for DB lookup with spaces stripped.
    """
    if not variety_string:
        return None, None
    
    # Use the full variety_string directly (strip spaces)
    variety_name = variety_string.strip()
    
    # Identify which crop this variety belongs to by checking crop names in the string
    name_lower = variety_name.lower()
    matched_crop = None
    
    # Try exact match with crop name first
    if name_lower in crops_cache:
        matched_crop = crops_cache[name_lower]
    else:
        # Check for crop names within the string
        # Sort by length (longest first) to match more specific names first
        sorted_crop_names = sorted(crops_cache.keys(), key=len, reverse=True)
        for c_name in sorted_crop_names:
            # Use word boundary regex to avoid partial matches
            pattern = r'\b' + re.escape(c_name) + r'\b'
            if re.search(pattern, name_lower):
                matched_crop = crops_cache[c_name]
                break
        
        # If still no match, try stripping common prefixes/suffixes
        if not matched_crop:
            # Common prefixes to strip
            prefixes_to_strip = ['raw ', 'fresh ', 'dried ', 'green ', 'ripe ']
            cleaned_name = name_lower
            for prefix in prefixes_to_strip:
                if cleaned_name.startswith(prefix):
                    cleaned_name = cleaned_name[len(prefix):]
                    break
            
            # Try matching again with cleaned name
            for c_name in sorted_crop_names:
                pattern = r'\b' + re.escape(c_name) + r'\b'
                if re.search(pattern, cleaned_name):
                    matched_crop = crops_cache[c_name]
                    logger.debug(f"Matched '{variety_string}' to crop '{matched_crop.name}' after stripping prefix")
                    break
    
    if matched_crop:
        logger.debug(f"parse_crop_string: '{variety_string}' -> crop={matched_crop.name}, variety={variety_name}")
    else:
        logger.debug(f"parse_crop_string: '{variety_string}' -> NO CROP MATCH")
    
    return matched_crop, variety_name




async def upsert_aggregated_prices(
    db,
    marketplace_id: int,
    marketplace_name: str,
    grouped_entries: Dict[Tuple, List[dict]],
    crops_cache: Dict[str, "Crop"]
) -> Dict[str, any]:
    """Upsert aggregated price records for crops"""
    stats = {
        "inserted": 0, 
        "updated": 0, 
        "skipped": 0,
        "skipped_details": [],
        "updated_price_ids": set()  # Track which price records were updated
    }
    
    for (variety_str, p_date), entries in grouped_entries.items():
        try:
            variety_name = variety_str.strip()
            # Look up variety directly by name (no crop matching needed)
            v_res = await db.execute(select(CropVariety).where(
                CropVariety.name.ilike(variety_name)
            ))
            v = v_res.scalar_one_or_none()
            if not v:
                logger.warning(f"Variety '{variety_name}' not found in database")
                stats["skipped"] += 1
                stats["skipped_details"].append({
                    "marketplace": marketplace_name,
                    "item": variety_str,
                    "variety": variety_name,
                    "date": p_date,
                    "reason": f"Variety '{variety_name}' not found in database"
                })
                continue
            
            variety_id = v.variety_id
            crop_id = v.crop_id

            # Aggregate stats - ONLY using latest date entries (already filtered)
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
                    "volume": item.get("volume"),
                    "pmin": pmin if pmin > 0 else None,
                    "pmax": pmax if pmax > 0 else None,
                    "wmin": item.get("wmin"),
                    "wmax": item.get("wmax"),
                    "rmin": item.get("rmin"),
                    "rmax": item.get("rmax"),
                    "collectedDate": str(p_date),
                })

            min_price = min(all_mins) if all_mins else (min(all_maxs) if all_maxs else None)
            max_price = max(all_maxs) if all_maxs else (max(all_mins) if all_mins else None)
            
            avg_price = None
            if all_mins or all_maxs:
                all_vals = all_mins + all_maxs
                avg_price = sum(all_vals) / len(all_vals)

            # Find existing record (UPDATE ONLY mode)
            if variety_id is not None:
                result = await db.execute(
                    select(MarketPrice).where(
                        and_(
                            MarketPrice.marketplace_id == marketplace_id,
                            MarketPrice.crop_id == crop_id,
                            MarketPrice.variety_id == variety_id
                        )
                    ).order_by(MarketPrice.price_date.desc()).limit(1)
                )
            else:
                result = await db.execute(
                    select(MarketPrice).where(
                        and_(
                            MarketPrice.marketplace_id == marketplace_id,
                            MarketPrice.crop_id == crop_id,
                            MarketPrice.variety_id.is_(None)
                        )
                    ).order_by(MarketPrice.price_date.desc()).limit(1)
                )
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update existing record with correct date
                if existing.price_date != p_date:
                    existing.price_date = p_date

                stats["updated"] += 1
                stats["updated_price_ids"].add(existing.price_id)  # Track this update

                print(f"   ✓ Updated {variety_name}: Date -> {p_date}")
            else:
                # No insert - update only mode
                stats["skipped"] += 1
                stats["skipped_details"].append({
                    "marketplace": marketplace_name,
                    "item": variety_name,
                    "variety": variety_name,
                    "date": p_date,
                    "reason": "No existing record to update"
                })
                
        except Exception as e:
            logger.error(f"Error aggregating {variety_str}: {e}")
            stats["skipped"] += 1
            stats["skipped_details"].append({
                "marketplace": marketplace_name,
                "item": variety_str,
                "variety": None,
                "date": p_date if 'p_date' in locals() else None,
                "reason": f"Error: {str(e)}"
            })

    await db.commit()
    return stats


async def sync_crop_prices():
    """Main sync function for crop prices"""
    async with async_session_maker() as db:
        logger.info("Starting crop prices sync (Table API)...")
        print("=" * 80)
        
        # Load Crops Cache
        crops_cache = await load_crops_cache(db)
        logger.info(f"Loaded {len(crops_cache)} crops for matching")
        
        # Get all nmis_crop_ids from database dynamically
        crop_ids = await get_crop_nmis_ids(db)
        if not crop_ids:
            logger.warning("No crops with nmis_crop_id found in database!")
            return
        
        logger.info(f"Found {len(crop_ids)} crop IDs in database")
        
        result = await db.execute(select(Marketplace).where(
            and_(
                Marketplace.marketplace_type == "crop",
            )
        ))
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
                    select(MarketPrice.price_id, MarketPrice.crop_id, MarketPrice.variety_id, MarketPrice.price_date)
                    .where(MarketPrice.marketplace_id == marketplace_id)
                )
                existing_prices = {row.price_id: row for row in existing_prices_result.fetchall()}
                
                # Fetch data using dynamic IDs from database
                data = await fetch_crop_prices_table(marketplace_id, crop_ids)
                
                if not data:
                    print(f"[{i}/{len(marketplaces)}] {marketplace_name}: No data")
                    continue
                
                print(f"[{i}/{len(marketplaces)}] {marketplace_name}: Fetched {len(data)} rows", end="")
                
                # Group by (VarietyString) to find LATEST date only
                latest_dates = {}
                parsed_items = []

                for item in data:
                    v_str = item.get("varietyName", "")
                    d_str = item.get("collectionDate")
                    if not d_str:
                        continue
                    try:
                        p_date = datetime.strptime(d_str, "%Y-%m-%d").date()
                    except ValueError:
                        logger.warning(f"Invalid date format: {d_str}")
                        continue
                    
                    # Track only the LATEST date for each item
                    if v_str not in latest_dates or p_date > latest_dates[v_str]:
                        latest_dates[v_str] = p_date
                    parsed_items.append((v_str, p_date, item))

                # Group by (VarietyString, Date) but ONLY for latest dates
                # This filters out all old dates!
                grouped = defaultdict(list)
                for v_str, p_date, item in parsed_items:
                    if p_date == latest_dates.get(v_str):
                        grouped[(v_str, p_date)].append(item)
                
                # Upsert only latest date records
                stats = await upsert_aggregated_prices(db, marketplace.marketplace_id, marketplace.name, grouped, crops_cache)
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
                        "marketplace": marketplace.name,
                        "price_id": price_id,
                        "crop_id": record.crop_id,
                        "variety_id": record.variety_id,
                        "price_date": record.price_date
                    })
                    print(f"   - Untouched Record ID: {price_id} (Crop ID: {record.crop_id}, Variety ID: {record.variety_id}, Date: {record.price_date})")
                
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
                    variety_str = f" ({item['variety']})" if item['variety'] else ""
                    print(f"    - {item['marketplace']}: {item['item']}{variety_str} [{item['date']}]")
            
            print("\n" + "=" * 80)
        
        if all_untouched_records:
            print(f"\nUNTOUCHED RECORDS ({len(all_untouched_records)} records exist in DB but weren't updated):")
            print("=" * 80)
            
            # Get crop and variety names for better reporting
            crop_cache = {}
            variety_cache = {}
            
            # Fetch all crop names
            crop_result = await db.execute(select(Crop.crop_id, Crop.name))
            for row in crop_result.fetchall():
                crop_cache[row.crop_id] = row.name
            
            # Fetch all variety names
            variety_result = await db.execute(select(CropVariety.variety_id, CropVariety.name))
            for row in variety_result.fetchall():
                variety_cache[row.variety_id] = row.name
            
            # Group by marketplace
            by_marketplace = defaultdict(list)
            for record in all_untouched_records:
                by_marketplace[record["marketplace"]].append(record)
            
            for marketplace_name, records in list(by_marketplace.items()):
                print(f"\n  {marketplace_name}: {len(records)} untouched")
                for record in records:
                    crop_name = crop_cache.get(record["crop_id"], f"ID:{record['crop_id']}")
                    variety_name = variety_cache.get(record["variety_id"], "") if record["variety_id"] else None
                    variety_str = f" ({variety_name})" if variety_name else ""
                    print(f"    - {crop_name}{variety_str} [Last: {record['price_date']}]")
            
            print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(sync_crop_prices())
