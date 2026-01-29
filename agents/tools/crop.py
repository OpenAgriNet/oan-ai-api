# agents/tools/crop.py
from pydantic_ai import RunContext
from agents.deps import FarmerContext
from app.database import async_session_maker
from sqlalchemy import func, or_, select, literal
from app.models.market import Crop, CropVariety, MarketPrice, Marketplace
from typing import List, Optional, Tuple, Union
from sqlalchemy.orm import joinedload
from helpers.utils import get_logger, log_execution_time

logger = get_logger(__name__)


async def _get_marketplace(
    db,
    marketplace_name: str,
    region: Optional[str] = None
) -> Tuple[Optional[Marketplace], Optional[str]]:

    """
    Internal helper to get marketplace by name, optionally filtered by region.

    Returns:
        Tuple of (marketplace, error_message)
        - (Marketplace, None) if found
        - (None, error_message) if not found or ambiguous
    """
    stmt = select(Marketplace).where(
        Marketplace.marketplace_type == "crop",
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


@log_execution_time
async def list_crops_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    region: Optional[str] = None
) -> str:
    """
    List all crops available in a specific marketplace.

    Args:
        marketplace_name: Name of the marketplace (e.g., "Merkato", "Yaye market")
        region: Optional region name to disambiguate if same marketplace name exists in multiple regions

    Returns:
        Formatted list of available crops with Amharic names
    """
    logger.info(f"list_crops_in_marketplace: marketplace={marketplace_name}, region={region}")

    async with async_session_maker() as db:
        marketplace, error = await _get_marketplace(db, marketplace_name, region)
        if error:
            return error

        stmt = (
            select(Crop)
            .join(MarketPrice, MarketPrice.crop_id == Crop.crop_id)
            .where(MarketPrice.marketplace_id == marketplace.marketplace_id)
            .where(MarketPrice.price_date >= (func.current_date() - 364))
            .where(Crop.category == "agricultural")
            .options(joinedload(Crop.varieties))
            .distinct()
            .order_by(Crop.name)
        )
        result = await db.execute(stmt)
        crops = result.scalars().unique().all()

        if not crops:
            return f"No crops found in {marketplace.name} marketplace."

        crop_list = [
            f"* {crop.name}" +
            (f" ({crop.name_amharic})" if crop.name_amharic else "") +
            (f" - Varieties: {', '.join([v.name for v in crop.varieties])}" if crop.varieties else "") +
            f"\n  Source: https://nmis.et/"
            for crop in crops
        ]

        return (
            f"Crops available in {marketplace.name} ({marketplace.region}):\n\n" +
            "\n".join(crop_list)
        )


