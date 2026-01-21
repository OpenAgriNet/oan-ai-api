from pydantic import BaseModel, Field
from typing import Literal
from pydantic_ai import Agent
from helpers.utils import get_prompt
from pydantic_ai.models import ModelSettings
from agents.models import LLM_MODEL


class QueryModerationResult(BaseModel):
    """Moderation result of the query."""
    category: Literal["valid_agricultural",
                      "invalid_non_agricultural",
                      "invalid_external_reference",
                      "invalid_compound_mixed",
                      "unsafe_illegal",
                      "political_controversial",
                      "role_obfuscation"] = Field(..., description="Moderation category of the user's message.")
    action: str = Field(..., description="Action to take on the query, always in English.")

    def __str__(self):
        category_str = self.category.replace("_", " ").title()
        return f"**Moderation Recommendation:** {self.action} ({category_str})"

moderation_agent = Agent(
    model=LLM_MODEL,
    name="Moderation Agent",
    system_prompt=get_prompt('moderation_system'),
    output_type=QueryModerationResult,
    retries=3,  
    model_settings=ModelSettings(
        max_tokens=800,  
        temperature=0.0,  
        parallel_tool_calls=False,
        thinking_config={
            "thinking_level": "MINIMAL"  
        }
    )
)
