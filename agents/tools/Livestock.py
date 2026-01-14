from pydantic_ai import RunContext
from app.models.market import Livestock, LivestockBreed, MarketPrice, Marketplace
from agents.tools.crop import _get_marketplace_id
from agents.deps import FarmerContext
from app.database import get_db_session
from sqlalchemy import func, select, or_
from typing import List
from sqlalchemy.orm import joinedload
from helpers.utils import get_logger
logger = get_logger(__name__)


async def list_livestock_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    region: str
) -> str:
    """
    List all livestock types available in a specific livestock marketplace.
    
    Args:
        marketplace_name: Name of the livestock marketplace (e.g., "Addis Ababa Livestock Market")
        region: Region name (e.g., "Oromia", "Afar")
    
    Returns:
        Formatted list of available livestock with Amharic names
    """
    logger.info(f"list_livestock_in_marketplace: marketplace={marketplace_name}, region={region}")
    async with get_db_session() as db:
        # Get marketplace ID
        logger.debug(f"list_livestock_in_marketplace: marketplace={marketplace_name}, region={region}")
        marketplace_id = await _get_marketplace_id(db, marketplace_name, region)
        logger.debug(f"Marketplace ID from list_livestock_in_marketplace: {marketplace_id}")
        if not marketplace_id:
            return f"Marketplace '{marketplace_name}' not found in {region} region."

        # Get livestock with their breeds
        stmt = (
            select(Livestock)
            .join(MarketPrice, MarketPrice.livestock_id == Livestock.livestock_id)
            .where(MarketPrice.marketplace_id == marketplace_id)
            .where(MarketPrice.price_date >= (func.current_date() - 364))
            .options(joinedload(Livestock.breeds))
            .distinct()
            .order_by(Livestock.name)
        )
        result = await db.execute(stmt)
        livestocks = result.scalars().unique().all()

        if not livestocks:
            return f"No livestock found in {marketplace_name} marketplace."

        livestock_list = [
            f"• {livestock.name}" +
            (f" ({livestock.name_amharic})" if livestock.name_amharic else "") +
            (f" ({', '.join([b.name for b in livestock.breeds])})" if livestock.breeds else " (No breeds)") +
            f"   • Source: https://nmis.et/"

            for livestock in livestocks
        ]
        logger.info(f"list_livestock_in_marketplace result: {livestock_list}")
        return (
            f"📦 livestocks available in {marketplace_name} ({region}):\n\n" +
            "\n".join(livestock_list)
        )


async def get_livestock_price_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    region: str,
    livestock_type: str
) -> str:
    """
    Always use the list_livestock_in_marketplace(marketplace_name, region), before using this Tool.
    Get latest price information for a specific livestock type in a marketplace.
    
    Args:
        marketplace_name: Name of the livestock marketplace
        region: Region name
        livestock_type: Type of livestock (e.g., "Cattle", "Goat", "Sheep")
    
    Returns:
        Formatted price information with date
    """
    logger.info(f"get_livestock_price_in_marketplace: livestock={livestock_type}, marketplace={marketplace_name}, region={region}")
    async with get_db_session() as db:
        # Get marketplace ID
        marketplace_id = await _get_marketplace_id(db, marketplace_name, region)
        logger.debug(f"get_livestock_price: marketplace_id={marketplace_id}, marketplace={marketplace_name}, region={region}")
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
                Livestock.name_amharic.label('livestock_name_amharic'),
                Livestock.name.label('livestock_name'),
                LivestockBreed.name.label('breed_name'),
                LivestockBreed.name_amharic.label('breed_name_amharic')
            )
            .join(Livestock, MarketPrice.livestock_id == Livestock.livestock_id)
            .join(LivestockBreed, MarketPrice.breed_id == LivestockBreed.breed_id)
            .where(
                MarketPrice.marketplace_id == marketplace_id,
                or_(
                    func.lower(Livestock.name) == livestock_type.lower(),
                    func.lower(LivestockBreed.name) == livestock_type.lower(),
                    func.lower(Livestock.name).contains(livestock_type.lower()),
                    func.lower(LivestockBreed.name).contains(livestock_type.lower()),
                    func.lower(Livestock.name_amharic) == livestock_type.lower(),
                    func.lower(LivestockBreed.name_amharic) == livestock_type.lower(),
                    func.lower(Livestock.name_amharic).contains(livestock_type.lower()),
                    func.lower(LivestockBreed.name_amharic).contains(livestock_type.lower())
                ),
                MarketPrice.price_date >= (func.current_date() - 364)
            )
            .order_by(MarketPrice.price_date.desc())
        )
        result = await db.execute(stmt)
        price_data_list = result.all()

        if not price_data_list:
            return f"No price data found for '{livestock_type}' in {marketplace_name}."

        price_data_breeds = {}
        for price_row in price_data_list:
            price_data_breeds[price_row.breed_name] = (
            f"💰 {price_row.livestock_name} ({price_row.livestock_name_amharic}) prices in {marketplace_name}:\n\n"
            f"• Breed: {price_row.breed_name} ({price_row.breed_name_amharic})\n"
            f"• Min Price: {price_row.min_price} ETB/{price_row.unit}\n"
            f"• Max Price: {price_row.max_price} ETB/{price_row.unit}\n"
            f"• Avg Price: {price_row.avg_price} ETB/{price_row.unit}\n"
            f"• Modal Price: {price_row.modal_price} ETB/{price_row.unit}\n"
            f"• Date: {price_row.price_date.strftime('%Y-%m-%d')}\n"
            f"• Source: https://nmis.et/"
        )
        logger.info(f"get_livestock_price_in_marketplace result: {price_data_breeds}")
        # Format response
        return "\n\n".join(price_data_breeds.values())



