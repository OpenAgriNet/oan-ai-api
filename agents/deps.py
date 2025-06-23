from typing import Optional
from pydantic import BaseModel, Field
from langcodes import Language


class FarmerContext(BaseModel):
    """Context for the farmer agent."""
    query: str = Field(description="The user's question.")
    lang_code: str = Field(description="The language code of the user's question.", default='mr')
    moderation_str: Optional[str] = Field(default=None, description="The moderation result of the user's question.")

    def update_moderation_str(self, moderation_str: str):
        """Update the moderation result of the user's question."""
        self.moderation_str = moderation_str

    def _language_string(self):
        """Get the language string for the agrinet agent."""
        if self.lang_code:
            return f"**Selected Language:** {Language.get(self.lang_code).display_name()}"
        else:
            return None
    
    def _query_string(self):
        """Get the query string for the agrinet agent."""
        return "**User:** " + '"' + self.query + '"'

    def _moderation_string(self):
        """Get the moderation string for the agrinet agent."""
        if self.moderation_str:
            return self.moderation_str
        else:
            return None
    
    def get_user_message(self):
        """Get the user message for the agrinet agent."""
        strings = [self._query_string(), self._language_string(), self._moderation_string(),]
        return "\n".join([x for x in strings if x])

    
# Example:
# Query: "What is the weather in Mumbai?"
# Moderation Result: "This is a valid agricultural question."
# Selected Language: Marathi
