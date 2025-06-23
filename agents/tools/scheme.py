import uuid
from datetime import datetime, timezone
from helpers.utils import get_logger
import requests
from pydantic import BaseModel, AnyHttpUrl, Field
from typing import List, Optional, Dict, Any, Literal
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

# -----------------------
# Tag Models
# -----------------------
class TagItem(BaseModel):
    descriptor: Descriptor
    value: str
    display: bool = True

    def __str__(self) -> str:
        desc_name = self.descriptor.name or self.descriptor.code or "Tag"
        return f"{desc_name}: {self.value}"

class Tag(BaseModel):
    display: bool = True
    descriptor: Descriptor
    list: List[TagItem]

    def __str__(self) -> str:
        items_str = "\n      ".join(str(tag_item) for tag_item in self.list)
        return items_str

# -----------------------
# Item & Provider Models
# -----------------------
class Item(BaseModel):
    id: str
    descriptor: Descriptor
    tags: Optional[List[Tag]] = None

    def __str__(self) -> str:
        lines = []
        
        # Use the scheme name from the descriptor, fallback to id if not available
        scheme_name = self.descriptor.name or self.id
        lines.append(f"# Scheme: {scheme_name}")
        lines.append("")  # Add blank line after scheme name
        
        if self.tags:
            for tag in self.tags:
                for tag_item in tag.list:
                    # Show all tag items that have meaningful content
                    if tag_item.value and tag_item.value.strip() and tag_item.descriptor.name:
                        lines.append(f"## {tag_item.descriptor.name}")
                        lines.append(f"{tag_item.value}")
                        lines.append("")  # Add blank line after each section
        
        return "\n".join(lines)

class Provider(BaseModel):
    id: Optional[str] = None
    descriptor: Descriptor
    items: Optional[List[Item]] = None

    def __str__(self) -> str:
        lines = []
        if self.items:
            for item in self.items:
                lines.append(str(item))
        return "\n\n---\n\n".join(lines)

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
                lines.append(str(provider))
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

class SchemeResponse(BaseModel):
    context: Context
    responses: List[ResponseItem]

    def _has_scheme_data(self) -> bool:
        """Check if there are any responses with providers that have items."""
        for response in self.responses:
            for provider in response.message.catalog.providers:
                if provider.items and len(provider.items) > 0:
                    return True
        return False
    
    def __str__(self) -> str:
        lines = []
        
        has_scheme_data = self._has_scheme_data()
        if not self.responses or not has_scheme_data:
            lines.append("No scheme data found.")
            return "\n".join(lines)
            
        for idx, rsp in enumerate(self.responses, start=1):
            lines.append(str(rsp))
        return "\n".join(lines)

# -----------------------
# Request Model
# -----------------------
class SchemeRequest(BaseModel):
    """SchemeRequest model for the scheme API.
    
    Args:
        scheme_name (Optional[str]): Name of the scheme. Can be one of: "kcc", "pmkisan", "pmfby"
    """
    scheme_name: str
    
    def get_payload(self) -> Dict[str, Any]:
        """
        Convert the SchemeRequest object to a dictionary.
        
        Returns:
            Dict[str, Any]: The dictionary representation of the SchemeRequest object
        """
        now = datetime.today()
        
        return {
            "context": {
                "domain": "schemes:oan",
                "action": "search",
                "version": "1.1.0",
                "bap_id": os.getenv("BAP_ID"),
                "bap_uri": os.getenv("BAP_URI"),
                "message_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "timestamp": now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            },
            "message": {
                "intent": {
                    "category": {
                        "descriptor": {
                            "code": "schemes-agri"
                        }
                    },
                    "item": {
                        "descriptor": {
                            "name": self.scheme_name
                        }
                    }
                }
            }
        }

def get_scheme_info(scheme_name: Optional[Literal["kcc", "pmkisan", "pmfby"]] = None) -> str:
    """Retrieve detailed information about government agricultural schemes.
    
    This tool fetches comprehensive scheme data including benefits, eligibility criteria, 
    application process, and other relevant details for agricultural schemes. Use this 
    tool whenever users inquire about specific schemes or need general scheme information.

    Args:
        scheme_name (Optional[str]): Name of the scheme to retrieve. Options:
            - "kcc": Kisan Credit Card scheme
            - "pmkisan": Pradhan Mantri Kisan Samman Nidhi scheme  
            - "pmfby": Pradhan Mantri Fasal Bima Yojana scheme
            - None: Retrieve all available schemes

    Returns:
        str: Formatted scheme data including introduction, benefits, eligibility, 
             application process, and other relevant information.
    """
    try:
        # Convert None to empty string for the API request
        scheme_name_str = scheme_name or ""
        payload = SchemeRequest(scheme_name=scheme_name_str).get_payload()
        response = requests.post(
            os.getenv("BAP_ENDPOINT"),
            json=payload,
            timeout=(20, 30)
        )
        
        if response.status_code != 200:
            logger.error(f"Scheme API returned status code {response.status_code}")
            return "Scheme service unavailable. Retrying"
            
        scheme_response = SchemeResponse.model_validate(response.json())
        return str(scheme_response)
                
    except requests.Timeout as e:
        logger.error(f"Scheme API request timed out: {str(e)}")
        return "Scheme request timed out. Please try again later."
    
    except requests.RequestException as e:
        logger.error(f"Scheme API request failed: {e}")
        return f"Scheme request failed: {str(e)}"
    
    except UnexpectedModelBehavior as e:
        logger.warning("Scheme request exceeded retry limit")
        return "Scheme data is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error getting scheme data: {e}")
        raise ModelRetry(f"Unexpected error in scheme request. {str(e)}") 
