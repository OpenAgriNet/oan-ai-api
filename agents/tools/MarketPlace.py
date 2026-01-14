import math
from typing import List, Dict, Optional, Union

from helpers.market_place_json import ACTIVE_CROP_MARKETPLACE, ACTIVE_LIVESTOCK_MARKETPLACE, EXACT_MATCH_UP_LIVESTOCK_MARKETPLACES, EXACT_MATCH_UP_MARKETPLACES, MARKETPLACES, LIVESTOCK_MARKETPLACES
from helpers.utils import haversine
from helpers.utils import get_logger
logger = get_logger(__name__)


def list_active_crop_marketplaces()-> Dict:
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
    return ACTIVE_CROP_MARKETPLACE

def find_nearest_crop_marketplaces(
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
        List[dict] | str: Nearest marketplaces sorted by distance, or error message if region not supported

    Raises:
        ValueError: If coordinates or numeric parameters are invalid
    """
    # Validate inputs
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



def find_crop_marketplace_by_name(
    marketplace_name: str,
) -> Optional[Dict]:
    """
    Find a marketplace by name and return its details.

    This tool is used when the user searches for a marketplace directly
    by name, without providing location or asking for nearby results.

    Parameters:
        marketplace_name (str): Name of the marketplace provided by the user

    Returns:
        dict | None: Marketplace details if found, otherwise None
    """
    logger.info(f"find_crop_marketplace_by_name: {marketplace_name}")

    res = EXACT_MATCH_UP_MARKETPLACES.get(marketplace_name, None)

    return res


def list_crop_marketplaces_by_region(region: str) -> Union[List[Dict], str]:
    """
    List all marketplaces in a specified region.

    This tool is used when the user requests a list of marketplaces
    available in a certain region.

    Parameters:
        region (str): Region name
    Returns:
        List[dict] | str: List of marketplaces in the region, or error message if region not supported
    """
    logger.info(f"list_crop_marketplaces_by_region: {region}")
    if region not in MARKETPLACES:
        return "Can you check in the supported regions: Amhara, Oromia, Tigray, Sidama, South West Ethiopia, SNNP"

    return [
        {
            "name": m["name"],
            "latitude": m["lat"],
            "longitude": m["lon"],
            "region": region
        }
        for m in MARKETPLACES[region]
    ]
    
    
# ============================================================================
# LIVESTOCK MARKETPLACE DISCOVERY
# ============================================================================
 

def list_active_livestock_marketplaces()->Dict:
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

    return ACTIVE_LIVESTOCK_MARKETPLACE
    

def find_nearest_livestock_marketplaces(
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
        List[dict] | str: Nearest livestock marketplaces sorted by distance, or error message if region not supported

    Raises:
        ValueError: If coordinates or numeric parameters are invalid
    """
    # Validate inputs
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
        return "Can you check in the supported regions: Afar, Oromia Somali"

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


def find_livestock_marketplace_by_name(
    marketplace_name: str,
) -> Optional[Dict]:
    """
    Find a livestock marketplace by name and return its details.

    This tool is used when the user searches for a livestock marketplace directly
    by name, without providing location or asking for nearby results.

    Parameters:
        marketplace_name (str): Name of the livestock marketplace provided by the user

    Returns:
        dict | None: Livestock marketplace details if found, otherwise None
    """
    logger.info(f"find_livestock_marketplace_by_name: {marketplace_name}")

    res = EXACT_MATCH_UP_LIVESTOCK_MARKETPLACES.get(marketplace_name, None)

    return res


def list_livestock_marketplaces_by_region(region: str) -> Union[List[Dict], str]:
    """
    List all livestock marketplaces in a specified region.

    This tool is used when the user requests a list of livestock marketplaces
    available in a certain region.

    Parameters:
        region (str): Region name
    Returns:
        List[dict] | str: List of livestock marketplaces in the region, or error message if region not supported
    """
    logger.info(f"list_livestock_marketplaces_by_region: {region}")
    if region not in LIVESTOCK_MARKETPLACES:
        return "Can you check in the supported regions: Afar, Oromia, Somali"

    return [
        {
            "name": m["name"],
            "latitude": m["lat"],
            "longitude": m["lon"],
            "region": region
        }
        for m in LIVESTOCK_MARKETPLACES[region]
    ]

