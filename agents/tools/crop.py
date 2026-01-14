# agents/tools/crop.py
from pydantic_ai import RunContext
from agents.deps import FarmerContext
from app.database import get_db_session
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.market import Crop, CropVariety, MarketPrice, Marketplace
from typing import List, Optional

from sqlalchemy.orm import joinedload

from helpers.utils import get_logger
logger = get_logger(__name__)


async def _get_marketplace_id(
    db: AsyncSession,
    marketplace_name: str,
    region: str
) -> Optional[int]:
    """Internal helper to get marketplace_id"""
    logger.debug(f"Getting marketplace ID: region={region}, marketplace={marketplace_name}")
    stmt = select(Marketplace.marketplace_id).where(
        or_(
            func.lower(Marketplace.name) == func.lower(f"{region.lower()} - {marketplace_name.lower()}"),
            func.lower(Marketplace.name_amharic) == func.lower(f"{region.lower()} - {marketplace_name.lower()}"),
        ),
        func.lower(Marketplace.region) == func.lower(region),
        Marketplace.is_active == True
    )
    logger.debug(f"Query from _get_marketplace_id: {stmt}")
    result = await db.execute(stmt)
    matches = result.all()
    
    if not matches:
        return None
    
    if len(matches) == 1:
        return matches[0].marketplace_id
    
    # Multiple matches - try exact word match
    for match in matches:
        name_words = set(match.name.lower().split())
        search_words = set(marketplace_name.lower().split())

        # Check if all search words are present in name words
        if search_words.issubset(name_words):
            return match.marketplace_id
    
    # Fallback: return first match
    logger.warning(
        f"Multiple matches for '{marketplace_name}' in {region}: "
        f"{[m.name for m in matches]}. Using first match."
    )
    return matches[0].marketplace_id


async def list_crops_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    region: str
) -> str:
    """
    List all crops available in a specific marketplace.
    
    Args:
        marketplace_name: Name of the marketplace (e.g., "Merkato", "Yaye market")
        region: Region name (e.g., "Amhara", "Oromia", "Sidama")
    
    Returns:
        Formatted list of available crops with Amharic names
    """
    logger.info(f"list_crops_in_marketplace: marketplace={marketplace_name}, region={region}")
    async with get_db_session() as db:
        # Get marketplace ID
        logger.debug(f"list_crops_in_marketplace: marketplace={marketplace_name}, region={region}")
        marketplace_id = await _get_marketplace_id(db, marketplace_name, region)
        logger.debug(f"Marketplace ID from list_crops_in_marketplace: {marketplace_id}")
        if not marketplace_id:
            return f"Marketplace '{marketplace_name}' not found in {region} region."

        # Get crops with their varieties
        stmt = (
            select(Crop)
            .join(MarketPrice, MarketPrice.crop_id == Crop.crop_id)
            .where(MarketPrice.marketplace_id == marketplace_id)
            .where(MarketPrice.price_date >= (func.current_date() - 364))
            .where(Crop.category == "agricultural")
            .options(joinedload(Crop.varieties))
            .distinct()
            .order_by(Crop.name)
        )
        result = await db.execute(stmt)
        crops = result.scalars().unique().all()

        if not crops:
            return f"No crops found in {marketplace_name} marketplace."

        crop_list = [
            f"• {crop.name}" +
            (f" ({crop.name_amharic})" if crop.name_amharic else "") +
            (f" ({', '.join([v.name for v in crop.varieties])})" if crop.varieties else " (No varieties)") +
            f"   • Source: https://nmis.et/"
            for crop in crops
        ]
        logger.info(f"list_crops_in_marketplace result: {crop_list}")
        return (
            f" Crops available in {marketplace_name} ({region}):\n\n" +
            "\n".join(crop_list)
        )


