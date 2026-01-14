from typing import TypedDict, Optional
from helpers.utils import haversine
from agents.tools.maps import reverse_geocode
from helpers.utils import get_logger
logger = get_logger(__name__)


class RegionDetectionResult(TypedDict, total=False):
    """Result structure for region detection functions."""
    success: bool
    inside_supported_region: bool
    region: str
    message: str
    nearest_region: str
    distance_km: float


REGION_CENTROIDS = {
    "Amhara": (11.5, 38.0),
    "Oromia": (8.5, 39.5),
    "Tigray": (13.5, 39.0),
    "Sidama": (6.85, 38.4),
    "South West Ethiopia": (7.3, 35.5),
    
    "SNNP": (6.5, 37.0), 
    "South Ethiopia": (5.5, 37.5),  # New southern region
    "Central Ethiopia": (7.0, 38.0),  # Former SNNPR core area
}

SUPPORTED_REGIONS = {
    # Amhara
    "amhara": "Amhara",
    "amhara region": "Amhara",
    "Addis Ababa": "Amhara",
    "addis ababa": "Amhara",
    # Oromia
    "oromia": "Oromia",
    "oromia region": "Oromia",
    
    # SNNP and successor names
    "snnp": "SNNP",
    "snnpr": "SNNP",
    "southern nations, nationalities, and peoples": "SNNP",
    "southern nations, nationalities, and peoples' region": "SNNP",
    "southern nations": "SNNP",
    "central ethiopia": "SNNP",
    "central ethiopia regional state": "SNNP",
    "south ethiopia": "SNNP",
    "south ethiopia regional state": "SNNP",
    
    # Tigray
    "tigray": "Tigray",
    "tigray region": "Tigray",
    
    # Sidama
    "sidama": "Sidama",
    "sidama region": "Sidama",
    "sidama regional state": "Sidama",
    
    # South West
    "south west": "South West",
    "south west ethiopia": "South West",
    "south west ethiopia peoples region": "South West",
    "south west ethiopia regional state": "South West",
    "southwest": "South West",
    "southwest ethiopia": "South West",
}


def detect_region_from_address(address):
    logger.debug(f"Detecting region from address: {address}")
    for key in ["state", "region"]:
        value = address.get(key)
        logger.debug(f"Checking address field '{key}': {value}")
        if not value:
            continue

        normalized = value.lower()
        for k, v in SUPPORTED_REGIONS.items():
            if k in normalized:
                return v

    return None


def find_nearest_region(lat, lon):
    nearest = None
    min_dist = float("inf")

    for region, (r_lat, r_lon) in REGION_CENTROIDS.items():
        dist = haversine(lat, lon, r_lat, r_lon)
        logger.debug(f"Distance to {region}: {dist:.2f} km")
        if dist < min_dist:
            min_dist = dist
            nearest = region
    logger.debug(f"Nearest region to ({lat}, {lon}) is {nearest} at {min_dist} km")
    return nearest, round(min_dist, 2)

def detect_crop_region(latitude: float, longitude: float) -> RegionDetectionResult:
    """
    Always use forward_geocode to get coordinates from place names, then use this function.
    Detects whether a user is located within one of the supported regions.

    This function uses reverse geocoding to determine the administrative region
    for the given geographic coordinates and checks it against a predefined
    list of supported regions.

    Use this function when:
    - A user asks which region they are currently in
    - You need to validate whether a user is inside a supported service area
    - Region-specific data or logic must be applied

    Parameters:
        latitude (float): The user's latitude in decimal degrees.
        longitude (float): The user's longitude in decimal degrees.

    Returns:
        RegionDetectionResult: Structured result with region detection info

    Raises:
        ValueError: If latitude or longitude is out of valid range
    """
    # Validate inputs
    if not -90 <= latitude <= 90:
        raise ValueError(f"Invalid latitude: {latitude}. Must be between -90 and 90.")
    if not -180 <= longitude <= 180:
        raise ValueError(f"Invalid longitude: {longitude}. Must be between -180 and 180.")

    data = reverse_geocode(latitude, longitude)
    if not data or not hasattr(data, 'address'):
        return {
            "success": False,
            "message": "Unable to determine location from coordinates"
        }
    address = data.address
    logger.debug(f"Reverse geocoding address: {data}")


    region = detect_region_from_address(address)
    logger.debug(f"Detected region from address: {region}")
    if region:
        return {
            "inside_supported_region": True,
            "region": region
        }

    nearest_region, distance_km = find_nearest_region(latitude, longitude)
    logger.debug(f"Nearest region to ({latitude}, {longitude}) is {nearest_region} at {distance_km} km")
    return {
        "inside_supported_region": False,
        "message": "You are not inside a supported region",
        "nearest_region": nearest_region,
        "distance_km": distance_km
    }




