import nest_asyncio
nest_asyncio.apply()
from celery import shared_task
from django.core.cache import cache
import json
from helpers.utils import get_logger
from oan_app.views.utils import _get_message_history, trim_history, format_message_pairs
from agents.suggestions import suggestions_agent
from langcodes import Language

logger = get_logger(__name__)


SUGGESTIONS_CACHE_TTL = 60*30 # 30 minutes

@shared_task(bind=True, name="create_suggestions", rate_limit='5/s')
def create_suggestions(self, session_id: str, target_lang: str = 'mr'):
    """
    Create and save suggestions for a session
    """
    logger.info(f"Getting suggestions for session {session_id}")

    target_lang_name = Language.get(target_lang).display_name(target_lang)

    history   = trim_history(_get_message_history(session_id),
                             30_000,
                             include_tool_calls=False,
                             include_system_prompts=False
                             )
    message_pairs = "\n\n".join(format_message_pairs(history, 5))

    message       = f"**Conversation**\n\n{message_pairs}\n\n**Based on the conversation, suggest 3-5 questions the farmer can ask in {target_lang_name}.**"
    agent_run    = suggestions_agent.run_sync(message)
    suggestions = [x for x in agent_run.output]
    logger.info(f"Suggestions: {suggestions}")
    # Store suggestions in cache
    cache.set(f"suggestions_{session_id}_{target_lang}", suggestions, timeout=SUGGESTIONS_CACHE_TTL)
    logger.info(f"Suggestions created and saved for session {session_id}")
    
    return {
        "status": "success",
        "message": f"Suggestions created and saved for session {session_id}"
    }