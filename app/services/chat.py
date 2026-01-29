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
from helpers.utils import get_logger, get_prompt, get_today_date_str
from pydantic_ai import UsageLimits
from app.services.fast_gemini import FastGeminiService, FastModerationService

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
    moderation_time = 0
    if enable_moderation:
        stage_start = time.perf_counter()
        
        # Phase 2 Optimization: Use FastModerationService (Lightweight)
        fast_mod = FastModerationService()
        mod_metrics = {}
        is_safe, category, action = await fast_mod.moderate(user_message, mod_metrics)
        
        moderation_data = json.dumps({"category": category, "action": action})
        moderation_time = mod_metrics.get('mod_time', (time.perf_counter() - stage_start) * 1000)
        logger.info(f"⏱️ [TIMING] Moderation agent (optimized): {moderation_time:.2f}ms")
        
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

    # ⏱️ STAGE 4: Main agent execution (Phase 3: FastGeminiService)
    stage_start = time.perf_counter()
    
    # Initialize Fast Service with correct language (sets system prompt)
    fast_chat = FastGeminiService(lang=target_lang)
    metrics = {}
    
    # Construct Full Prompt (History + Query)
    # user_message already contains history formatted in Stage 1
    # FastGeminiService handles System Prompt internally via __init__
    
    full_text = ""
    # Use generate_response to stream/accumulate text and execute tools
    async for chunk in fast_chat.generate_response(user_message, metrics):
        if chunk:
            full_text += chunk
            
    llm_exec_time = (time.perf_counter() - stage_start) * 1000
    logger.info(f"⏱️ [TIMING] Main agent execution (FastGemini): {llm_exec_time:.2f}ms")
    
    # Map FastGemini metrics to deps for the table
    if 'timings' in metrics:
        deps.timings = metrics['timings']
    
    # ⏱️ STAGE 5: Source extraction (Skipped for Speed/Direct API)
    # Direct API allows tool use but doesn't return structured sources object like Pydantic AI
    logger.info(f"⏱️ [TIMING] Source extraction: N/A (Direct API)")
    sources = [] 

    # ⏱️ STAGE 6: History update
    stage_start = time.perf_counter()
    
    # Manually construct new messages using Pydantic AI models to ensure compatibility
    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
    
    new_messages = [
        ModelRequest(parts=[UserPromptPart(content=query)]),
        ModelResponse(parts=[TextPart(content=full_text)])
    ]
    
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
        "response": full_text,
        "status": "success"
    }
    
    # Add sources if available
    if sources:
        response_data["sources"] = sources

    # 📊 GENERATE ASCII PERFORMANCE TABLE
    try:
        if 'timings' in metrics:
            deps.timings = metrics['timings']
            
        # ═══════════════════════════════════════════════════════
        # METRICS CALCULATION
        # ═══════════════════════════════════════════════════════
        
        # Calculate Tool Metrics
        tool_count = 0
        total_tool_time = 0
        
        # Pull from deps.timings which is populated by @log_execution_time
        if hasattr(deps, 'timings'):
            for t in deps.timings:
                if t.get('step') == 'tool_end':
                    total_tool_time += t.get('duration', 0)
                    tool_count += 1
        
        # Fallback: if deps.timings is somehow empty/missed, count from messages
        if tool_count == 0:
            # We don't have response_stream variable here in this scope based on provided snippet, 
            # assuming it was a mistake in the original code or variable from FullGeminiService.
            # But we have tool_calls in history/metrics if we dug deep. 
            # For now, rely on deps.timings.
            pass
        
        # Mapping metrics
        # llm_exec_time is captured above (Main Agent Execution)
        e2e_total = (time.perf_counter() - pipeline_start) * 1000
        
        # Prepare Moderation String
        mod_display = f"{moderation_time:.2f} ms" if enable_moderation else "Disabled"
        
        query_preview = query[:60] + "..." if len(query) > 60 else query
        
        log_lines = [
            f"\n{'═'*60}",
            f"📊 PERFORMANCE METRICS BREAKDOWN (TEXT MODE)",
            f"{'═'*60}",
            f"🔹 Query: {query_preview}",
            f"{'─'*60}",
            f"",
            f"📍 STAGE TIMINGS:",
            f"   🎤 STT Transcription:     {'N/A':>8}",
            f"   ⚡ LLM Total Time:        {llm_exec_time:>8.2f} ms",
            f"",
            f"   └─ LLM DETAILS:",
            f"      🛠️  Tool Calls:          {tool_count} calls",
            f"      ⚙️  Tool Processing:     {total_tool_time:>8.2f} ms",
            f"      ⚖️  Moderation:          {mod_display}",
            f"",
            f"   🔊 TTS Synthesis:         {'N/A':>8}",
            f"",
            f"{'─'*60}",
            f"📊 AGGREGATE METRICS:",
            f"   🔴 TOTAL E2E LATENCY:     {e2e_total:>8.2f} ms",
            f"{'═'*60}"
        ]
        
        for line in log_lines:
            logger.info(line)

        # Add metrics to response_data
        response_data["metrics"] = {
            "stt_transcription": "N/A",
            "llm_total_time": round(llm_exec_time, 2),
            "tool_calls": tool_count,
            "tool_processing": round(total_tool_time, 2),
            "moderation": round(moderation_time, 2) if enable_moderation else "Disabled",
            "tts_synthesis": "N/A",
            "total_e2e_latency": round(e2e_total, 2)
        }
            
    except Exception as e:
        logger.error(f"Error generating metrics table: {e}")

    yield json.dumps(response_data)