import os
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from typing import Dict, Optional
from pydantic import BaseModel, Field, field_validator
from helpers.utils import get_logger

logger = get_logger(__name__)

load_dotenv()

# Initialize Nominatim geocoder (self-hosted)
from geopy.geocoders import Nominatim

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
    
    def model_post_init(self, __context__) -> None:
        """Called after the model is initialized."""
        super().model_post_init(__context__)
        self.check_place_name()
    
    def check_place_name(self) -> None:
        """If coordinates are provided but not place name, do reverse geocoding."""
        if self.latitude is not None and self.longitude is not None and self.place_name is None:
            try:
                location = geocoder.reverse((self.latitude, self.longitude), exactly_one=True)
                if location:
                    self.place_name = location.raw['display_name']
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                logger.error(f"Reverse geocoding error: {e}")

    def _location_string(self):
        if self.latitude and self.longitude:
            return f"{self.place_name} (Latitude: {self.latitude}, Longitude: {self.longitude})"
        else:
            return "Location not available"

    def __str__(self):
        return f"{self.place_name} ({self.latitude}, {self.longitude})"


def forward_geocode(place_name: str) -> Optional[Location]:
    """Use this tool to get latitude and longitude of a place given its name."""
    try:
        response = geocoder.geocode(
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

            return Location(
                place_name=response.raw['display_name'],
                latitude=response.latitude,
                longitude=response.longitude,
                address=address
            )

        logger.info("No results found.")
        return None

    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.error(f"Forward geocoding error: {e}")
        return None


def reverse_geocode(latitude: float, longitude: float) -> Optional[Location]:
    """Use this tool to get the place name given its latitude and longitude."""
    try:
        location = geocoder.reverse(
            (latitude, longitude), 
            exactly_one=True, 
            addressdetails=True,
            zoom=10,
            language='en'
            )
        logger.info(f"Reverse geocoding response: {location}")
        
        if not location:
            logger.info("No reverse geocoding result found.")
            return None
        
        raw = location.raw
        address = raw.get("address", {})
        
        return Location(
                place_name=location.raw['display_name'],
                latitude=latitude,
                longitude=longitude,
                address=address
            )
        
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.error(f"Reverse geocoding error: {e}")
    return None