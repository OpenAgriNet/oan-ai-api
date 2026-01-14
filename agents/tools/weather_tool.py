from __future__ import annotations
import os

import httpx
from datetime import datetime, timezone
from typing import List, Literal
from pydantic import BaseModel, Field
from pydantic_ai import Tool
from helpers.utils import get_logger

logger = get_logger(__name__)

CURRENT_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

API_KEY = os.getenv("OPENWEATHERMAP_API_KEY", "")
TIMEOUT = 10.0

# -----------------------
# Current Weather Tool
# -----------------------
class CurrentWeatherInput(BaseModel):
    latitude: float = Field(..., description="Latitude in decimal degrees")
    longitude: float = Field(..., description="Longitude in decimal degrees")
    units: Literal["metric", "imperial"] = "metric"
    language: Literal["en", "am"] = "en"
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
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(
            CURRENT_WEATHER_URL,
            params={
                "lat": input.latitude,
                "lon": input.longitude,
                "appid": API_KEY,
                "units": input.units,
                "lang": input.language,
            },
        )
        response.raise_for_status()
        data = response.json()
        logger.info(f"Fetched current weather for ({input.latitude}, {input.longitude}, units={input.units}, language={input.language})")
        logger.info(f"Current weather data: {data}")
        return CurrentWeather(
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



# ------------------------
# Weather Forecast Tool
# ------------------------
class ForecastInput(BaseModel):
    latitude: float
    longitude: float
    units: Literal["metric", "imperial"] = "metric"
    language: Literal["en", "am"] = "en"

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



async def get_weather_forecast(input: ForecastInput) -> WeatherForecast:
    """Get the WEATHER FORECAST (hourly and daily) for a location.
    Use this tool when the user asks about future weather, tomorrow, or the coming days."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(
            FORECAST_URL,
            params={
                "lat": input.latitude,
                "lon": input.longitude,
                "appid": API_KEY,
                "units": input.units,
                "lang": input.language,
            },
        )
        response.raise_for_status()
        data = response.json()

    hourly = [
        HourlyForecast(
            timestamp=item["dt"],
            temperature=item["main"]["temp"],
            feels_like=item["main"]["feels_like"],
            humidity=item["main"]["humidity"],
            wind_speed=item["wind"]["speed"],
            precipitation_probability=item.get("pop", 0.0),
            description=item["weather"][0]["description"],
        )
        for item in data["list"][:16]  # next 48 hours
    ]

    daily_map: dict = {}

    for item in data["list"]:
        date = datetime.fromtimestamp(item["dt"], tz=timezone.utc).date()
        daily_map.setdefault(date, []).append(item)

    daily = []
    for date, items in sorted(daily_map.items())[:8]:
        temps = [i["main"]["temp"] for i in items]
        humidities = [i["main"]["humidity"] for i in items]
        winds = [i["wind"]["speed"] for i in items]

        daily.append(
            DailyForecast(
                date=int(
                    datetime.combine(date, datetime.min.time())
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                ),
                min_temp=min(temps),
                max_temp=max(temps),
                avg_temp=sum(temps) / len(temps),
                avg_humidity=sum(humidities) / len(humidities),
                avg_wind_speed=sum(winds) / len(winds),
                precipitation_probability=max(i.get("pop", 0) for i in items),
                description=items[0]["weather"][0]["description"],
            )
        )
    logger.info(f"Generated weather forecast with {len(hourly)} hourly and {len(daily)} daily entries")
    return WeatherForecast(hourly=hourly, daily=daily)