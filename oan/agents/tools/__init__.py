"""
Tools for the OAN AI API.
"""
from agents.tools.common import reasoning_tool, planning_tool
from agents.tools.search import search_documents
from agents.tools.weather import weather_forecast
from agents.tools.mandi import mandi_prices
from agents.tools.warehouse import warehouse_data
from agents.tools.maps import reverse_geocode, forward_geocode  
from pydantic_ai import Tool
from agents.tools.terms import search_terms

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
]
