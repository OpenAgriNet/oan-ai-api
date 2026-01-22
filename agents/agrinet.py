from pydantic_ai import Agent, RunContext
from helpers.utils import get_prompt, get_today_date_str
from agents.models import LLM_MODEL
from agents.tools import TOOLS
from agents.deps import FarmerContext


agrinet_agent = Agent(
    model=LLM_MODEL,
    name="AgriHelp Assistant",
    output_type=str,
    deps_type=FarmerContext,
    retries=1,
    tools=TOOLS,
    end_strategy='exhaustive',
    model_settings={
        "temperature": 0.2,
        "thinking_config": {
            "thinking_level": "MINIMAL"
        }
    }
)

# Use dynamic system prompt like old backend
@agrinet_agent.system_prompt
def dynamic_system_prompt(ctx: RunContext[FarmerContext]) -> str:
    """Dynamic system prompt based on context"""
    lang = ctx.deps.lang_code if ctx.deps else "en"
    return get_prompt(lang, context={'today_date': get_today_date_str()})