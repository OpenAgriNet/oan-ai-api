import uuid
from datetime import datetime, timezone, timedelta
from helpers.utils import get_logger
import requests
from pydantic import BaseModel, AnyHttpUrl, Field
from typing import List, Optional, Dict, Any
from pydantic_ai import ModelRetry, UnexpectedModelBehavior
import os

logger = get_logger(__name__)

# -----------------------
# Basic Models
# -----------------------
class Image(BaseModel):
    url: AnyHttpUrl

class Descriptor(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    short_desc: Optional[str] = None
    long_desc: Optional[str] = None
    images: Optional[List[Image]] = None

    def __str__(self) -> str:
        if self.name:
            return self.name
        elif self.code:
            return self.code
        return ""

class Country(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None

class Location(BaseModel):
    country: Optional[Country] = None

class City(BaseModel):
    name: Optional[str] = None

class LocationInfo(BaseModel):
    id: str
    city: City

# -----------------------
# Price Models
# -----------------------
class Price(BaseModel):
    minimum_value: str
    maximum_value: str
    estimated_value: str

    def __str__(self) -> str:
        return f"Min: ₹{self.minimum_value}, Max: ₹{self.maximum_value}, Est: ₹{self.estimated_value}"

# -----------------------
# Item & Provider Models
# -----------------------
class Item(BaseModel):
    id: str
    descriptor: Descriptor
    location_ids: List[str]
    price: Price

    def __str__(self) -> str:
        return f"{self.descriptor.name}: {self.price}"

class Provider(BaseModel):
    id: str
    descriptor: Descriptor
    locations: List[LocationInfo]
    items: List[Item]
    time: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        lines = []
        lines.append(f"Provider: {self.descriptor.name}")
        
        if self.locations:
            lines.append("  Locations:")
            for loc in self.locations:
                lines.append(f"    - {loc.city.name}")
        
        if self.items:
            lines.append("  Items:")
            for item in self.items:
                lines.append(f"    - {item}")
        
        return "\n".join(lines)

# -----------------------
# Catalog & Message Models
# -----------------------
class Catalog(BaseModel):
    providers: List[Provider]

    def __str__(self) -> str:
        lines = []
        if self.providers:
            for provider in self.providers:
                provider_str = str(provider).replace("\n", "\n  ")
                lines.append(f"  {provider_str}")
        return "\n".join(lines)

class Message(BaseModel):
    catalog: Catalog

    def __str__(self) -> str:
        return str(self.catalog)

# -----------------------
# Context & Response Models
# -----------------------
class Context(BaseModel):
    ttl: Optional[str] = None
    action: str
    timestamp: str
    message_id: str
    transaction_id: str
    domain: str
    version: str
    bap_id: Optional[str] = None
    bap_uri: Optional[AnyHttpUrl] = None
    bpp_id: Optional[str] = None
    bpp_uri: Optional[AnyHttpUrl] = None
    country: Optional[str] = None
    city: Optional[str] = None
    location: Optional[Location] = None

class ResponseItem(BaseModel):
    context: Context
    message: Message

    def __str__(self) -> str:
        return str(self.message)

class MandiResponse(BaseModel):
    context: Context
    responses: List[ResponseItem]

    def _has_mandi_data(self) -> bool:
        """Check if there are any responses with providers that have items."""
        for response in self.responses:
            for provider in response.message.catalog.providers:
                if provider.items and len(provider.items) > 0:
                    return True
        return False
    
    def __str__(self) -> str:
        lines = []
        lines.append("> Mandi Price Data")
        
        has_mandi_data = self._has_mandi_data()
        if not self.responses or not has_mandi_data:
            lines.append("No mandi price data found for the requested location.")
            return "\n".join(lines)
            
        lines.append("Responses:")
        for idx, rsp in enumerate(self.responses, start=1):
            rsp_str = str(rsp).replace("\n", "\n  ")
            lines.append(f"  Response {idx}:")
            lines.append(f"    {rsp_str}")
        return "\n".join(lines)

# -----------------------
# Request Model
# -----------------------
class MandiRequest(BaseModel):
    """MandiRequest model for the mandi price API.
    
    Args:
        latitude (float): Latitude of the location
        longitude (float): Longitude of the location
        days_back (int): Number of days back to get prices for. 0 means current day, 1 means previous day, etc. Default is 0 (current day).
    """
    latitude: float = Field(..., description="Latitude of the location")
    longitude: float = Field(..., description="Longitude of the location")
    days_back: int = Field(0, description="Number of days back to get prices for. 0 means current day, 1 means previous day, etc. Default is 0 (current day).")
    
    def get_payload(self) -> Dict[str, Any]:
        """
        Convert the MandiRequest object to a dictionary.
        
        Returns:
            Dict[str, Any]: The dictionary representation of the MandiRequest object
        """
        now = datetime.today()
        
        start_date = now - timedelta(days=self.days_back)
        end_date   = now
        return {
            "context": {
                "domain": "advisory:mh-vistaar",
                "action": "search",
                "location": {
                    "country": {
                        "name": "India",
                        "code": "IND"
                    }
                },
                "version": "1.1.0",
                "bap_id": os.getenv("BAP_ID"),
                "bap_uri": os.getenv("BAP_URI"),
                "message_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "timestamp": now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            },
            "message": {
                "intent": {
                    "category": {
                        "descriptor": {
                            "code": "price-discovery"
                        }
                    },
                    "item": {
                        "descriptor": {"code": ""}
                    },
                    "fulfillment": {
                        "stops": [
                            {
                                "location": {
                                    "gps": f"{self.latitude}, {self.longitude}"
                                },
                                "time": {
                                    "range": {
                                        "start": start_date.strftime('%Y-%m-%dT00:00:00Z'),
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }

def mandi_prices(latitude: float, longitude: float, days_back: int = 0) -> str:
    """Get Market/Mandi prices for a specific location.

    Args:
        latitude (float): Latitude of the location
        longitude (float): Longitude of the location
        days_back (int): Number of days back to get prices for. 0 means current day, 1 means previous day, etc. Default is 0 (current day).

    Returns:
        str: The mandi prices for the specific location
    """
    try:
        payload = MandiRequest(latitude=latitude, longitude=longitude, days_back=days_back).get_payload()
        response = requests.post(
            os.getenv("BAP_ENDPOINT"),
            json=payload,
            timeout=(10, 15)
        )
        
        if response.status_code != 200:
            logger.error(f"Mandi API returned status code {response.status_code}")
            return "Mandi service unavailable. Retrying"
            
        mandi_response = MandiResponse.model_validate(response.json())
        return str(mandi_response)
                
    except requests.Timeout as e:
        logger.error(f"Mandi API request timed out: {str(e)}")
        return "Mandi request timed out. Please try again later."
        
    except requests.RequestException as e:
        logger.error(f"Mandi API request failed: {e}")
        return f"Mandi request failed: {str(e)}"
    
    except UnexpectedModelBehavior as e:
        logger.warning("Mandi request exceeded retry limit")
        return "Sorry, the mandi data is temporarily unavailable. Please try again later."
    
    except Exception as e:
        logger.error(f"Error getting mandi prices: {e}")
        raise ModelRetry(f"Unexpected error in mandi price request. {str(e)}")
