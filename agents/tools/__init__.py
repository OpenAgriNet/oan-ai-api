"""
Tools for the OAN AI API.
"""
# RAG tool (routes to Marqo or Cosdata based on config)
from agents.tools.rag_router import search_documents

# Geolocation tools
from agents.tools.maps import forward_geocode, reverse_geocode

# Weather tools
from agents.tools.weather_tool import get_current_weather, get_weather_forecast

# Crop tools
from agents.tools.crop import list_crops_in_marketplace, compare_crop_prices_nearby, get_crop_price_in_marketplace, get_crop_price_quick

# Livestock tools
from agents.tools.Livestock import list_livestock_in_marketplace, compare_livestock_prices_nearby, get_livestock_price_in_marketplace, get_livestock_price_quick

# Marketplace tools
from agents.tools.MarketPlace import (
    find_crop_marketplace_by_name,
    list_crop_marketplaces_by_region,
    find_nearest_crop_marketplaces,
    list_active_crop_marketplaces,
    find_livestock_marketplace_by_name,
    list_livestock_marketplaces_by_region,
    find_nearest_livestock_marketplaces,
    list_active_livestock_marketplaces
)

# Region tools
from agents.tools.Regions import detect_crop_region, detect_livestock_region

# Other tools
from agents.tools.terms import search_terms
from agents.tools.scheme import get_scheme_info

from pydantic_ai import Tool

TOOLS = [
    # --- RAG/Search tools ---
    Tool(search_documents),  # Routes to Marqo or Cosdata based on RAG_PROVIDER
    Tool(search_terms),
    Tool(get_scheme_info),

    # --- Weather tools ---
    Tool(get_current_weather),
    Tool(get_weather_forecast),

    # --- Geolocation tools ---
    Tool(forward_geocode),
    Tool(reverse_geocode),

    # --- Region tools ---
    Tool(detect_crop_region),
    Tool(detect_livestock_region),

    # --- Crop Marketplace tools ---
    Tool(list_active_crop_marketplaces),  # Cross-verification tool
    Tool(list_crop_marketplaces_by_region),
    Tool(find_crop_marketplace_by_name),
    Tool(find_nearest_crop_marketplaces),

    # --- Livestock Marketplace tools ---
    Tool(list_active_livestock_marketplaces),  # Cross-verification tool
    Tool(list_livestock_marketplaces_by_region),
    Tool(find_livestock_marketplace_by_name),
    Tool(find_nearest_livestock_marketplaces),

    # --- Crop tools ---
    Tool(get_crop_price_quick),  # FAST PATH: Use this first for direct crop+marketplace queries
    Tool(list_crops_in_marketplace),
    Tool(get_crop_price_in_marketplace),
    Tool(compare_crop_prices_nearby),

    # --- Livestock tools ---
    Tool(get_livestock_price_quick),  # FAST PATH: Use this first for direct livestock+marketplace queries
    Tool(list_livestock_in_marketplace),
    Tool(get_livestock_price_in_marketplace),
    Tool(compare_livestock_prices_nearby),
]
