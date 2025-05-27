from pydantic_ai import Agent
from helpers.utils import get_prompt, get_today_date_str
from agents.models import LLM_MODEL
from agents.tools import TOOLS
from pydantic_ai.settings import ModelSettings
from agents.deps import FarmerContext


agrinet_agent = Agent(
    model=LLM_MODEL,
    name="Vistaar Agent",
    output_type=str,
    deps=FarmerContext,
    retries=3,
    tools=TOOLS,
    system_prompt=get_prompt('agrinet_system', context={'today_date': get_today_date_str()}),
    end_strategy='exhaustive',
    model_settings=ModelSettings(
        max_tokens=8192,
        parallel_tool_calls=True,
   )
)