async def get_crop_price_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    region: str,
    crop_name: str
) -> str:
    """
    Always use the list_crops_in_marketplace(marketplace_name, region), before using this Tool.
    Get latest price information for a specific crop in a marketplace.
    
    Args:
        marketplace_name: Name of the marketplace
        region: Region name
        crop_name: Name of the crop (e.g., "Teff", "Wheat", "Barley")
    
    Returns:
        Formatted price information with date
    """
    logger.info(f"get_crop_price_in_marketplace: crop={crop_name}, marketplace={marketplace_name}, region={region}")
    async with get_db_session() as db:
        # Get marketplace ID
        marketplace_id = await _get_marketplace_id(db, marketplace_name, region)
        logger.debug(f"get_crop_price: marketplace_id={marketplace_id}, marketplace={marketplace_name}, region={region}")
        if not marketplace_id:
            return f"Marketplace '{marketplace_name}' not found in {region} region."

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
            .join(CropVariety, MarketPrice.variety_id == CropVariety.variety_id)
            .where(
                MarketPrice.marketplace_id == marketplace_id,
                or_(
                    func.lower(Crop.name) == crop_name.lower(),
                    func.lower(CropVariety.name) == crop_name.lower(),
                    func.lower(Crop.name).contains(crop_name.lower()),
                    func.lower(CropVariety.name).contains(crop_name.lower()),
                    func.lower(Crop.name_amharic) == crop_name.lower(),
                    func.lower(CropVariety.name_amharic) == crop_name.lower(),
                    func.lower(Crop.name_amharic).contains(crop_name.lower()),
                    func.lower(CropVariety.name_amharic).contains(crop_name.lower())
                ),
                MarketPrice.price_date >= (func.current_date() - 364),
                Crop.category == "agricultural"
            )
            .order_by(MarketPrice.price_date.desc())
        )
        result = await db.execute(stmt)
        price_data_list = result.all()

        if not price_data_list:
            return f"No price data found for '{crop_name}' in {marketplace_name}."

        price_data_varieties = {}
        for price_row in price_data_list:
            price_data_varieties[price_row.variety_name] = (
            f" {price_row.crop_name} ({price_row.crop_name_amharic}) prices in {marketplace_name}:\n\n"
            f"• Variety: {price_row.variety_name} ({price_row.variety_name_amharic})\n"
            f"• Min Price: {price_row.min_price} ETB/{price_row.unit}\n"
            f"• Max Price: {price_row.max_price} ETB/{price_row.unit}\n"
            f"• Avg Price: {price_row.avg_price} ETB/{price_row.unit}\n"
            f"• Modal Price: {price_row.modal_price} ETB/{price_row.unit}\n"
            f"• Date: {price_row.price_date.strftime('%Y-%m-%d')}\n"
            f"• Source: https://nmis.et/"
        )
        logger.info(f"get_crop_price_in_marketplace result: {price_data_varieties}")
        # Format response
        return "\n\n".join(price_data_varieties.values())



async def compare_crop_prices_nearby(
    ctx: RunContext[FarmerContext],
    region: str,
    marketplace_names: List[str],
    crop_name: str,
) -> str:
    """
    Compare prices of a crop across multiple marketplaces in a region.
    
    Args:
        region: Region to search in
        marketplace_names: List of marketplace names to include in comparison
        crop_name: Crop to compare
        
    
    Returns:
        Formatted comparison of prices across markets
    """
    logger.info(f"compare_crop_prices_nearby: crop={crop_name}, region={region}, marketplaces={marketplace_names}")
    if not marketplace_names:
        return "No marketplaces provided for comparison."
    async with get_db_session() as db:
        # Get all marketplaces in region
        stmt = (
            select(
                Marketplace.name,
                MarketPrice.min_price,
                MarketPrice.max_price,
                MarketPrice.avg_price,
                MarketPrice.modal_price,
                MarketPrice.price_date,
                MarketPrice.unit,
                Crop.name.label('crop_name'),
                CropVariety.name.label('variety_name')
            )
            .join(MarketPrice, MarketPrice.marketplace_id == Marketplace.marketplace_id)
            .join(Crop, MarketPrice.crop_id == Crop.crop_id)
            .join(CropVariety, MarketPrice.variety_id == CropVariety.variety_id)
            .where(
                or_(Marketplace.region == region,
                    Marketplace.region_amharic == region),
                Marketplace.is_active == True,
                or_(func.lower(Crop.name) == func.lower(crop_name),
                    func.lower(CropVariety.name) == func.lower(crop_name),
                    func.lower(Crop.name).contains(func.lower(crop_name)),
                    func.lower(CropVariety.name).contains(func.lower(crop_name)),
                    func.lower(Crop.name_amharic) == func.lower(crop_name),
                    func.lower(CropVariety.name_amharic) == func.lower(crop_name),
                    func.lower(Crop.name_amharic).contains(func.lower(crop_name)),
                    func.lower(CropVariety.name_amharic).contains(func.lower(crop_name))
                ),
                Crop.category == "agricultural"
            )
            .where(MarketPrice.price_date >= (func.current_date() - 364))  # Last 7 days
            .where(
                or_(Marketplace.name.in_(marketplace_names),
                    Marketplace.name_amharic.in_(marketplace_names))
            )
            .order_by(MarketPrice.avg_price.asc())
        )
        result = await db.execute(stmt)
        markets = result.all()

        if not markets:
            return f"No price data found for '{crop_name}' in {region} region."

        # Format response
        lines = [f" {crop_name} price comparison in {region}:\n"]

        for idx, market in enumerate(markets, 1):
            lines.append(
                f"{idx}. **{market.name}**\n"
                f"   • Avg: {market.avg_price} ETB/{market.unit}\n"
                f"   • Range: {market.min_price} - {market.max_price} ETB\n"
                f"   • Date: {market.price_date.strftime('%Y-%m-%d')}\n"
                f"   • Source: https://nmis.et/"
            )
        logger.info(f"compare_crop_prices_nearby result: {lines}")
        return "\n\n".join(lines)