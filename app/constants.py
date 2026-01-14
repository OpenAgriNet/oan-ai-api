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
    'compare_crop_prices_nearby': 'https://nmis.et/',

    # Livestock price tools (database-backed)
    'get_livestock_price_in_marketplace': 'https://nmis.et/',
    'compare_livestock_prices_nearby': 'https://nmis.et/',
}
