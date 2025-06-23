"""
Tools for the OAN AI API.
"""
from agents.tools.search import search_documents
from agents.tools.weather import weather_forecast
from agents.tools.mandi import mandi_prices
from agents.tools.warehouse import warehouse_data
from agents.tools.maps import forward_geocode  
from pydantic_ai import Tool
from agents.tools.terms import search_terms
from agents.tools.scheme import get_scheme_info

TOOLS = [
    Tool(
        search_terms,
        takes_ctx=False,
    ),
    Tool(
        search_documents,
        takes_ctx=False, # No context is needed for this tool
    ),
    Tool(
        weather_forecast,
        takes_ctx=False,
    ),
    Tool(
        mandi_prices,
        takes_ctx=False,
    ),
    Tool(
        warehouse_data,
        takes_ctx=False,
    ),
    Tool(
        forward_geocode,
        takes_ctx=False,
    ),
    Tool(
        get_scheme_info,
        takes_ctx=False,
    ),
]
