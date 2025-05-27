import os
import requests
from dotenv import load_dotenv
from mapbox import Geocoder
from cachecontrol.caches.file_cache import FileCache
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from helpers.utils import get_logger

logger = get_logger(__name__)

load_dotenv()

# Create a cached session
mapbox_cache = FileCache('.mapbox_cache')

geocoder = Geocoder(access_token=os.getenv("MAPBOX_API_TOKEN"), cache=mapbox_cache)

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
        """Check if place_name is provided."""
        if self.latitude is not None and self.longitude is not None and self.place_name is None:
            response = geocoder.reverse(lon=self.longitude, lat=self.latitude, 
                                     limit=1, 
                                     types=['place'])
            if response.status_code == 200:
                data = response.json()
                if data['features']:
                    self.place_name = data['features'][0]['place_name']

    def _location_string(self):
        if self.latitude and self.longitude:
            return f"{self.place_name} (Latitude: {self.latitude}, Longitude: {self.longitude})"
        else:
            return "Location not available"

    def __str__(self):
        return f"{self.place_name} ({self.latitude}, {self.longitude})"


def forward_geocode(place_name: str) -> Optional[Location]:
    """Forward Geocoding to get latitude and longitude from place name.

    Args:
        place_name (str): The place name to geocode, in English.

    Returns:
        Location: The location of the place.
    """
    # Bounding box for Maharashtra [min_lon, min_lat, max_lon, max_lat]
    # Coordinates from Wikipedia: 15°35'N to 22°02'N and 72°36'E to 80°54'E
    maharashtra_bbox = [72.6, 15.583333, 80.9, 22.033333]

    response = geocoder.forward(place_name, 
                                country=["in"],
                                bbox=maharashtra_bbox,
                                limit=1)
    if response.status_code == 200:
        data = response.json()
        if data['features']:
            feature = data['features'][0]
            longitude, latitude = feature['center']
            return Location(
                place_name=feature['place_name'],
                latitude=latitude,
                longitude=longitude
            )
        else:
            logger.info("No results found.")
    else:
        logger.info(f"Error: {response.status_code}")
    return None


def reverse_geocode(latitude: float, longitude: float) -> Optional[Location]:
    """Reverse Geocoding to get place name from latitude and longitude.

    Args:
        latitude (float): The latitude of the location.
        longitude (float): The longitude of the location.

    Returns:
        Location: The location of the place.
    """
    response = geocoder.reverse(lon=longitude, lat=latitude, 
                                limit=1, 
                                types=['place']
                                )
    if response.status_code == 200:
        data = response.json()
        if data['features']:
            feature = data['features'][0]
            return Location(
                place_name=feature['place_name'],
                latitude=latitude,
                longitude=longitude
            )
        else:
            logger.info("No results found.")
    else:
        logger.info(f"Error: {response.status_code}")
    return None