async def compare_livestock_prices_nearby(
    ctx: RunContext[FarmerContext],
    region: str,
    livestock_type: str,
    marketplace_names: List[str],
) -> str:
    """
    Compare prices of a livestock type across multiple marketplaces in a region.
    
    Args:
        region: Region to search in
        livestock_type: Livestock type to compare (e.g., "Cattle", "Goat")
        max_markets: Maximum number of markets to compare (default 5)
    
    Returns:
        Formatted comparison of prices across markets
    """
    logger.info(f"compare_livestock_prices_nearby: livestock={livestock_type}, region={region}, marketplaces={marketplace_names}")
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
                Livestock.name.label('livestock_name'),
                LivestockBreed.name.label('breed_name')
            )
            .join(MarketPrice, MarketPrice.marketplace_id == Marketplace.marketplace_id)
            .join(Livestock, MarketPrice.livestock_id == Livestock.livestock_id)
            .join(LivestockBreed, MarketPrice.breed_id == LivestockBreed.breed_id)
            .where(
                or_(
                    Marketplace.region == region,
                    Marketplace.region_amharic == region
                ),
                Marketplace.is_active == True,
                or_(
                    func.lower(Livestock.name) == livestock_type.lower(),
                    func.lower(LivestockBreed.name) == livestock_type.lower(),
                    func.lower(Livestock.name).contains(livestock_type.lower()),
                    func.lower(LivestockBreed.name).contains(livestock_type.lower()),
                    func.lower(Livestock.name_amharic) == livestock_type.lower(),
                    func.lower(LivestockBreed.name_amharic) == livestock_type.lower(),
                    func.lower(Livestock.name_amharic).contains(livestock_type.lower()),
                    func.lower(LivestockBreed.name_amharic).contains(livestock_type.lower())
                )
            )
            .where(MarketPrice.price_date >= (func.current_date() - 364))  # Last 7 days
            .where(or_(
                Marketplace.name.in_(marketplace_names),
                Marketplace.name_amharic.in_(marketplace_names)
            ))
            .order_by(MarketPrice.avg_price.asc())
        )
        result = await db.execute(stmt)
        markets = result.all()

        if not markets:
            return f"No price data found for '{livestock_type}' in {region} region."

        # Format response
        lines = [f"💰 {livestock_type} price comparison in {region}:\n"]

        for idx, market in enumerate(markets, 1):
            lines.append(
                f"{idx}. **{market.name}**\n"
                f"   • Avg: {market.avg_price} ETB/{market.unit}\n"
                f"   • Range: {market.min_price} - {market.max_price} ETB\n"
                f"   • Date: {market.price_date.strftime('%Y-%m-%d')}"
                f"   • Source: https://nmis.et/"
            )
        logger.info(f"compare_livestock_prices_nearby result: {lines}")
        return "\n\n".join(lines)