# """
# Tools for the OAN AI API.
# """
# from agents.tools.search import search_documents
# from agents.tools.weather import weather_forecast
# from agents.tools.mandi import mandi_prices
# from agents.tools.warehouse import warehouse_data
# from agents.tools.maps import forward_geocode  
# from pydantic_ai import Tool
# from agents.tools.terms import search_terms
# from agents.tools.scheme import get_scheme_info

# TOOLS = [
#     Tool(
#         search_terms,
#         takes_ctx=False,
#     ),
#     Tool(
#         search_documents,
#         takes_ctx=False, # No context is needed for this tool
#     ),
#     Tool(
#         weather_forecast,
#         takes_ctx=False,
#     ),
#     Tool(
#         mandi_prices,
#         takes_ctx=False,
#     ),
#     Tool(
#         warehouse_data,
#         takes_ctx=False,
#     ),
#     Tool(
#         forward_geocode,
#         takes_ctx=False,
#     ),
#     Tool(
#         get_scheme_info,
#         takes_ctx=False,
#     ),
# ]


from agents.tools.maps import forward_geocode, reverse_geocode
from agents.tools.weather_tool import get_current_weather, get_weather_forecast
from agents.tools.crop import list_crops_in_marketplace, compare_crop_prices_nearby, get_crop_price_in_marketplace
from agents.tools.Livestock import list_livestock_in_marketplace, compare_livestock_prices_nearby, get_livestock_price_in_marketplace
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
from agents.tools.Regions import detect_crop_region, detect_livestock_region


from pydantic_ai import Tool

# Tool list for agent registration
TOOLS = [
    # --- Weather tools ---
    Tool(get_current_weather),
    Tool(get_weather_forecast),
    
    # --- geolocation tools ---
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
    Tool(list_crops_in_marketplace),
    Tool(get_crop_price_in_marketplace),
    Tool(compare_crop_prices_nearby),
    
    # --- Livestock tools ---
    Tool(list_livestock_in_marketplace),
    Tool(get_livestock_price_in_marketplace),
    Tool(compare_livestock_prices_nearby),
]