@log_execution_time
async def get_crop_price_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    crop_name: str,
    region: Optional[str] = None
) -> str:
    """
    Get detailed price information for a specific crop in a marketplace.
    
    ⚠️ NOTE: Use get_crop_price_quick() instead for faster results.
    Only use this tool if get_crop_price_quick() fails or you need to verify data.
    
    Args:
        marketplace_name: Name of the marketplace
        crop_name: Name of the crop (e.g., "Teff", "Wheat", "Barley")
        region: Optional region name to disambiguate if same marketplace name exists in multiple regions

    Returns:
        Formatted price information with date
    """
    logger.info(f"get_crop_price_in_marketplace: crop={crop_name}, marketplace={marketplace_name}, region={region}")

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
                Crop.name_amharic.label('crop_name_amharic'),
                Crop.name.label('crop_name'),
                CropVariety.name.label('variety_name'),
                CropVariety.name_amharic.label('variety_name_amharic')
            )
            .join(Crop, MarketPrice.crop_id == Crop.crop_id)
            .outerjoin(CropVariety, MarketPrice.variety_id == CropVariety.variety_id)
            .where(
                MarketPrice.marketplace_id == marketplace.marketplace_id,
                or_(
                    func.lower(Crop.name) == crop_name.lower(),
                    func.lower(Crop.name).contains(crop_name.lower()),
                    func.lower(Crop.name_amharic) == crop_name.lower(),
                    func.lower(Crop.name_amharic).contains(crop_name.lower()),
                    # Add Variety Search to handle specific queries like "White Teff"
                    func.lower(CropVariety.name) == crop_name.lower(),
                    func.lower(CropVariety.name).contains(crop_name.lower()),
                    func.lower(CropVariety.name_amharic) == crop_name.lower(),
                    func.lower(CropVariety.name_amharic).contains(crop_name.lower()),
                    # Inverted: Query contains Crop/Variety Name. Use strpos > 0
                    func.strpos(literal(crop_name.lower()), func.lower(Crop.name)) > 0,
                    func.strpos(literal(crop_name.lower()), func.lower(Crop.name_amharic)) > 0
                ),
                MarketPrice.price_date >= (func.current_date() - 364),
                Crop.category == "agricultural"
            )
            .order_by(MarketPrice.price_date.desc())
        )
        result = await db.execute(stmt)
        price_data_list = result.all()

        if not price_data_list:
            return f"No price data found for '{crop_name}' in {marketplace.name}."

        price_data_varieties = {}
        for price_row in price_data_list:
            variety_key = price_row.variety_name or "Default"
            price_data_varieties[variety_key] = (
                f"{price_row.crop_name} ({price_row.crop_name_amharic}) prices in {marketplace.name}:\n\n"
                f"* Variety: {price_row.variety_name or 'N/A'}" +
                (f" ({price_row.variety_name_amharic})" if price_row.variety_name_amharic else "") + "\n"
                f"* Min Price: {price_row.min_price} ETB/{price_row.unit or 'unit'}\n"
                f"* Max Price: {price_row.max_price} ETB/{price_row.unit or 'unit'}\n"
                f"* Avg Price: {price_row.avg_price} ETB/{price_row.unit or 'unit'}\n"
                f"* Date: {price_row.price_date.strftime('%Y-%m-%d')}\n"
                f"* Source: https://nmis.et/"
            )

        result_str = "\n\n".join(price_data_varieties.values())
        logger.info(f"💰 Tool Result for {marketplace.name}/{crop_name}: {result_str[:100]}...")
        return result_str


