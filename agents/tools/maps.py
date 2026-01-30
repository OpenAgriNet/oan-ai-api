import os
import asyncio
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from typing import Dict, Optional
from pydantic import BaseModel, Field, field_validator
from helpers.utils import get_logger
from app.core.cache import cache 

logger = get_logger(__name__)

load_dotenv()

# Cache TTL for geocoding (24 hours - locations don't change)
GEOCODE_CACHE_TTL = 60 * 60 * 24

# Initialize Nominatim geocoder (self-hosted)
geocoder = Nominatim(
    user_agent="ethiopia_agri_chatbot",
    domain=os.getenv("NOMINATIM_DOMAIN", ""),  
    scheme="http",
    timeout=10
)


class Location(BaseModel):
    """Location model for the maps tool."""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    place_name: Optional[str] = None
    address: Dict[str, str]
    
    @field_validator('latitude', 'longitude')
    @classmethod
    def round_coordinates(cls, v):
        if v is not None:
            return round(float(v), 3)
        return v


    def _location_string(self):
        if self.latitude and self.longitude:
            return f"{self.place_name} (Latitude: {self.latitude}, Longitude: {self.longitude})"
        else:
            return "Location not available"

    def __str__(self):
        return f"{self.place_name} ({self.latitude}, {self.longitude})"


async def forward_geocode(place_name: str) -> Optional[Location]:
    """Use this tool to get latitude and longitude of a place given its name."""
    # Normalize place name for cache key
    cache_key = f"geocode:forward:{place_name.lower().strip()}"
    
    # Try to get from cache first
    cached_data = await cache.get(cache_key)
    if cached_data:
        logger.info(f"Cache HIT for forward geocode: {cache_key}")
        return Location(**cached_data)
    
    logger.info(f"Cache MISS for forward geocode: {cache_key}")
    
    try:
        response = await asyncio.to_thread(
            geocoder.geocode,
            place_name,
            exactly_one=True,
            addressdetails=True,
            country_codes='et',
            language='en'
        )
        logger.info(f"Forward geocoding response: {response}")
        if response:
            # Get address details if available
            raw = response.raw
            address = raw.get("address", {})

            location = Location(
                place_name=response.raw['display_name'],
                latitude=response.latitude,
                longitude=response.longitude,
                address=address
            )
            
            # Cache the result
            await cache.set(cache_key, location.model_dump(), ttl=GEOCODE_CACHE_TTL)
            logger.info(f"Cached forward geocode for {GEOCODE_CACHE_TTL}s: {cache_key}")
            
            return location

        logger.info("No results found.")
        return None

    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.error(f"Forward geocoding error: {e}")
        return None


async def reverse_geocode(latitude: float, longitude: float) -> Optional[Location]:
    """Use this tool to get the place name given its latitude and longitude."""
    # Round coordinates for cache key consistency
    lat_rounded = round(latitude, 4)
    lon_rounded = round(longitude, 4)
    cache_key = f"geocode:reverse:{lat_rounded}:{lon_rounded}"
    
    # Try to get from cache first
    cached_data = await cache.get(cache_key)
    if cached_data:
        logger.info(f"Cache HIT for reverse geocode: {cache_key}")
        return Location(**cached_data)
    
    logger.info(f"Cache MISS for reverse geocode: {cache_key}")
    
    try:
        location_response = await asyncio.to_thread(
            geocoder.reverse,
            (latitude, longitude),
            exactly_one=True,
            addressdetails=True,
            zoom=10,
            language='en'
        )
        logger.info(f"Reverse geocoding response: {location_response}")
        
        if not location_response:
            logger.info("No reverse geocoding result found.")
            return None
        
        raw = location_response.raw
        address = raw.get("address", {})
        
        location = Location(
            place_name=location_response.raw['display_name'],
            latitude=latitude,
            longitude=longitude,
            address=address
        )
        
        # Cache the result
        await cache.set(cache_key, location.model_dump(), ttl=GEOCODE_CACHE_TTL)
        logger.info(f"Cached reverse geocode for {GEOCODE_CACHE_TTL}s: {cache_key}")
        
        return location
        
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.error(f"Reverse geocoding error: {e}")
    return None