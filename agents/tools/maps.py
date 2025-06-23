import os
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from helpers.utils import get_logger

logger = get_logger(__name__)

load_dotenv()

# Initialize Nominatim geocoder (self-hosted)
geocoder = Nominatim(
    user_agent="bharathvistaar", 
    domain="nominatim:8080",
    scheme="http",
    timeout=10
)

class Location(BaseModel):
    """Location model for the maps tool."""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    place_name: Optional[str] = None

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
    """Forward geocoding using Nominatim."""
    try:
        response = geocoder.geocode(place_name, exactly_one=True, addressdetails=True, country_codes='in')

        if response:
            return Location(
                place_name=response.raw['display_name'],
                latitude=response.latitude,
                longitude=response.longitude
            )
        else:
            logger.info("No results found.")
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.error(f"Forward geocoding error: {e}")
    return None


def reverse_geocode(latitude: float, longitude: float) -> Optional[Location]:
    """Reverse geocoding using Nominatim."""
    try:
        location = geocoder.reverse((latitude, longitude), exactly_one=True)
        if location:
            return Location(
                place_name=location.raw['display_name'],
                latitude=latitude,
                longitude=longitude
            )
        else:
            logger.info("No results found.")
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.error(f"Reverse geocoding error: {e}")
    return None