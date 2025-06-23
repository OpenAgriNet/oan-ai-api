from app.core.cache import cache
from helpers.utils import get_logger
from app.utils import _get_message_history, trim_history, format_message_pairs
from agents.suggestions import suggestions_agent
from langcodes import Language

logger = get_logger(__name__)


SUGGESTIONS_CACHE_TTL = 60*30 # 30 minutes

async def create_suggestions(session_id: str, target_lang: str = 'mr'):
    """
    Create and save suggestions for a session
    """
    logger.info(f"Getting suggestions for session {session_id}")

    target_lang_name = Language.get(target_lang).display_name(target_lang)

    history   = trim_history(await _get_message_history(session_id),
                             30_000,
                             include_tool_calls=False,
                             include_system_prompts=False
                             )
    message_pairs = "\n\n".join(format_message_pairs(history, 5))

    message       = f"**Conversation**\n\n{message_pairs}\n\n**Based on the conversation, suggest 3-5 questions the farmer can ask in {target_lang_name}.**"
    agent_run    = await suggestions_agent.run(message)
    suggestions = [x for x in agent_run.output]
    logger.info(f"Suggestions: {suggestions}")
    # Store suggestions in cache
    await cache.set(f"suggestions_{session_id}_{target_lang}", suggestions, ttl=SUGGESTIONS_CACHE_TTL)
    logger.info(f"Suggestions created and saved for session {session_id}")
    
    return {
        "status": "success",
        "message": f"Suggestions created and saved for session {session_id}"
    }