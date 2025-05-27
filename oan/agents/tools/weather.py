import uuid
from datetime import datetime, timedelta, timezone
from helpers.utils import get_logger
import requests
from pydantic import BaseModel, AnyHttpUrl, Field
from typing import List, Optional, Dict, Any, Tuple
from dateutil import parser
from dateutil.parser import ParserError
from pydantic_ai import ModelRetry, UnexpectedModelBehavior

logger = get_logger(__name__)

# -----------------------
# Images
# -----------------------
class Image(BaseModel):
    url: AnyHttpUrl

# -----------------------
# Descriptor
# -----------------------
class Descriptor(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    short_desc: Optional[str] = None
    long_desc: Optional[str] = None
    images: Optional[List[Image]] = None

    def is_date(self) -> Tuple[bool, Optional[datetime]]:
        """Check if the descriptor code or name contains a parseable date.
        
        Returns:
            Tuple[bool, Optional[datetime]]: (True, datetime_obj) if date found, (False, None) if not
        """
        try:
            # Try code first as it's more likely to contain the date
            if self.code:
                return True, parser.parse(self.code, fuzzy=True)
            # Try name if code didn't work
            if self.name:
                return True, parser.parse(self.name, fuzzy=True)
            return False, None
        except (ParserError, TypeError, ValueError):
            return False, None

    def __str__(self) -> str:
        """Return the 'name' or 'code' if present, else empty."""
        if self.name:
            return self.name
        elif self.code:
            return self.code
        return ""

# -----------------------
# Country & Location
# -----------------------
class Country(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None

class Location(BaseModel):
    country: Optional[Country] = None

# -----------------------
# Context
# -----------------------
class Context(BaseModel):
    ttl: Optional[str] = None
    action: str
    timestamp: str
    message_id: str
    transaction_id: str
    domain: str
    version: str
    # Mark optional if not always present
    bap_id: Optional[str] = None
    bap_uri: Optional[AnyHttpUrl] = None
    bpp_id: Optional[str] = None
    bpp_uri: Optional[AnyHttpUrl] = None
    country: Optional[str] = None
    city: Optional[str] = None
    location: Optional[Location] = None

# -----------------------
# TagItem & Tag
# -----------------------
class TagItem(BaseModel):
    descriptor: Descriptor
    value: str

    def __str__(self) -> str:
        desc_name = self.descriptor.name or self.descriptor.code or "Tag"
        return f"{desc_name}: {self.value}"

class Tag(BaseModel):
    descriptor: Descriptor
    list: List[TagItem]

    def __str__(self) -> str:
        """Example format:
           TagGroupName:
               TagItem1
               TagItem2
        """
        heading = self.descriptor.name or self.descriptor.code or "Tag Group"
        items_str = "\n      ".join(str(tag_item) for tag_item in self.list)
        return f"{heading}:\n      {items_str}"

# -----------------------
# TimeRange, Time, Stop, Fulfillment
# -----------------------
class TimeRange(BaseModel):
    start: str
    end: str

class Time(BaseModel):
    range: TimeRange

class Stop(BaseModel):
    time: Time

class Fulfillment(BaseModel):
    id: str
    stops: Optional[List[Stop]] = None

    def __str__(self) -> str:
        lines = [f"Fulfillment ID: {self.id}"]
        if self.stops:
            lines.append("  Stops:")
            for stop in self.stops:
                lines.append(f"    - Start: {stop.time.range.start}, End: {stop.time.range.end}")
        return "\n".join(lines)

# -----------------------
# Category
# -----------------------
class Category(BaseModel):
    id: str
    descriptor: Descriptor

    def __str__(self) -> str:
        return self.descriptor.name or self.id

# -----------------------
# Item
# -----------------------
class Item(BaseModel):
    id: str
    descriptor: Descriptor
    matched: bool
    recommended: bool
    category_ids: Optional[List[str]] = None
    fulfillment_ids: Optional[List[str]] = None
    tags: Optional[List[Tag]] = None

    def __str__(self) -> str:
        lines = []
        # Item name / ID heading
        lines.append(f"**Item:** {self.descriptor.name or self.id}")

        # Short/Long
        if self.descriptor.short_desc:
            lines.append(f"  Short: {self.descriptor.short_desc}")
        if self.descriptor.long_desc:
            # strip() to remove trailing newlines
            lines.append(f"  Long: {self.descriptor.long_desc.strip()}")

        # Show tags
        if self.tags:
            lines.append("  Tags:")
            for t in self.tags:
                tag_str = str(t).replace("\n", "\n    ")
                lines.append(f"    {tag_str}")

        return "\n".join(lines)

# -----------------------
# Provider
# -----------------------
class Provider(BaseModel):
    id: str
    descriptor: Descriptor
    categories: Optional[List[Category]] = None
    fulfillments: Optional[List[Fulfillment]] = None
    items: Optional[List[Item]] = None

    def __str__(self) -> str:
        lines = []
        lines.append(f"Provider: {self.descriptor.name or self.id}")

        if self.categories:
            lines.append("  Categories:")
            for cat in self.categories:
                lines.append(f"    - {cat}")

        if self.fulfillments:
            lines.append("  Fulfillments:")
            for f in self.fulfillments:
                f_str = str(f).replace("\n", "\n    ")
                lines.append(f"    {f_str}")

        if self.items:
            lines.append("  Items:")
            for item in self.items:
                item_str = str(item).replace("\n", "\n    ")
                lines.append(f"    {item_str}")

        return "\n".join(lines)

# -----------------------
# Catalog
# -----------------------
class Catalog(BaseModel):
    descriptor: Descriptor
    providers: List[Provider]

    def __str__(self) -> str:
        lines = []
        lines.append(f"Catalog: {self.descriptor.name or 'N/A'}")
        if self.providers:
            lines.append("Providers:")
            for provider in self.providers:
                provider_str = str(provider).replace("\n", "\n  ")
                lines.append(f"  {provider_str}")
        return "\n".join(lines)

# -----------------------
# Message & ResponseItem
# -----------------------
class Message(BaseModel):
    catalog: Catalog

    def __str__(self) -> str:
        return str(self.catalog)

class ResponseItem(BaseModel):
    context: Context
    message: Message

    def __str__(self) -> str:
        # Optionally, you can logger.info context info here or just the catalog:
        # e.g. f"Context: {self.context.transaction_id}\n{self.message}"
        return str(self.message)

# -----------------------
# Weather Response
# -----------------------
class WeatherResponse(BaseModel):
    context: Context
    responses: List[ResponseItem]

    def validate_dates(self, request_payload: Dict[str, Any]) -> bool:
        """
        Validate if the weather data is current based on the requested dates.
        At least one date in the response should fall within the requested range.
        
        Args:
            request_payload (Dict[str, Any]): The original request payload containing the date range
            
        Returns:
            bool: True if at least one valid date is found, False if no dates are within range
        """
        try:
            # Get requested date range from payload and ensure they're timezone aware
            request_start = parser.parse(request_payload["message"]["intent"]["item"]["time"]["range"]["start"])
            if request_start.tzinfo is None:
                request_start = request_start.replace(tzinfo=timezone.utc)
                
            request_end = parser.parse(request_payload["message"]["intent"]["item"]["time"]["range"]["end"])
            if request_end.tzinfo is None:
                request_end = request_end.replace(tzinfo=timezone.utc)
            
            # Get response timestamp and ensure it's timezone aware
            response_time = parser.parse(self.context.timestamp)
            if response_time.tzinfo is None:
                response_time = response_time.replace(tzinfo=timezone.utc)
            
            # Check if we have any responses
            if not self.responses:
                logger.warning("No weather data found in response")
                return False
            
            # Check if response timestamp is within 1 hour of request start time
            time_diff = abs((response_time - request_start).total_seconds())
            if time_diff > 3600:  # 3600 seconds = 1 hour
                logger.warning(f"Weather data may be outdated. Response time: {response_time}, Request start: {request_start}")
                return False
                
            # Track all dates found and their validity
            dates_found = []
            valid_dates = []
            
            # Iterate through all providers and their items to find dates
            for response in self.responses:
                for provider in response.message.catalog.providers:
                    for item in provider.items or []:
                        for tag in item.tags or []:
                            is_date, date_obj = tag.descriptor.is_date()
                            if is_date and date_obj:
                                # Ensure the found date is timezone aware
                                if date_obj.tzinfo is None:
                                    date_obj = date_obj.replace(tzinfo=timezone.utc)
                                dates_found.append(date_obj)
                                # Check if the date is within our request range
                                if request_start <= date_obj <= request_end:
                                    valid_dates.append(date_obj)
            
            # Log the results
            if dates_found:
                logger.info(f"Found {len(dates_found)} dates in response, {len(valid_dates)} within requested range")
                if valid_dates:
                    logger.info(f"Valid dates: {', '.join(d.isoformat() for d in valid_dates)}")
                else:
                    logger.warning(f"All dates found were outside range [{request_start} - {request_end}]")
                    logger.warning(f"Found dates: {', '.join(d.isoformat() for d in dates_found)}")
            else:
                logger.warning("No dates found in weather data")
            
            # Return True if we found at least one valid date
            return len(valid_dates) > 0
            
        except Exception as e:
            logger.error(f"Error validating weather dates: {e}")
            return False


    def _has_weather_data(self) -> bool:
        """Check if there are any responses with providers that have items."""
        for response in self.responses:
            for provider in response.message.catalog.providers:
                if provider.items and len(provider.items) > 0:
                    return True
        return False
    
    def __str__(self) -> str:
        lines = []
        lines.append("> Weather Forecast Data")
    
        # Check if there are any responses with providers that have items
        has_weather_data = self._has_weather_data()
        if len(self.responses) == 0 or not has_weather_data:
            lines.append("No weather data found for the requested location.")
            return "\n".join(lines)
        else:
            lines.append("Responses:")
            for idx, rsp in enumerate(self.responses, start=1):
                rsp_str = str(rsp).replace("\n", "\n  ")
                lines.append(f"  Response {idx}:")
                lines.append(f"    {rsp_str}")
            return "\n".join(lines)

# -----------------------
# Weather Request
# -----------------------
class WeatherRequest(BaseModel):
    """WeatherRequest model for the weather forecast API.
    
    Args:
        latitude (float): Latitude of the location, example: 12.9716
        longitude (float): Longitude of the location, example: 77.5946
        days (int): Number of days to forecast, (defaults to 5)
    """
    latitude: float  = Field(..., description="Latitude of the location")
    longitude: float = Field(..., description="Longitude of the location")
    days: int        = Field(default=0, description="Number of days to forecast. Between 1 and 10")
    
    def get_payload(self) -> Dict[str, Any]:
        """
        Convert the WeatherRequest object to a dictionary compatible with MahaPoCRA Beckn API.
        
        Returns:
            Dict[str, Any]: The dictionary representation of the request payload.
        """
        now = datetime.today()
        
        return {
            "context": {
                "ttl": "PT10M",
                "action": "search",
                "timestamp": now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                "message_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "domain": "advisory:weather:mh-vistaar",
                "version": "1.1.0",
                "bap_id": "prodseekernetwork.mahapocra.gov.in",
                "bap_uri": "https://prodseekernetwork.mahapocra.gov.in",
                "location": {
                    "country": {"name": "India", "code": "IND"},
                }
            },
            "message": {
                "intent": {
                    "category": {
                        "descriptor": {
                            "name": "Weather-Forecast"
                        }
                    },
                    "item": {
                        "time": {
                            "range": {
                                "start": now.astimezone(timezone.utc).strftime('%Y-%m-%dT00:00:00Z'),
                                "end": (now + timedelta(days=self.days)).astimezone(timezone.utc).strftime('%Y-%m-%dT00:00:00Z')
                            }
                        }
                    },
                    "fulfillment": {
                        "stops": [
                            {"location": {"gps": f"{self.latitude}, {self.longitude}"}}
                        ]
                    }
                }
            }
        }
    
def weather_forecast(latitude: float, longitude: float) -> str:
    """Get Weather forecast for a specific location.

    Args:
        latitude (float): Latitude of the location
        longitude (float): Longitude of the location
    
    Returns:
        str: The weather forecast for the specific location
    """    
    try:        
        payload  = WeatherRequest(latitude=latitude, longitude=longitude).get_payload()
        response = requests.post("https://prodseekerclient.mahapocra.gov.in/search",
                                 json=payload,
                                 timeout=(10,15))
        
        if response.status_code != 200:
            logger.error(f"Weather API returned status code {response.status_code}")
            return "Weather service unavailable. Retrying"
            
        weather_response = WeatherResponse.model_validate(response.json())
            
        return str(weather_response)
                
    except requests.Timeout:
        logger.error("Weather API request timed out")
        return "Weather request timed out."
    except requests.RequestException as e:
        logger.error(f"Weather API request failed: {e}")
        return f"Weather request failed: {str(e)}"
    except UnexpectedModelBehavior as e:
        logger.warning("Weather request exceeded retry limit")
        return "Weather data is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error getting weather forecast: {e}")
        raise ModelRetry(f"Unexpected error in weather forecast. {str(e)}")