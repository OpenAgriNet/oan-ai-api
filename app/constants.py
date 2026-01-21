"""
Application Constants

Tool-to-source mappings for attribution in chat responses.
"""

# Map tool names to their data sources
TOOL_SOURCE_MAP = {
    # Weather tools
    'get_current_weather': 'OpenWeatherMap',
    'get_weather_forecast': 'OpenWeatherMap',

    # Crop price tools (database-backed)
    'get_crop_price_in_marketplace': 'https://nmis.et/',
    'get_crop_price_quick': 'https://nmis.et/',
    'compare_crop_prices_nearby': 'https://nmis.et/',

    # Livestock price tools (database-backed)
    'get_livestock_price_in_marketplace': 'https://nmis.et/',
    'get_livestock_price_quick': 'https://nmis.et/',
    'compare_livestock_prices_nearby': 'https://nmis.et/',
    
    # Marketplace listing tools (database-backed)
    'list_active_crop_marketplaces': 'https://nmis.et/',
    'list_active_livestock_marketplaces': 'https://nmis.et/',
    'list_crops_in_marketplace': 'https://nmis.et/',
    'list_livestock_in_marketplace': 'https://nmis.et/',
    'find_crop_marketplace_by_name': 'https://nmis.et/',
    'find_livestock_marketplace_by_name': 'https://nmis.et/',
    'list_crop_marketplaces_by_region': 'https://nmis.et/',
    'list_livestock_marketplaces_by_region': 'https://nmis.et/',
}