# Livestock regions may differ from crop regions
LIVESTOCK_REGION_CENTROIDS = {
    "Oromia": (8.5, 39.5),
    "Afar": (11.5, 41.0),
    "Somali": (6.5, 44.5),
}

SUPPORTED_LIVESTOCK_REGIONS = {
    # Afar
    "afar": "Afar",
    "afar region": "Afar",
    "afar regional state": "Afar",
    
    # Somali
    "somali": "Somali",
    "somali region": "Somali",
    "somali regional state": "Somali",
    "ogaden": "Somali", # Historical/common alias
    
    # Oromia
    "oromia": "Oromia",
    "oromia region": "Oromia",
}


def detect_livestock_region_from_address(address):
    """Helper function to detect livestock region from address"""
    logger.debug(f"Detecting livestock region from address: {address}")
    for key in ["state", "region"]:
        value = address.get(key)
        logger.debug(f"Checking address field '{key}': {value}")
        if not value:
            continue

        normalized = value.lower()
        for k, v in SUPPORTED_LIVESTOCK_REGIONS.items():
            if k in normalized:
                return v

    return None


def find_nearest_livestock_region(lat, lon):
    """Helper function to find nearest livestock region"""
    nearest = None
    min_dist = float("inf")

    for region, (r_lat, r_lon) in LIVESTOCK_REGION_CENTROIDS.items():
        dist = haversine(lat, lon, r_lat, r_lon)
        logger.debug(f"Distance to livestock region {region}: {dist:.2f} km")
        if dist < min_dist:
            min_dist = dist
            nearest = region
    logger.debug(f"Nearest livestock region to ({lat}, {lon}) is {nearest} at {min_dist} km")
    return nearest, round(min_dist, 2)


def detect_livestock_region(latitude: float, longitude: float) -> RegionDetectionResult:
    """
    Detects whether a user is located within one of the supported livestock regions.

    This function uses reverse geocoding to determine the administrative region
    for the given geographic coordinates and checks it against a predefined
    list of supported livestock regions.

    Use this function when:
    - A user asks which livestock region they are currently in
    - You need to validate whether a user is inside a supported livestock service area
    - Livestock region-specific data or logic must be applied

    Parameters:
        latitude (float): The user's latitude in decimal degrees.
        longitude (float): The user's longitude in decimal degrees.

    Returns:
        RegionDetectionResult: Structured result with region detection info

    Raises:
        ValueError: If latitude or longitude is out of valid range
    """
    # Validate inputs
    if not -90 <= latitude <= 90:
        raise ValueError(f"Invalid latitude: {latitude}. Must be between -90 and 90.")
    if not -180 <= longitude <= 180:
        raise ValueError(f"Invalid longitude: {longitude}. Must be between -180 and 180.")

    data = reverse_geocode(latitude, longitude)
    if not data or not hasattr(data, 'address'):
        return {
            "success": False,
            "message": "Unable to determine location from coordinates"
        }

    address = data.address
    logger.debug(f"Reverse geocoding address for livestock: {data}")

    region = detect_livestock_region_from_address(address)
    logger.debug(f"Detected livestock region from address: {region}")

    if region:
        return {
            "inside_supported_region": True,
            "region": region
        }

    nearest_region, distance_km = find_nearest_livestock_region(latitude, longitude)
    logger.debug(f"Nearest livestock region to ({latitude}, {longitude}) is {nearest_region} at {distance_km} km")
    
    return {
        "inside_supported_region": False,
        "message": "You are not inside a supported livestock region",
        "nearest_region": nearest_region,
        "distance_km": distance_km
    }
