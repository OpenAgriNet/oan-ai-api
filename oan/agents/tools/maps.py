import os
import requests
from dotenv import load_dotenv
from mapbox import Geocoder
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from helpers.utils import get_logger

logger = get_logger(__name__)

load_dotenv()

geocoder = Geocoder(access_token=os.getenv("MAPBOX_API_TOKEN"))

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
    response = geocoder.forward(place_name, 
                                country=["in"],
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
