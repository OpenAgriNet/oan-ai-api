import uuid
from datetime import datetime, timezone
from helpers.utils import get_logger
import requests
from pydantic import BaseModel, AnyHttpUrl, Field
from typing import List, Optional, Dict, Any
from pydantic_ai import ModelRetry, UnexpectedModelBehavior, RunContext
from agents.deps import FarmerContext

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

# -----------------------
# Address & Contact Models
# -----------------------
class Address(BaseModel):
    address: str
    district: str
    region: str
    taluka: str
    vilage: str
    pinCode: str

    def __str__(self) -> str:
        return f"{self.address}, {self.vilage}, {self.taluka}, {self.district}, {self.region} - {self.pinCode}"

class Contact(BaseModel):
    person: str
    email: str
    phone: str
    webUrl: str

    def __str__(self) -> str:
        return f"Contact: {self.person}\nPhone: {self.phone}\nEmail: {self.email}"

# -----------------------
# Price & Rating Models
# -----------------------
class Price(BaseModel):
    currency: str
    value: str
    unit: str

    def __str__(self) -> str:
        return f"{self.currency} {self.value} {self.unit}"

class Tag(BaseModel):
    descriptor: Descriptor
    value: str

class TagList(BaseModel):
    list: List[Tag]

# -----------------------
# Fulfillment Models
# -----------------------
class Status(BaseModel):
    id: str
    code: str

class Category(BaseModel):
    id: str
    name: str
    descriptor: Descriptor

class FulfillmentLocation(BaseModel):
    id: str
    gps: str

class Fulfillment(BaseModel):
    id: str
    type: str
    status: List[Status]
    locations: FulfillmentLocation
    categories: List[Category]

# -----------------------
# Item & Provider Models
# -----------------------
class Item(BaseModel):
    id: str
    descriptor: Descriptor
    address: Address
    contact: Contact
    price: Price
    rating: str
    creator: Descriptor
    fulfillment_ids: List[str]
    status: List[str]
    category_ids: List[str]
    tags: List[TagList]

    def __str__(self) -> str:
        lines = []
        lines.append(f"Warehouse: {self.descriptor.name}")
        lines.append(f"Description: {self.descriptor.short_desc}")
        lines.append(f"Address: {self.address}")
        lines.append(f"{self.contact}")
        lines.append(f"Price: {self.price}")
        lines.append(f"Rating: {self.rating}")
        
        if self.tags:
            for tag_list in self.tags:
                for tag in tag_list.list:
                    lines.append(f"{tag.descriptor.code}: {tag.value}")
        
        return "\n".join(lines)

class Provider(BaseModel):
    id: str
    descriptor: Descriptor
    fulfillments: List[Fulfillment]
    items: List[Item]

    def __str__(self) -> str:
        lines = []
        lines.append(f"Provider: {self.descriptor.name}")
        lines.append(f"Description: {self.descriptor.short_desc}")
        
        if self.items:
            lines.append("\nWarehouses:")
            for idx, item in enumerate(self.items, start=1):
                item_str = str(item).replace("\n", "\n    ") 
                lines.append(f"  {idx}. {item_str}")
                lines.append("") 
        
        return "\n".join(lines)

# -----------------------
# Catalog & Message Models
# -----------------------
class Catalog(BaseModel):
    descriptor: Descriptor
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

class WarehouseResponse(BaseModel):
    context: Context
    responses: List[ResponseItem]

    def _has_warehouse_data(self) -> bool:
        """Check if there are any responses with providers that have items."""
        for response in self.responses:
            for provider in response.message.catalog.providers:
                if provider.items and len(provider.items) > 0:
                    return True
        return False
    
    def __str__(self) -> str:
        lines = []
        lines.append("> Warehouse Data")
        
        has_warehouse_data = self._has_warehouse_data()
        if not self.responses or not has_warehouse_data:
            lines.append("No warehouse data found for the requested location.")
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
class WarehouseRequest(BaseModel):
    """WarehouseRequest model for the warehouse API.
    
    Args:
        latitude (float): Latitude of the location
        longitude (float): Longitude of the location
    """
    latitude: float = Field(..., description="Latitude of the location")
    longitude: float = Field(..., description="Longitude of the location")
    
    def get_payload(self) -> Dict[str, Any]:
        """
        Convert the WarehouseRequest object to a dictionary.
        
        Returns:
            Dict[str, Any]: The dictionary representation of the WarehouseRequest object
        """
        now = datetime.today()
        
        return {
            "context": {
                "domain": "advisory:mh-vistaar",
                "location": {
                    "country": {
                        "name": "IND"
                    }
                },
                "action": "search",
                "version": "1.1.0",
                "bap_id": "prodseekernetwork.mahapocra.gov.in",
                "bap_uri": "https://prodseekernetwork.mahapocra.gov.in",
                "message_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "timestamp": now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            },
            "message": {
                "intent": {
                    "category": {
                        "descriptor": {
                            "code": "warehouse"
                        }
                    },
                    "item": {
                        "descriptor": {
                            "name": "none"
                        }
                    },
                    "fulfillment": {
                        "stops": [
                            {
                                "location": {
                                    "gps": f"{self.latitude}, {self.longitude}"
                                },
                                "time": {
                                    "range": {
                                        "start": now.strftime('%Y-%m-%dT00:00:00Z')
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }

def warehouse_data(latitude: float, longitude: float) -> str:
    """Get Warehouse data for a specific location.

    Args:
        latitude (float): Latitude of the location
        longitude (float): Longitude of the location
    
    Returns:
        str: The warehouse data for the specific location
    """
    try:
        payload = WarehouseRequest(latitude=latitude, longitude=longitude).get_payload()
        response = requests.post(
            "https://prodseekerclient.mahapocra.gov.in/search",
            json=payload,
            timeout=(10, 15)
        )
        
        if response.status_code != 200:
            logger.error(f"Warehouse API returned status code {response.status_code}")
            return "Warehouse service unavailable. Retrying"
            
        warehouse_response = WarehouseResponse.model_validate(response.json())
        return str(warehouse_response)
                
    except requests.Timeout as e:
        logger.error(f"Warehouse API request timed out: {str(e)}")
        return "Warehouse request timed out. Please try again later."
    
    except requests.RequestException as e:
        logger.error(f"Warehouse API request failed: {e}")
        return f"Warehouse request failed: {str(e)}"
    
    except UnexpectedModelBehavior as e:
        logger.warning("Warehouse request exceeded retry limit")
        return "Warehouse data is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error getting warehouse data: {e}")
        raise ModelRetry(f"Unexpected error in warehouse request. {str(e)}")
        