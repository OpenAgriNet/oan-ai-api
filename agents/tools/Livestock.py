from pydantic_ai import RunContext
from app.models.market import Livestock, LivestockBreed, MarketPrice, Marketplace
from agents.deps import FarmerContext
from app.database import async_session_maker
from sqlalchemy import func, select, or_
from typing import List, Optional, Tuple
from sqlalchemy.orm import joinedload
from helpers.utils import get_logger

logger = get_logger(__name__)


async def _get_marketplace(
    db,
    marketplace_name: str,
    region: Optional[str] = None
) -> Tuple[Optional[Marketplace], Optional[str]]:
    """
    Internal helper to get livestock marketplace by name, optionally filtered by region.

    Returns:
        Tuple of (marketplace, error_message)
        - (Marketplace, None) if found
        - (None, error_message) if not found or ambiguous
    """
    stmt = select(Marketplace).where(
        Marketplace.marketplace_type == "livestock",
        Marketplace.is_active == True,
        or_(
            func.lower(Marketplace.name) == func.lower(marketplace_name),
            func.lower(Marketplace.name_amharic) == func.lower(marketplace_name),
            func.lower(Marketplace.name).contains(func.lower(marketplace_name)),
            func.lower(Marketplace.name_amharic).contains(func.lower(marketplace_name))
        )
    )

    # Filter by region if provided
    if region:
        stmt = stmt.where(
            or_(
                func.lower(Marketplace.region) == func.lower(region),
                func.lower(Marketplace.region_amharic) == func.lower(region)
            )
        )

    result = await db.execute(stmt)
    marketplaces = result.scalars().all()

    if not marketplaces:
        return None, f"Marketplace '{marketplace_name}' not found."

    if len(marketplaces) == 1:
        return marketplaces[0], None

    # Multiple matches - need region to disambiguate
    regions_list = [f"{m.name} ({m.region})" for m in marketplaces]
    return None, f"Multiple marketplaces found: {', '.join(regions_list)}. Please specify region."


async def list_livestock_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    region: Optional[str] = None
) -> str:
    """
    List all livestock types available in a specific livestock marketplace.

    Args:
        marketplace_name: Name of the livestock marketplace (e.g., "Dubti", "Aysaita")
        region: Optional region name to disambiguate if same marketplace name exists in multiple regions

    Returns:
        Formatted list of available livestock with Amharic names
    """
    logger.info(f"list_livestock_in_marketplace: marketplace={marketplace_name}, region={region}")

    async with async_session_maker() as db:
        marketplace, error = await _get_marketplace(db, marketplace_name, region)
        if error:
            return error

        stmt = (
            select(Livestock)
            .join(MarketPrice, MarketPrice.livestock_id == Livestock.livestock_id)
            .where(MarketPrice.marketplace_id == marketplace.marketplace_id)
            .where(MarketPrice.price_date >= (func.current_date() - 364))
            .options(joinedload(Livestock.breeds))
            .distinct()
            .order_by(Livestock.name)
        )
        result = await db.execute(stmt)
        livestocks = result.scalars().unique().all()

        if not livestocks:
            return f"No livestock found in {marketplace.name} marketplace."

        livestock_list = [
            f"* {livestock.name}" +
            (f" ({livestock.name_amharic})" if livestock.name_amharic else "") +
            (f" - Breeds: {', '.join([b.name for b in livestock.breeds])}" if livestock.breeds else "") +
            f"\n  Source: https://nmis.et/"
            for livestock in livestocks
        ]

        return (
            f"Livestock available in {marketplace.name} ({marketplace.region}):\n\n" +
            "\n".join(livestock_list)
        )


