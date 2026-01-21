from pydantic_ai import Agent
from helpers.utils import get_prompt, get_today_date_str
from agents.models import LLM_MODEL
from agents.tools import TOOLS
from pydantic_ai.settings import ModelSettings
from agents.deps import FarmerContext


agrinet_agent = Agent(
    model=LLM_MODEL,
    name="AgriHelp Assistant",
    output_type=str,
    deps_type=FarmerContext,
    retries=3,  # Increased from 1 to handle output validation failures
    tools=TOOLS,
    system_prompt=get_prompt('en', context={'today_date': get_today_date_str()}),
    end_strategy='exhaustive',
    model_settings=ModelSettings(
        max_tokens=300,  # Increased from 200 to avoid truncating responses
        temperature=0.2,  # Lower temperature for more deterministic, faster responses (same as old backend)
        parallel_tool_calls=True,
        # thinking_config with MINIMAL level for fastest responses
        # This reduces internal reasoning overhead for faster generation
        thinking_config={
            "thinking_level": "MINIMAL"
        }
    )
)