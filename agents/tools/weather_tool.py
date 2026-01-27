from __future__ import annotations
import os

import httpx
from datetime import datetime, timezone
from typing import List, Literal
from pydantic import BaseModel, Field
from pydantic_ai import Tool
from agents.tools.maps import forward_geocode
from helpers.utils import get_logger
from app.core.cache import cache
logger = get_logger(__name__)

CURRENT_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

API_KEY = os.getenv("OPENWEATHERMAP_API_KEY", "")
TIMEOUT = 10.0
WEATHER_CACHE_TTL = 15 * 60  # 15 minutes

# -----------------------
# Current Weather Tool
# -----------------------
class CurrentWeatherInput(BaseModel):
    location: str = Field(..., description="Location name (e.g., city, town)")
    units: Literal["metric", "imperial"] = "metric"
    
class CurrentWeather(BaseModel):
    timestamp: int
    temperature: float
    feels_like: float
    humidity: int
    pressure: int
    wind_speed: float
    wind_direction: int
    clouds: int
    visibility: int
    description: str
    source: str = "OpenWeatherMap"


async def get_current_weather(input: CurrentWeatherInput) -> CurrentWeather:
    """
    Always Add source as OpenWeatherMap in your response.
    Get the CURRENT weather conditions for a specific latitude and longitude.
    Use this tool ONLY when the user asks about the weather right now or current conditions."""    
    try:
        location = await forward_geocode(input.location)
        
        # Create cache key based on location and units
        cache_key = f"weather:current:{location.latitude}:{location.longitude}:{input.units}"
        
        # Try to get from cache first
        cached_data = await cache.get(cache_key)
        if cached_data:
            logger.info(f"Cache HIT for current weather: {cache_key}")
            return CurrentWeather(**cached_data)
        
        logger.info(f"Cache MISS for current weather: {cache_key}")
        
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                CURRENT_WEATHER_URL,
                params={
                    "lat": location.latitude,
                    "lon": location.longitude,
                    "appid": API_KEY,
                    "units": input.units,
                    "lang": "en",
                },
            )
            response.raise_for_status()
            data = response.json()
            logger.info(f"Fetched current weather for ({location.latitude}, {location.longitude}, units={input.units}, language=en)")
            logger.info(f"Current weather data: {data}")
            
            weather = CurrentWeather(
                timestamp=data["dt"],
                temperature=data["main"]["temp"],
                feels_like=data["main"]["feels_like"],
                humidity=data["main"]["humidity"],
                pressure=data["main"]["pressure"],
                wind_speed=data["wind"]["speed"],
                wind_direction=data["wind"].get("deg", 0),
                clouds=data["clouds"]["all"],
                visibility=data.get("visibility", 10_000),
                description=data["weather"][0]["description"],
                source="OpenWeatherMap",
            )
            
            # Cache the result
            await cache.set(cache_key, weather.model_dump(), ttl=WEATHER_CACHE_TTL)
            logger.info(f"Cached current weather for {WEATHER_CACHE_TTL}s: {cache_key}")
            
            return weather
    except httpx.HTTPStatusError as e:
        logger.error(f"Weather API error: {e.response.status_code} - {e.response.text}")
        raise Exception(f"Unable to fetch weather data: {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error(f"Weather API request error: {e}")
        raise Exception("Unable to connect to weather service")
    except Exception as e:
        logger.error(f"Unexpected error fetching weather: {e}")
        raise



# ------------------------
# Weather Forecast Tool
# ------------------------
class ForecastInput(BaseModel):
    location: str = Field(..., description="Location name (e.g., city, town)")
    units: Literal["metric", "imperial"] = "metric"
class HourlyForecast(BaseModel):
    timestamp: int
    temperature: float
    feels_like: float
    humidity: int
    wind_speed: float
    precipitation_probability: float
    description: str
    source: str = "OpenWeatherMap"


class DailyForecast(BaseModel):
    date: int
    min_temp: float
    max_temp: float
    avg_temp: float
    avg_humidity: float
    avg_wind_speed: float
    precipitation_probability: float
    description: str
    source: str = "OpenWeatherMap"


class WeatherForecast(BaseModel):
    hourly: List[HourlyForecast]
    daily: List[DailyForecast]
    source: str = "OpenWeatherMap"



async def get_weather_forecast(input: ForecastInput) -> str:
    """Get the WEATHER FORECAST for a location.
    Use this tool when the user asks about future weather, tomorrow, or the coming days.
    Returns a human-readable summary optimized for quick understanding."""
    try:
        location = await forward_geocode(input.location)
        
        # Create cache key based on location and units
        cache_key = f"weather:forecast:{location.latitude}:{location.longitude}:{input.units}"
        
        # Try to get from cache first
        cached_data = await cache.get(cache_key)
        if cached_data:
            logger.info(f"Cache HIT for weather forecast: {cache_key}")
            return cached_data
        
        logger.info(f"Cache MISS for weather forecast: {cache_key}")
        
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                FORECAST_URL,
                params={
                    "lat": location.latitude,
                    "lon": location.longitude,
                    "appid": API_KEY,
                    "units": input.units,
                    "lang": "en",
                },  
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Weather forecast API error: {e.response.status_code} - {e.response.text}")
        raise Exception(f"Unable to fetch weather forecast: {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error(f"Weather forecast API request error: {e}")
        raise Exception("Unable to connect to weather service")
    except Exception as e:
        logger.error(f"Unexpected error fetching forecast: {e}")
        raise

    # Group data by day
    daily_map: dict = {}
    for item in data["list"]:
        date = datetime.fromtimestamp(item["dt"], tz=timezone.utc).date()
        daily_map.setdefault(date, []).append(item)

    # Build human-readable summary (limit to 5 days)
    unit_symbol = "°C" if input.units == "metric" else "°F"
    speed_unit = "m/s" if input.units == "metric" else "mph"
    
    lines = ["📅 Weather Forecast (Source: OpenWeatherMap)"]
    lines.append("")
    
    for date, items in sorted(daily_map.items())[:5]:
        temps = [i["main"]["temp"] for i in items]
        humidities = [i["main"]["humidity"] for i in items]
        winds = [i["wind"]["speed"] for i in items]
        rain_prob = max(i.get("pop", 0) for i in items) * 100
        description = items[len(items)//2]["weather"][0]["description"]  # mid-day description
        
        date_str = date.strftime("%a %d %b %Y")
        min_t, max_t = round(min(temps)), round(max(temps))
        avg_humidity = round(sum(humidities) / len(humidities))
        avg_wind = round(sum(winds) / len(winds), 1)
        
        lines.append(f"• {date_str}: {min_t}-{max_t}{unit_symbol}, {description}")
        lines.append(f"  Rain: {rain_prob:.0f}% | Humidity: {avg_humidity}% | Wind: {avg_wind}{speed_unit}")
    
    summary = "\n".join(lines)
    logger.info(summary)
    logger.info(f"Generated weather forecast summary for {len(daily_map)} days")
    
    # Cache the result
    await cache.set(cache_key, summary, ttl=WEATHER_CACHE_TTL)
    logger.info(f"Cached weather forecast for {WEATHER_CACHE_TTL}s: {cache_key}")
    
    return summary