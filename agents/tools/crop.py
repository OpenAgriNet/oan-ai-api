# agents/tools/crop.py
from pydantic_ai import RunContext
from agents.deps import FarmerContext
from app.database import async_session_maker
from sqlalchemy import func, or_, select
from app.models.market import Crop, CropVariety, MarketPrice, Marketplace
from typing import List, Optional, Tuple, Union
from sqlalchemy.orm import joinedload
from helpers.utils import get_logger

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


async def get_crop_price_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    crop_name: str,
    region: Optional[str] = None
) -> str:
    """
    Always use the list_crops_in_marketplace(marketplace_name) before using this Tool.
    Get latest price information for a specific crop in a marketplace.

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

        return "\n\n".join(price_data_varieties.values())


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