@log_execution_time
async def compare_crop_prices_nearby(
    ctx: RunContext[FarmerContext],
    marketplace_names: List[str],
    crop_name: str,
) -> str:
    """
    Compare prices of a crop across multiple marketplaces.

    Args:
        marketplace_names: List of marketplace names to compare
        crop_name: Crop to compare

    Returns:
        Formatted comparison of prices across markets
    """
    logger.info(f"compare_crop_prices_nearby: crop={crop_name}, marketplaces={marketplace_names}")

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
                Crop.name.label('crop_name'),
                CropVariety.name.label('variety_name')
            )
            .join(MarketPrice, MarketPrice.marketplace_id == Marketplace.marketplace_id)
            .join(Crop, MarketPrice.crop_id == Crop.crop_id)
            .outerjoin(CropVariety, MarketPrice.variety_id == CropVariety.variety_id)
            .where(
                Marketplace.marketplace_type == "crop",
                Marketplace.is_active == True,
                or_(
                    func.lower(Crop.name) == func.lower(crop_name),
                    func.lower(Crop.name).contains(func.lower(crop_name)),
                    func.lower(Crop.name_amharic) == func.lower(crop_name),
                    func.lower(Crop.name_amharic).contains(func.lower(crop_name))
                ),
                Crop.category == "agricultural",
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
            return f"No price data found for '{crop_name}' in the specified marketplaces."

        lines = [f"{crop_name} price comparison:\n"]

        for idx, market in enumerate(markets, 1):
            lines.append(
                f"{idx}. **{market.name}** ({market.region})\n"
                f"   * Avg: {market.avg_price} ETB/{market.unit or 'unit'}\n"
                f"   * Range: {market.min_price} - {market.max_price} ETB\n"
                f"   * Date: {market.price_date.strftime('%Y-%m-%d')}\n"
                f"   * Source: https://nmis.et/"
            )

        return "\n\n".join(lines)


@log_execution_time
async def get_crop_price_quick(
    ctx: RunContext[FarmerContext],
    crop_name: str,
    marketplace_name: str
) -> str:
    """
    Get crop price by marketplace name directly - no region needed. FAST VERSION.
    
    CRITICAL: Only call this tool if BOTH parameters are clearly specified by the user.
    DO NOT call this tool if:
    - User didn't mention a specific crop name
    - User didn't mention a specific marketplace name
    - User said vague things like "the crop" or "the price"
    
    If information is missing, ASK the user for it instead of calling this tool.
    
    Args:
        crop_name: REQUIRED - Specific crop name (e.g., "Wheat", "Teff", "Barley")
                   Must be explicitly mentioned by user, not assumed.
        marketplace_name: REQUIRED - Specific marketplace name (e.g., "Amber", "Merkato")
                         Must be explicitly mentioned by user, not assumed.
    
    Returns:
        Price information or error message if marketplace/crop not found
    """
    logger.info(f"get_crop_price_quick: crop={repr(crop_name)}, marketplace={repr(marketplace_name)}")
    
    # Defensive trimming
    crop_name = crop_name.strip()
    marketplace_name = marketplace_name.strip()

    # Validate parameters - check for vague/generic inputs
    vague_terms = ['crop', 'the crop', 'it', 'that', 'this', 'something', 'anything', 'price', 'market', 'the market']
    
    crop_lower = crop_name.lower()
    market_lower = marketplace_name.lower()
    
    if crop_lower in vague_terms or len(crop_lower) < 3:
        return "ERROR: I need to know which specific crop you're asking about. Please tell me the crop name (e.g., wheat, teff, barley)."
    
    if market_lower in vague_terms or len(market_lower) < 3:
        return "ERROR: I need to know which specific marketplace you're asking about. Please tell me the marketplace name (e.g., Amber, Merkato, Piassa)."
    
    # Import here to avoid circular imports
    from helpers.market_place_json import EXACT_MATCH_UP_MARKETPLACES
    
    # Find marketplace with case-insensitive and fuzzy matching
    marketplace_info = None
    name_lower = marketplace_name.lower().strip()
    clean_name = name_lower.replace(" market", "").replace(" gebeya", "").replace(" city", "").strip()
    
    # Try exact match first
    marketplace_info = EXACT_MATCH_UP_MARKETPLACES.get(marketplace_name)
    
    # If not found, try fuzzy matching with difflib
    if not marketplace_info:
        import difflib
        
        # Create a mapping of clean names to original keys for better matching
        # key_map maps lowercase clean name -> original key
        key_map = {}
        all_keys = []
        
        for key in EXACT_MATCH_UP_MARKETPLACES.keys():
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
                    marketplace_info = EXACT_MATCH_UP_MARKETPLACES[key]
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
                marketplace_info = EXACT_MATCH_UP_MARKETPLACES[original_key]
                logger.info(f"Fuzzy matched '{clean_input}' to '{original_key}' (via clean name)")
    
    if not marketplace_info:
        logger.info(f"get_crop_price_quick: marketplace not found - marketplace_info is None")
        return f"Marketplace '{marketplace_name}' not found. Please check the marketplace name."
    
    region = marketplace_info.get("region")
    
    async with async_session_maker() as db:
        # Get marketplace using the helper function
        marketplace, error = await _get_marketplace(db, marketplace_name, region)
        if error:
            logger.info(f"get_crop_price_quick: {error}")
            return f"Marketplace '{marketplace_name}' not found in database."

        # Get price info
        stmt = (
            select(
                MarketPrice.min_price,
                MarketPrice.max_price,
                MarketPrice.avg_price,
                MarketPrice.modal_price,
                MarketPrice.price_date,
                MarketPrice.unit,
                Crop.name_amharic.label('crop_name_amharic'),
                Crop.name.label('crop_name'),
                CropVariety.name.label('variety_name'),
                CropVariety.name_amharic.label('variety_name_amharic')
            )
            .join(Crop, MarketPrice.crop_id == Crop.crop_id)
            .outerjoin(CropVariety, MarketPrice.variety_id == CropVariety.variety_id)
            .where(
                MarketPrice.marketplace_id == marketplace.marketplace_id,
                or_(
                    func.lower(Crop.name) == crop_name.lower(),
                    func.lower(Crop.name).contains(crop_name.lower()),
                    func.lower(Crop.name_amharic) == crop_name.lower(),
                    func.lower(Crop.name_amharic).contains(crop_name.lower())
                ),
                MarketPrice.price_date >= (func.current_date() - 364),
                Crop.category == "agricultural"
            )
            .order_by(MarketPrice.price_date.desc())
        )
        result = await db.execute(stmt)
        price_data_list = result.all()

        if not price_data_list and region:
            logger.info(f"get_crop_price_quick: no price data with region='{region}'. Retrying without region...")
            # Fallback: Try getting marketplace without region constraint
            marketplace, error = await _get_marketplace(db, marketplace_name, None)
            if not error and marketplace:
                 # Re-run query with new marketplace ID
                 # We need to rebuild the statement because marketplace.marketplace_id changed
                 stmt = (
                    select(
                        MarketPrice.min_price,
                        MarketPrice.max_price,
                        MarketPrice.avg_price,
                        MarketPrice.modal_price,
                        MarketPrice.price_date,
                        MarketPrice.unit,
                        Crop.name_amharic.label('crop_name_amharic'),
                        Crop.name.label('crop_name'),
                        CropVariety.name.label('variety_name'),
                        CropVariety.name_amharic.label('variety_name_amharic')
                    )
                    .join(Crop, MarketPrice.crop_id == Crop.crop_id)
                    .outerjoin(CropVariety, MarketPrice.variety_id == CropVariety.variety_id)
                    .where(
                        MarketPrice.marketplace_id == marketplace.marketplace_id,
                        or_(
                            func.lower(Crop.name) == crop_name.lower(),
                            func.lower(Crop.name).contains(crop_name.lower()),
                            func.lower(Crop.name_amharic) == crop_name.lower(),
                            func.lower(Crop.name_amharic).contains(crop_name.lower())
                        ),
                        MarketPrice.price_date >= (func.current_date() - 364),
                        Crop.category == "agricultural"
                    )
                    .order_by(MarketPrice.price_date.desc())
                )
                 result = await db.execute(stmt)
                 price_data_list = result.all()

        if not price_data_list:
            logger.info(f"get_crop_price_quick: no price data (fallback included)")
            return f"No price data found for '{crop_name}' in {marketplace_name}."

        price_data_varieties = {}
        for price_row in price_data_list:
            variety_key = price_row.variety_name or "Default"
            price_data_varieties[variety_key] = (
                f"{price_row.crop_name} ({price_row.crop_name_amharic}) prices in {marketplace_name} ({region}):\n\n"
                f"* Variety: {price_row.variety_name or 'N/A'}" +
                (f" ({price_row.variety_name_amharic})" if price_row.variety_name_amharic else "") + "\n"
                f"* Min Price: {price_row.min_price} ETB/{price_row.unit or 'unit'}\n"
                f"* Max Price: {price_row.max_price} ETB/{price_row.unit or 'unit'}\n"
                f"* Avg Price: {price_row.avg_price} ETB/{price_row.unit or 'unit'}\n"
                f"* Modal Price: {price_row.modal_price} ETB/{price_row.unit or 'unit'}\n"
                f"* Date: {price_row.price_date.strftime('%Y-%m-%d')}\n"
                f"* Source: https://nmis.et/"
            )
        
        logger.info(f"get_crop_price_quick: found {len(price_data_varieties)} varieties")
        return "\n\n".join(price_data_varieties.values())
