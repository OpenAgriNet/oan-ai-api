from typing import AsyncGenerator
import json
import time
import os
from agents.agrinet import agrinet_agent
from agents.moderation import moderation_agent
from helpers.utils import get_logger
from app.utils import (
    update_message_history,
    trim_history,
    format_message_pairs
)
from app.utils import extract_sources_from_result
from dotenv import load_dotenv
from agents.deps import FarmerContext
from pydantic_ai import UsageLimits

load_dotenv()

logger = get_logger(__name__)

async def stream_chat_messages(
    query: str,
    session_id: str,
    source_lang: str,
    target_lang: str,
    user_id: str,
    history: list,
) -> AsyncGenerator[str, None]:
    """Async generator for streaming chat messages."""
    # ⏱️ START TIMING
    pipeline_start = time.perf_counter()
    
    # Generate a unique content ID for this query
    content_id = f"query_{session_id}_{len(history)//2 + 1}"
    
    # ⏱️ STAGE 1: Context preparation
    stage_start = time.perf_counter()
    deps = FarmerContext(
        query=query,
        lang_code=target_lang,
    )

    message_pairs = "\n\n".join(format_message_pairs(history, 3))
    if message_pairs:
        last_response = f"**Conversation**\n\n{message_pairs}\n\n---\n\n"
    else:
        last_response = ""
    
    user_message = f"{last_response}{deps.get_user_message()}"
    stage_time = (time.perf_counter() - stage_start) * 1000
    logger.info(f"⏱️ [TIMING] Context preparation: {stage_time:.2f}ms")
    
    # ⏱️ STAGE 2: Moderation (OPTIONAL - can be disabled for speed)
    # NOTE: Old backend doesn't have moderation - this adds 3-4 seconds overhead
    # Set ENABLE_MODERATION=false in .env to disable
    enable_moderation = os.getenv("ENABLE_MODERATION", "false").lower() == "true"
    
    if enable_moderation:
        stage_start = time.perf_counter()
        moderation_run = await moderation_agent.run(user_message)
        moderation_data = moderation_run.output
        stage_time = (time.perf_counter() - stage_start) * 1000
        logger.info(f"⏱️ [TIMING] Moderation agent: {stage_time:.2f}ms")
        deps.update_moderation_str(str(moderation_data))
    else:
        logger.info(f"⏱️ [TIMING] Moderation agent: DISABLED (0ms)")

    # ⏱️ STAGE 3: History trimming
    stage_start = time.perf_counter()
    trimmed_history = trim_history(
        history,
        max_tokens=60_000,
        include_system_prompts=True,
        include_tool_calls=True
    )
    stage_time = (time.perf_counter() - stage_start) * 1000
    logger.info(f"⏱️ [TIMING] History trimming: {stage_time:.2f}ms")

    # ⏱️ STAGE 4: Main agent execution
    stage_start = time.perf_counter()
    
    # Use simple query like old backend (not formatted deps.get_user_message())
    response_stream = await agrinet_agent.run(
            user_prompt=query,  # Simple query, not deps.get_user_message()
            message_history=trimmed_history,
            deps=deps,
            usage_limits=UsageLimits(request_limit=200),
        )
    stage_time = (time.perf_counter() - stage_start) * 1000
    logger.info(f"⏱️ [TIMING] Main agent execution: {stage_time:.2f}ms")
    
    # ⏱️ STAGE 5: Source extraction
    stage_start = time.perf_counter()
    sources = extract_sources_from_result(response_stream)
    stage_time = (time.perf_counter() - stage_start) * 1000
    logger.info(f"⏱️ [TIMING] Source extraction: {stage_time:.2f}ms")

    # ⏱️ STAGE 6: History update
    stage_start = time.perf_counter()
    new_messages = response_stream.new_messages()
    messages = [
        *history,
        *new_messages
    ]
    await update_message_history(session_id, messages)
    stage_time = (time.perf_counter() - stage_start) * 1000
    logger.info(f"⏱️ [TIMING] History update: {stage_time:.2f}ms")

    # ⏱️ TOTAL PIPELINE TIME
    total_time = (time.perf_counter() - pipeline_start) * 1000
    logger.info(f"⏱️ [TIMING] ═══ TOTAL PIPELINE: {total_time:.2f}ms ═══")
    
    # Return complete response as JSON (not mixed format)
    response_data = {
        "response": response_stream.output,
        "status": "success"
    }
    
    # Add sources if available
    if sources:
        response_data["sources"] = sources
    
    yield json.dumps(response_data)