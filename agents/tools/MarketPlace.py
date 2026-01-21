from typing import List, Dict, Optional, Union
from app.database import async_session_maker
from app.models.market import Marketplace
from sqlalchemy import select, func, or_
from helpers.market_place_json import MARKETPLACES, LIVESTOCK_MARKETPLACES
from helpers.utils import haversine, get_logger

logger = get_logger(__name__)


# ============================================================================
# CROP MARKETPLACE TOOLS
# ============================================================================

async def list_active_crop_marketplaces() -> Dict[str, str]:
    """
    Get dictionary mapping English to Amharic names for all active crop marketplaces.

    Use this tool when:
    1. User provides Amharic marketplace name - reverse lookup to get English equivalent
    2. find_crop_marketplace_by_name returns empty - verify marketplace exists
    3. Need to suggest corrections for misspelled names

    Returns:
        Dict[str, str]: Dictionary with English:Amharic name pairs
                       Example: {"Merkato": "መርካቶ", "Piassa": "ፒያሳ"}

    Note: ALL subsequent tool calls must use English names (dictionary keys)
    """
    async with async_session_maker() as db:
        stmt = select(Marketplace.name, Marketplace.name_amharic).where(
            Marketplace.marketplace_type == "crop",
            Marketplace.is_active == True
        ).order_by(Marketplace.name)

        result = await db.execute(stmt)
        rows = result.all()

        return {row.name: row.name_amharic or "" for row in rows}


async def find_crop_marketplace_by_name(
    marketplace_name: str,
    region: Optional[str] = None
) -> Union[Dict, str, None]:
    """
    Find a crop marketplace by name and return its details.

    Parameters:
        marketplace_name (str): Name of the marketplace (English or Amharic)
        region (str): Optional region to disambiguate if same name exists in multiple regions

    Returns:
        dict: Marketplace details if found
        str: Error message if multiple matches found
        None: If not found
    """
    logger.info(f"find_crop_marketplace_by_name: {marketplace_name}, region={region}")

    async with async_session_maker() as db:
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
            return None

        if len(marketplaces) == 1:
            m = marketplaces[0]
            return {
                "name": m.name,
                "name_amharic": m.name_amharic,
                "region": m.region,
                "region_amharic": m.region_amharic,
                "latitude": m.latitude,
                "longitude": m.longitude
            }

        # Multiple matches
        regions_list = [f"{m.name} ({m.region})" for m in marketplaces]
        return f"Multiple marketplaces found: {', '.join(regions_list)}. Please specify region."


async def list_crop_marketplaces_by_region(region: str) -> Union[List[Dict], str]:
    """
    List all crop marketplaces in a specified region.

    Parameters:
        region (str): Region name (English or Amharic)

    Returns:
        List[dict] | str: List of marketplaces in the region
    """
    logger.info(f"list_crop_marketplaces_by_region: {region}")

    async with async_session_maker() as db:
        stmt = select(Marketplace).where(
            Marketplace.marketplace_type == "crop",
            Marketplace.is_active == True,
            or_(
                func.lower(Marketplace.region) == func.lower(region),
                func.lower(Marketplace.region_amharic) == func.lower(region)
            )
        ).order_by(Marketplace.name)

        result = await db.execute(stmt)
        marketplaces = result.scalars().all()

        if not marketplaces:
            return f"No crop marketplaces found in {region} region."

        return [
            {
                "name": m.name,
                "name_amharic": m.name_amharic,
                "latitude": m.latitude,
                "longitude": m.longitude,
                "region": m.region
            }
            for m in marketplaces
        ]


async def find_nearest_crop_marketplaces(
    user_lat: float,
    user_lon: float,
    region: str,
    radius_km: float = 20,
    limit: int = 5
) -> Union[List[Dict], str]:
    """
    Find marketplaces within a given region that are closest to the user.

    Parameters:
        user_lat (float): User latitude
        user_lon (float): User longitude
        region (str): Region name (from region detection tool)
        radius_km (float): Search radius in kilometers
        limit (int): Maximum number of marketplaces to return

    Returns:
        List[dict] | str: Nearest marketplaces sorted by distance
    """
    if not -90 <= user_lat <= 90:
        raise ValueError(f"Invalid latitude: {user_lat}. Must be between -90 and 90.")
    if not -180 <= user_lon <= 180:
        raise ValueError(f"Invalid longitude: {user_lon}. Must be between -180 and 180.")
    if radius_km <= 0:
        raise ValueError(f"Radius must be positive: {radius_km}")
    if limit <= 0:
        raise ValueError(f"Limit must be positive: {limit}")

    logger.info(f"find_nearest_crop_marketplaces: region={region}")

    if region not in MARKETPLACES:
        return "Can you check in the supported regions: Amhara, Oromia, Tigray, Sidama, South West Ethiopia, SNNP"

    results = []
    for m in MARKETPLACES[region]:
        distance = haversine(user_lat, user_lon, m["lat"], m["lon"])
        if distance <= radius_km:
            results.append({
                "name": m["name"],
                "latitude": m["lat"],
                "longitude": m["lon"],
                "distance_km": round(distance, 2)
            })

    results.sort(key=lambda x: x["distance_km"])
    return results[:limit]


