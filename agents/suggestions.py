from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from typing import List
from helpers.utils import get_prompt
from agents.models import LLM_MODEL
from agents.tools.search import search_documents
from pydantic_ai import Tool


suggestions_agent = Agent(
    name="Suggestions Agent",
    model=LLM_MODEL,
    system_prompt=get_prompt('suggestions_system'),
    output_type=List[str],
    result_tool_name="suggestions",
    result_tool_description="A list of 3-5 suggested questions for the farmer to ask.",
    retries=1,
    end_strategy='exhaustive',
    tools=[
        Tool(
            search_documents,
            takes_ctx=False,
        )
    ],
    model_settings=ModelSettings(
        parallel_tool_calls=False, # Prevent multiple tool calls
    )
)