async def get_livestock_price_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    livestock_type: str,
    region: Optional[str] = None
) -> str:
    """
    Get detailed price information for a specific livestock type in a marketplace.
    
    ⚠️ NOTE: Use get_livestock_price_quick() instead for faster results.
    Only use this tool if get_livestock_price_quick() fails or you need to verify data.

    Args:
        marketplace_name: Name of the livestock marketplace
        livestock_type: Type of livestock (e.g., "Cattle", "Goat", "Sheep")
        region: Optional region name to disambiguate if same marketplace name exists in multiple regions

    Returns:
        Formatted price information with date
    """
    logger.info(f"get_livestock_price_in_marketplace: livestock={livestock_type}, marketplace={marketplace_name}, region={region}")

    async with async_session_maker() as db:
        marketplace, error = await _get_marketplace(db, marketplace_name, region)
        if error:
            return error

        stmt = (
            select(
                MarketPrice.min_price,
                MarketPrice.max_price,
                MarketPrice.avg_price,
                MarketPrice.modal_price,
                MarketPrice.price_date,
                MarketPrice.unit,
                Livestock.name_amharic.label('livestock_name_amharic'),
                Livestock.name.label('livestock_name'),
                LivestockBreed.name.label('breed_name'),
                LivestockBreed.name_amharic.label('breed_name_amharic')
            )
            .join(Livestock, MarketPrice.livestock_id == Livestock.livestock_id)
            .outerjoin(LivestockBreed, MarketPrice.breed_id == LivestockBreed.breed_id)
            .where(
                MarketPrice.marketplace_id == marketplace.marketplace_id,
                or_(
                    func.lower(Livestock.name) == livestock_type.lower(),
                    func.lower(Livestock.name).contains(livestock_type.lower()),
                    func.lower(Livestock.name_amharic) == livestock_type.lower(),
                    func.lower(Livestock.name_amharic).contains(livestock_type.lower())
                ),
                MarketPrice.price_date >= (func.current_date() - 364)
            )
            .order_by(MarketPrice.price_date.desc())
        )
        result = await db.execute(stmt)
        price_data_list = result.all()

        if not price_data_list:
            return f"No price data found for '{livestock_type}' in {marketplace.name}."

        price_data_breeds = {}
        for price_row in price_data_list:
            breed_key = price_row.breed_name or "Default"
            price_data_breeds[breed_key] = (
                f"{price_row.livestock_name} ({price_row.livestock_name_amharic}) prices in {marketplace.name}:\n\n"
                f"* Breed: {price_row.breed_name or 'N/A'}" +
                (f" ({price_row.breed_name_amharic})" if price_row.breed_name_amharic else "") + "\n"
                f"* Min Price: {price_row.min_price} ETB/{price_row.unit or 'Head'}\n"
                f"* Max Price: {price_row.max_price} ETB/{price_row.unit or 'Head'}\n"
                f"* Avg Price: {price_row.avg_price} ETB/{price_row.unit or 'Head'}\n"
                f"* Date: {price_row.price_date.strftime('%Y-%m-%d')}\n"
                f"* Source: https://nmis.et/"
            )

        return "\n\n".join(price_data_breeds.values())


async def compare_livestock_prices_nearby(
    ctx: RunContext[FarmerContext],
    livestock_type: str,
    marketplace_names: List[str],
) -> str:
    """
    Compare prices of a livestock type across multiple marketplaces.

    Args:
        livestock_type: Livestock type to compare (e.g., "Cattle", "Goat")
        marketplace_names: List of marketplace names to compare

    Returns:
        Formatted comparison of prices across markets
    """
    logger.info(f"compare_livestock_prices_nearby: livestock={livestock_type}, marketplaces={marketplace_names}")

    if not marketplace_names:
        return "No marketplaces provided for comparison."

    async with async_session_maker() as db:
        stmt = (
            select(
                Marketplace.name,
                Marketplace.region,
                MarketPrice.min_price,
                MarketPrice.max_price,
                MarketPrice.avg_price,
                MarketPrice.price_date,
                MarketPrice.unit,
                Livestock.name.label('livestock_name'),
                LivestockBreed.name.label('breed_name')
            )
            .join(MarketPrice, MarketPrice.marketplace_id == Marketplace.marketplace_id)
            .join(Livestock, MarketPrice.livestock_id == Livestock.livestock_id)
            .outerjoin(LivestockBreed, MarketPrice.breed_id == LivestockBreed.breed_id)
            .where(
                Marketplace.marketplace_type == "livestock",
                Marketplace.is_active == True,
                or_(
                    func.lower(Livestock.name) == livestock_type.lower(),
                    func.lower(Livestock.name).contains(livestock_type.lower()),
                    func.lower(Livestock.name_amharic) == livestock_type.lower(),
                    func.lower(Livestock.name_amharic).contains(livestock_type.lower())
                ),
                MarketPrice.price_date >= (func.current_date() - 364)
            )
            .where(
                or_(
                    Marketplace.name.in_(marketplace_names),
                    Marketplace.name_amharic.in_(marketplace_names)
                )
            )
            .order_by(MarketPrice.avg_price.asc())
        )
        result = await db.execute(stmt)
        markets = result.all()

        if not markets:
            return f"No price data found for '{livestock_type}' in the specified marketplaces."

        lines = [f"{livestock_type} price comparison:\n"]

        for idx, market in enumerate(markets, 1):
            lines.append(
                f"{idx}. **{market.name}** ({market.region})\n"
                f"   * Avg: {market.avg_price} ETB/{market.unit or 'Head'}\n"
                f"   * Range: {market.min_price} - {market.max_price} ETB\n"
                f"   * Date: {market.price_date.strftime('%Y-%m-%d')}\n"
                f"   * Source: https://nmis.et/"
            )

        return "\n\n".join(lines)


