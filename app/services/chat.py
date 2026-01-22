from typing import AsyncGenerator
import json
import time
import os
from agents.agrinet import agrinet_agent
from app.services.moderation_classifier import moderation_classifier
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
from pydantic_ai.messages import ModelResponse, TextPart
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
    
    # ⏱️ STAGE 2: Pre-Moderation (User Input)
    enable_moderation = os.getenv("ENABLE_MODERATION", "false").lower() == "true"
    
    if enable_moderation:
        stage_start = time.perf_counter()
        try:
            pre_mod_result = moderation_classifier.classify(query, lang=target_lang)
            stage_time = (time.perf_counter() - stage_start) * 1000
            logger.info(f"⏱️ [TIMING] Pre-moderation: {stage_time:.2f}ms - {pre_mod_result.reason}")
            
            if not pre_mod_result.is_safe:
                logger.warning(f"User input blocked: {pre_mod_result.label} - {pre_mod_result.reason}")
                response_data = {
                    "response": "I'm sorry, but I cannot process this request as it contains potentially harmful content.",
                    "status": "blocked",
                    "moderation": {
                        "stage": "pre",
                        "label": pre_mod_result.label,
                        "reason": pre_mod_result.reason
                    }
                }
                yield json.dumps(response_data)
                return
                
        except Exception as e:
            logger.error(f"Pre-moderation failed: {e}. Continuing (fail-open).")
            stage_time = (time.perf_counter() - stage_start) * 1000
            logger.info(f"⏱️ [TIMING] Pre-moderation (failed): {stage_time:.2f}ms")
    else:
        logger.info(f"⏱️ [TIMING] Pre-moderation: DISABLED (0ms)")

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
    
    response_stream = await agrinet_agent.run(
            user_prompt=query,
            message_history=trimmed_history,
            deps=deps,
            usage_limits=UsageLimits(request_limit=200),
        )
    stage_time = (time.perf_counter() - stage_start) * 1000
    logger.info(f"⏱️ [TIMING] Main agent execution: {stage_time:.2f}ms")

    # ⏱️ STAGE 4.5: Post-Moderation (Agent Output)
    post_mod_blocked = False
    
    if enable_moderation:
        stage_start = time.perf_counter()
        try:
            post_mod_result = moderation_classifier.classify(str(response_stream.output), lang=target_lang)
            stage_time = (time.perf_counter() - stage_start) * 1000
            logger.info(f"⏱️ [TIMING] Post-moderation: {stage_time:.2f}ms - {post_mod_result.reason}")
            
            if not post_mod_result.is_safe:
                logger.warning(f"Response blocked: {post_mod_result.label} - {post_mod_result.reason}")
                post_mod_blocked = True
                final_response_text = "I cannot fulfill this request as the generated response was flagged as potentially unsafe."
            else:
                final_response_text = response_stream.output
                
        except Exception as e:
            logger.error(f"Post-moderation failed: {e}. Allowing response through (fail-open).")
            stage_time = (time.perf_counter() - stage_start) * 1000
            logger.info(f"⏱️ [TIMING] Post-moderation (failed): {stage_time:.2f}ms")
            final_response_text = response_stream.output
    else:
        final_response_text = response_stream.output

    # ⏱️ STAGE 5: Source extraction
    stage_start = time.perf_counter()
    if post_mod_blocked:
        sources = []
    else:
        sources = extract_sources_from_result(response_stream)
    stage_time = (time.perf_counter() - stage_start) * 1000
    logger.info(f"⏱️ [TIMING] Source extraction: {stage_time:.2f}ms")

    # ⏱️ STAGE 6: History update
    stage_start = time.perf_counter()
    new_messages = response_stream.new_messages()
    
    if post_mod_blocked:
        blocked_response = ModelResponse(parts=[TextPart(content=final_response_text)])
        messages = [
            *history,
            blocked_response
        ]
    else:
        messages = [
            *history,
            *new_messages
        ]
    
    # ⏱️ TOTAL PIPELINE TIME
    total_time = (time.perf_counter() - pipeline_start) * 1000
    logger.info(f"⏱️ [TIMING] ═══ TOTAL PIPELINE: {total_time:.2f}ms ═══")
    
    # Return complete response as JSON
    response_data = {
        "response": final_response_text,
        "status": "success"
    }
    
    if sources:
        response_data["sources"] = sources
    
    yield json.dumps(response_data)
    
    await update_message_history(session_id, messages)
    stage_time = (time.perf_counter() - stage_start) * 1000
    logger.info(f"⏱️ [TIMING] History update: {stage_time:.2f}ms")