# ============================================================================
# LIVESTOCK MARKETPLACE TOOLS
# ============================================================================

async def list_active_livestock_marketplaces() -> Dict[str, str]:
    """
    Get dictionary mapping English to Amharic names for all active livestock marketplaces.

    Use this tool when:
    1. User provides Amharic marketplace name - reverse lookup to get English equivalent
    2. find_livestock_marketplace_by_name returns empty - verify marketplace exists
    3. Need to suggest corrections for misspelled names

    Returns:
        Dict[str, str]: Dictionary with English:Amharic name pairs
                       Example: {"Bati": "ባቲ", "Semera": "ሰመራ"}

    Note: ALL subsequent tool calls must use English names (dictionary keys)
    """
    async with async_session_maker() as db:
        stmt = select(Marketplace.name, Marketplace.name_amharic).where(
            Marketplace.marketplace_type == "livestock",
            Marketplace.is_active == True
        ).order_by(Marketplace.name)

        result = await db.execute(stmt)
        rows = result.all()

        return {row.name: row.name_amharic or "" for row in rows}


async def find_livestock_marketplace_by_name(
    marketplace_name: str,
    region: Optional[str] = None
) -> Union[Dict, str, None]:
    """
    Find a livestock marketplace by name and return its details.

    Parameters:
        marketplace_name (str): Name of the livestock marketplace (English or Amharic)
        region (str): Optional region to disambiguate if same name exists in multiple regions

    Returns:
        dict: Livestock marketplace details if found
        str: Error message if multiple matches found
        None: If not found
    """
    logger.info(f"find_livestock_marketplace_by_name: {marketplace_name}, region={region}")

    async with async_session_maker() as db:
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
            return None

        if len(marketplaces) == 1:
            m = marketplaces[0]
            return {
                "name": m.name,
                "name_amharic": m.name_amharic,
                "region": m.region,
                "region_amharic": m.region_amharic,
                "latitude": m.latitude,
                "longitude": m.longitude
            }

        # Multiple matches
        regions_list = [f"{m.name} ({m.region})" for m in marketplaces]
        return f"Multiple marketplaces found: {', '.join(regions_list)}. Please specify region."


async def list_livestock_marketplaces_by_region(region: str) -> Union[List[Dict], str]:
    """
    List all livestock marketplaces in a specified region.

    Parameters:
        region (str): Region name (English or Amharic)

    Returns:
        List[dict] | str: List of livestock marketplaces in the region
    """
    logger.info(f"list_livestock_marketplaces_by_region: {region}")

    async with async_session_maker() as db:
        stmt = select(Marketplace).where(
            Marketplace.marketplace_type == "livestock",
            Marketplace.is_active == True,
            or_(
                func.lower(Marketplace.region) == func.lower(region),
                func.lower(Marketplace.region_amharic) == func.lower(region)
            )
        ).order_by(Marketplace.name)

        result = await db.execute(stmt)
        marketplaces = result.scalars().all()

        if not marketplaces:
            return f"No livestock marketplaces found in {region} region."

        return [
            {
                "name": m.name,
                "name_amharic": m.name_amharic,
                "latitude": m.latitude,
                "longitude": m.longitude,
                "region": m.region
            }
            for m in marketplaces
        ]


async def find_nearest_livestock_marketplaces(
    user_lat: float,
    user_lon: float,
    region: str,
    radius_km: float = 20,
    limit: int = 5
) -> Union[List[Dict], str]:
    """
    Find livestock marketplaces within a given region that are closest to the user.

    Parameters:
        user_lat (float): User latitude
        user_lon (float): User longitude
        region (str): Region name (from livestock region detection tool)
        radius_km (float): Search radius in kilometers
        limit (int): Maximum number of marketplaces to return

    Returns:
        List[dict] | str: Nearest livestock marketplaces sorted by distance
    """
    if not -90 <= user_lat <= 90:
        raise ValueError(f"Invalid latitude: {user_lat}. Must be between -90 and 90.")
    if not -180 <= user_lon <= 180:
        raise ValueError(f"Invalid longitude: {user_lon}. Must be between -180 and 180.")
    if radius_km <= 0:
        raise ValueError(f"Radius must be positive: {radius_km}")
    if limit <= 0:
        raise ValueError(f"Limit must be positive: {limit}")

    logger.info(f"find_nearest_livestock_marketplaces: region={region}")
    if region not in LIVESTOCK_MARKETPLACES:
        return "Can you check in the supported regions: Afar, Oromia, Somali"

    results = []
    for m in LIVESTOCK_MARKETPLACES[region]:
        distance = haversine(user_lat, user_lon, m["lat"], m["lon"])
        if distance <= radius_km:
            results.append({
                "name": m["name"],
                "latitude": m["lat"],
                "longitude": m["lon"],
                "distance_km": round(distance, 2)
            })

    results.sort(key=lambda x: x["distance_km"])
    return results[:limit]