async def get_livestock_price_quick(
    ctx: RunContext[FarmerContext],
    livestock_type: str,
    marketplace_name: str
) -> str:
    """
    Get livestock price by marketplace name directly - no region needed. FAST VERSION.
    
    CRITICAL: Only call this tool if BOTH parameters are clearly specified by the user.
    DO NOT call this tool if:
    - User didn't mention a specific livestock type
    - User didn't mention a specific marketplace name
    - User said vague things like "the livestock" or "the price"
    
    If information is missing, ASK the user for it instead of calling this tool.
    
    Args:
        livestock_type: REQUIRED - Specific livestock type (e.g., "Cattle", "Goat", "Sheep", "Oxen")
                       Must be explicitly mentioned by user, not assumed.
        marketplace_name: REQUIRED - Specific marketplace name (e.g., "Dubti", "Bati", "Semera")
                         Must be explicitly mentioned by user, not assumed.
    
    Returns:
        Price information or error message if marketplace/livestock not found
    """
    logger.info(f"get_livestock_price_quick: livestock={livestock_type}, marketplace={marketplace_name}")
    
    # Validate parameters - check for vague/generic inputs
    vague_terms = ['livestock', 'animal', 'it', 'that', 'this', 'something', 'anything', 'price', 'market', 'the market']
    
    livestock_lower = livestock_type.lower().strip()
    market_lower = marketplace_name.lower().strip()
    
    if livestock_lower in vague_terms or len(livestock_lower) < 2:
        return "ERROR: I need to know which specific livestock type you're asking about. Please tell me the livestock type (e.g., cattle, goat, sheep, oxen)."
    
    if market_lower in vague_terms or len(market_lower) < 3:
        return "ERROR: I need to know which specific marketplace you're asking about. Please tell me the marketplace name (e.g., Dubti, Bati, Semera)."
    
    # Normalize livestock type - handle common plural/singular variations
    livestock_normalized = livestock_lower
    plural_to_singular = {
        'oxen': 'ox',
        'cattle': 'cow',  
        'sheep': 'sheep',  
        'goats': 'goat',
        'camels': 'camel',
        'calves': 'calf',
        'cows': 'cow',
    }
    
    # Try to normalize to singular form for better matching
    if livestock_normalized in plural_to_singular:
        livestock_normalized = plural_to_singular[livestock_normalized]
        logger.info(f"Normalized '{livestock_type}' to '{livestock_normalized}' for better matching")
    
    # Import here to avoid circular imports
    from helpers.market_place_json import EXACT_MATCH_UP_LIVESTOCK_MARKETPLACES
    
    # Find marketplace with case-insensitive and fuzzy matching
    marketplace_info = None
    name_lower = marketplace_name.lower().strip()
    clean_name = name_lower.replace(" market", "").replace(" gebeya", "").replace(" city", "").strip()
    
    # Try exact match first
    marketplace_info = EXACT_MATCH_UP_LIVESTOCK_MARKETPLACES.get(marketplace_name)
    
    # If not found, try fuzzy matching with difflib
    if not marketplace_info:
        import difflib
        
        # Create a mapping of clean names to original keys for better matching
        # key_map maps lowercase clean name -> original key
        key_map = {}
        all_keys = []
        
        for key in EXACT_MATCH_UP_LIVESTOCK_MARKETPLACES.keys():
            all_keys.append(key)
            # Add cleaned versions to improve matching chances
            key_clean = key.lower().replace(" market", "").replace(" gebeya", "").replace(" city", "").strip()
            if key_clean not in key_map:
                key_map[key_clean] = key
        
        # 1. Try matching against the full keys
        matches = difflib.get_close_matches(name_lower, [k.lower() for k in all_keys], n=1, cutoff=0.7)
        
        if matches:
            # Find the original key that matches this lowercase match
            matched_lower = matches[0]
            for key in all_keys:
                if key.lower() == matched_lower:
                    marketplace_name = key
                    marketplace_info = EXACT_MATCH_UP_LIVESTOCK_MARKETPLACES[key]
                    logger.info(f"Fuzzy matched '{name_lower}' to '{key}' (score via direct match)")
                    break
        
        # 2. If no match yet, try matching against cleaned names (often better for user inputs)
        if not marketplace_info:
            clean_input = name_lower.replace(" market", "").replace(" gebeya", "").replace(" city", "").strip()
            clean_matches = difflib.get_close_matches(clean_input, list(key_map.keys()), n=1, cutoff=0.6)
            
            if clean_matches:
                best_clean_match = clean_matches[0]
                original_key = key_map[best_clean_match]
                marketplace_name = original_key
                marketplace_info = EXACT_MATCH_UP_LIVESTOCK_MARKETPLACES[original_key]
                logger.info(f"Fuzzy matched '{clean_input}' to '{original_key}' (via clean name)")
    
    if not marketplace_info:
        logger.info(f"get_livestock_price_quick: marketplace not found")
        return f"Livestock marketplace '{marketplace_name}' not found. Please check the marketplace name."
    
    region = marketplace_info.get("region")
    
    async with async_session_maker() as db:
        # Get marketplace using the helper function
        marketplace, error = await _get_marketplace(db, marketplace_name, region)
        logger.debug(f"Getting marketplace: region={region}, marketplace={marketplace_name}")
        
        if error:
            logger.info(f"get_livestock_price_quick: {error}")
            return f"Marketplace '{marketplace_name}' not found in database."

        # Get price info - use normalized livestock name for better matching
        stmt = (
            select(
                MarketPrice.min_price,
                MarketPrice.max_price,
                MarketPrice.avg_price,
                MarketPrice.modal_price,
                MarketPrice.price_date,
                MarketPrice.unit,
                Livestock.name_amharic.label('livestock_name_amharic'),
                Livestock.name.label('livestock_name'),
                LivestockBreed.name.label('breed_name'),
                LivestockBreed.name_amharic.label('breed_name_amharic')
            )
            .join(Livestock, MarketPrice.livestock_id == Livestock.livestock_id)
            .outerjoin(LivestockBreed, MarketPrice.breed_id == LivestockBreed.breed_id)
            .where(
                MarketPrice.marketplace_id == marketplace.marketplace_id,
                or_(
                    func.lower(Livestock.name) == livestock_normalized,
                    func.lower(Livestock.name).contains(livestock_normalized),
                    func.lower(Livestock.name_amharic) == livestock_normalized,
                    func.lower(Livestock.name_amharic).contains(livestock_normalized)
                ),
                MarketPrice.price_date >= (func.current_date() - 364)
            )
            .order_by(MarketPrice.price_date.desc())
        )
        result = await db.execute(stmt)
        price_data_list = result.all()

        if not price_data_list:
            logger.info(f"get_livestock_price_quick: no price data")
            return f"No price data found for '{livestock_type}' in {marketplace_name} ({region})."

        price_data_breeds = {}
        for price_row in price_data_list:
            breed_key = price_row.breed_name or "Default"
            price_data_breeds[breed_key] = (
                f"{price_row.livestock_name} ({price_row.livestock_name_amharic}) prices in {marketplace_name} ({region}):\n\n"
                f"* Breed: {price_row.breed_name or 'N/A'}" +
                (f" ({price_row.breed_name_amharic})" if price_row.breed_name_amharic else "") + "\n"
                f"* Min Price: {price_row.min_price} ETB/{price_row.unit or 'Head'}\n"
                f"* Max Price: {price_row.max_price} ETB/{price_row.unit or 'Head'}\n"
                f"* Avg Price: {price_row.avg_price} ETB/{price_row.unit or 'Head'}\n"
                f"* Modal Price: {price_row.modal_price} ETB/{price_row.unit or 'Head'}\n"
                f"* Date: {price_row.price_date.strftime('%Y-%m-%d')}\n"
                f"* Source: https://nmis.et/"
            )
        
        logger.info(f"get_livestock_price_quick: found {len(price_data_breeds)} breeds")
        
        # Format response
        return "\n\n".join(price_data_breeds.values())
