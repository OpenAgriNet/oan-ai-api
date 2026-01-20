"""
Production-Ready LLM Provider
"""

import asyncio
import time
from typing import AsyncGenerator, Optional, List, Dict

from app.utils import get_message_history, update_message_history
from helpers.utils import get_logger
from agents.agrinet import agrinet_agent as agent
from helpers.utils import get_prompt as get_system_prompt

logger = get_logger(__name__)


class LLMProvider:
    """Abstract base class for LLM providers"""

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        session_id: str,
        language: str = "en"
    ) -> AsyncGenerator[str, None]:
        raise NotImplementedError


class OpenRouterLLMProvider(LLMProvider):
    """
    OpenRouter LLM Provider with proper error handling
    Supports both streaming and non-streaming modes
    """

    def __init__(self, enable_streaming: bool = True):
        """
        Initialize LLM provider

        Args:
            enable_streaming: If True, streams chunks. If False, yields complete output.
                             Set to False if tool calling breaks with streaming.
        """
        self.enable_streaming = enable_streaming
        logger.info(f"LLM Provider initialized (streaming={'enabled' if enable_streaming else 'disabled'})")

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        session_id: str,
        language: str = "en",
    ) -> AsyncGenerator[str, None]:
        """
        Generate response from OpenRouter with tool support.
        Yields complete text (not streaming) due to tool calling.

        Args:
            messages: List of message dicts OR string (for backwards compatibility)
            session_id: Session identifier
            language: Language code

        Yields:
            str: Response text
        """
        response_stream = None

        try:
            # Get history
            history = await get_message_history(str(session_id))

            # Extract query from messages
            # Handle both list and string inputs for backwards compatibility
            if isinstance(messages, list) and messages:
                # Get last user message
                query = next(
                    (msg["content"] for msg in reversed(messages) if msg.get("role") == "user"),
                    str(messages[-1].get("content", ""))
                )
            else:
                query = str(messages)

            if not query:
                logger.warning("Empty query provided to LLM")
                yield "I didn't receive any input. Could you please repeat your question?"
                return

            # Create context
            from agents.deps import FarmerContext
            from uuid import UUID

            # Convert string IDs to UUIDs
            try:
                session_id = UUID(session_id) if isinstance(session_id, str) else session_id
            except (ValueError, AttributeError) as e:
                logger.error(f"Invalid UUID format: session_id={session_id}")
                yield f"Error: Invalid session ID format"
                return

            context = FarmerContext(
                query=query,
                lang_code=language,
            )

            # Instructions for FAST tool calling and SHORT responses
            instructions = (
                "⚠️ FORBIDDEN PHRASES - NEVER SAY:\n"
                "- 'Let me check that for you'\n"
                "- 'Let me check'\n"
                "- 'I'll check'\n"
                "- 'I'm checking'\n"
                "- 'One moment'\n"
                "\n"
                "RULES:\n"
                "1. Missing info? Ask directly: 'Which crop and which marketplace?'\n"
                "2. NO preamble before questions\n"
                "3. Have complete info? Call tool and respond with price\n"
                "4. Format: Price + date + 'per NMIS' in 1-2 sentences"
            )

            if self.enable_streaming:
                # STREAMING MODE: Try run_stream with stream_text for token streaming
                print("\n" + "╔" + "=" * 78 + "╗")
                print("║" + " " * 25 + "🚀 LLM REQUEST START" + " " * 32 + "║")
                print("╚" + "=" * 78 + "╝")
                logger.info("=" * 80)
                logger.info("🚀 LLM REQUEST START")
                logger.info("=" * 80)
                logger.debug("Using streaming mode with run_stream()")
                
                # Get and log the full system prompt
                system_prompt = get_system_prompt(prompt_file=language)
                print(f"\n📝 SYSTEM PROMPT:")
                print(f"   Length: {len(system_prompt)} chars")
                print(f"   Preview: {system_prompt[:300]}...")
                print(f"\n💬 USER QUERY: {context.query}")
                print(f"🌍 LANGUAGE: {language}")
                print(f"📚 HISTORY LENGTH: {len(history)} messages")
                print(f"🎯 INSTRUCTIONS: {instructions[:100]}...")
                
                logger.info(f"📝 SYSTEM PROMPT LENGTH: {len(system_prompt)} chars")
                logger.info(f"📝 FULL SYSTEM PROMPT:\n{system_prompt}")
                logger.info(f"💬 USER QUERY: {context.query}")
                logger.info(f"🌍 LANGUAGE: {language}")
                logger.info(f"📚 HISTORY LENGTH: {len(history)} messages")
                logger.info(f"🎯 INSTRUCTIONS: {instructions}")
                
                stream_start = time.time()
                print(f"\n⏱️  REQUEST SENT: {time.strftime('%H:%M:%S', time.localtime(stream_start))}.{int((stream_start % 1) * 1000):03d}")
                print("─" * 80)
                logger.info(f"⏱️  REQUEST SENT AT: {stream_start:.3f}")
                
                first_text_time = None
                text_chunk_count = 0
                tool_call_detected = False
                tool_call_time = None
                tool_result_time = None
                tool_result_sent_time = None
                
                # Send initial status BEFORE entering the stream context
                print("\n🔄 SENDING INITIAL STATUS...")
                logger.info("🔄 Sending initial status: Thinking...")
                yield "[STATUS:Thinking...]"
                
                # Small delay to ensure the status is sent and visible
                await asyncio.sleep(0.1)

                try:
                    async with agent.run_stream(
                        user_prompt=context.query,
                        message_history=history,
                        deps=context,
                        instructions=instructions,
                    ) as stream:
                        got_output = False
                        collected_text = ""
                        tool_calls_made = []
                        tool_results = []
                        current_tool_name = None
                        
                        print("\n🔄 WAITING FOR LLM RESPONSE...")
                        logger.info("🔄 STREAMING TEXT:")
                        logger.info(f"Stream object type: {type(stream)}")
                        logger.info(f"Stream object: {stream}")

                        # Use stream_text() to get text output (stream() is deprecated)
                        # Tool calls are already logged by the tools themselves
                        try:
                            logger.info("Starting stream_text iteration...")
                            async for chunk in stream.stream_text(delta=True):
                                logger.info(f"Received chunk from stream_text: '{chunk[:50] if chunk else 'None'}'")
                                if chunk:
                                    text_chunk_count += 1
                                    
                                    if first_text_time is None:
                                        first_text_time = time.time()
                                        elapsed = first_text_time - stream_start
                                        print("\n" + "┌" + "─" * 78 + "┐")
                                        print(f"│ ✅ FIRST TEXT CHUNK received in {elapsed:.3f}s" + " " * (78 - 40 - len(f"{elapsed:.3f}")) + "│")
                                        print("└" + "─" + "─" * 78 + "┘")
                                        logger.info(f"✅ FIRST TEXT CHUNK received in {elapsed:.3f}s")
                                    
                                    if text_chunk_count <= 3:
                                        print(f"   📝 Chunk #{text_chunk_count}: '{chunk[:60]}...' ({len(chunk)} chars)")
                                        logger.debug(f"Chunk #{text_chunk_count}: '{chunk[:50]}...' ({len(chunk)} chars)")
                                    
                                    collected_text += chunk
                                    
                                    # Filter forbidden phrases from chunk
                                    forbidden_patterns = [
                                        r"let me check that for you\.?\s*",
                                        r"let me check\.?\s*",
                                        r"i'll check that for you\.?\s*",
                                        r"i'll check\.?\s*",
                                        r"i'm checking\.?\s*",
                                        r"one moment please\.?\s*",
                                        r"one moment\.?\s*",
                                    ]
                                    
                                    import re
                                    filtered_chunk = chunk
                                    for pattern in forbidden_patterns:
                                        filtered_chunk = re.sub(pattern, "", filtered_chunk, flags=re.IGNORECASE)
                                    
                                    # Only yield if chunk has content after filtering
                                    if filtered_chunk.strip():
                                        got_output = True
                                        yield filtered_chunk
                                        logger.debug(f"✅ Yielded filtered chunk: '{filtered_chunk[:50]}'")
                                    elif chunk != filtered_chunk:
                                        logger.warning(f"⚠️  Filtered forbidden phrase from chunk: '{chunk[:50]}'")
                                        logger.warning(f"⚠️  Chunk was completely filtered out!")
                                    else:
                                        logger.warning(f"⚠️  Empty chunk after filtering: original='{chunk[:50]}'")
                        
                        except Exception as stream_error:
                            logger.error(f"Error in stream: {stream_error}", exc_info=True)
                            # Fall back to collected text if available
                            if collected_text:
                                logger.info(f"Using collected text as fallback: {len(collected_text)} chars")
                                got_output = True
                                yield collected_text
                        
                        
                        if not got_output:
                            print("\n⚠️  WARNING: Streaming completed but no text output received")
                            logger.warning("Streaming completed but no text output received")
                            logger.warning(f"Total collected text: '{collected_text[:200]}'")
                            logger.warning(f"Text chunk count: {text_chunk_count}")
                            yield "I couldn't generate a response. Please try again."
                        else:
                            total_time = time.time() - stream_start
                            print("\n" + "╔" + "=" * 78 + "╗")
                            print("║" + " " * 23 + "✅ LLM STREAMING COMPLETED" + " " * 28 + "║")
                            print("╚" + "=" * 78 + "╝")
                            print(f"   ⏱️  Total time: {total_time:.3f}s")
                            print(f"   📏 Response length: {len(collected_text)} chars")
                            print(f"   📦 Chunks received: {text_chunk_count}")
                            print(f"   💬 Response: {collected_text[:150]}...")
                            
                            logger.info(f"✅ LLM streaming completed in {total_time:.3f}s")
                            logger.info(f"   Response: {len(collected_text)} chars, {text_chunk_count} chunks")
                            logger.info(f"   Full response: {collected_text}")

                        # Save history - must be done inside the async with block
                        if hasattr(stream, 'result'):
                            response_stream = stream.result
                        elif hasattr(stream, '_result'):
                            response_stream = stream._result
                        else:
                            response_stream = stream

                except Exception as stream_error:
                    print(f"\n❌ STREAMING ERROR: {stream_error}")
                    logger.error(f"Streaming error: {stream_error}", exc_info=True)
                    yield "I encountered an error while streaming. Please try again."
                    return

            else:
                # NON-STREAMING MODE: Use run() for complete response (tool calling safe)
                logger.debug("Using non-streaming mode (full output)")

                response_stream = await agent.run(
                    user_prompt=context.query,
                    message_history=history,
                    deps=context,
                    instructions=instructions,
                )

                # Validate response
                if response_stream is None:
                    logger.error("Agent returned None")
                    yield "I'm having trouble processing your request. Please try again."
                    return

                if not hasattr(response_stream, 'output'):
                    logger.error(f"Response stream missing 'output' attribute: {type(response_stream)}")
                    yield "I encountered an error processing your request."
                    return

                # Yield the complete output at once
                output = response_stream.output
                if output and isinstance(output, str):
                    yield output
                else:
                    logger.warning(f"Invalid output type: {type(output)}")
                    yield "I couldn't generate a proper response. Please try again."

        except asyncio.CancelledError:
            logger.debug("LLM generation cancelled")
            raise

        except GeneratorExit:
            logger.debug("LLM generator exited")
            raise

        except Exception as e:
            logger.error(f"LLM Generation error: {e}", exc_info=True)
            yield f"I encountered an error: {str(e)[:100]}. Please try again."

        finally:
            # Save conversation history if available
            try:
                if response_stream is not None and hasattr(response_stream, "new_messages"):
                    # For non-streaming mode, use proper message history
                    new_messages = response_stream.new_messages()

                    if new_messages:
                        logger.debug(f"Saving {len(new_messages)} new messages to history")

                        # Log message breakdown for debugging
                        for msg in new_messages:
                            if hasattr(msg, 'parts'):
                                for part in msg.parts:
                                    kind = getattr(part, 'part_kind', 'unknown')
                                    logger.debug(f"  Message part: {kind}")

                        # Merge with existing history
                        history = await get_message_history(str(session_id))
                        all_messages = [*history, *new_messages]
                        await update_message_history(str(session_id), all_messages)

                        logger.info(
                            f"Saved history for session {session_id}: "
                            f"{len(all_messages)} messages total"
                        )
                    else:
                        logger.debug("No new messages to save")

                elif response_stream is None:
                    logger.debug("No response stream to save")

                else:
                    logger.warning(
                        f"Response stream missing new_messages method: {type(response_stream)}"
                    )

            except Exception as e:
                logger.error(f"Error saving conversation history: {e}", exc_info=True)


# Singleton
_llm_provider: Optional[LLMProvider] = None

# Configuration: Enable streaming for faster first-token response
# Tool calls will still complete before streaming begins, but text streams as generated
ENABLE_LLM_STREAMING = True


def get_llm_provider() -> LLMProvider:
    """
    Get or create LLM provider singleton

    To disable streaming (if tool calling breaks), set:
    ENABLE_LLM_STREAMING = False

    Returns:
        LLMProvider: LLM provider instance
    """
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = OpenRouterLLMProvider(enable_streaming=ENABLE_LLM_STREAMING)
    return _llm_provider


def set_streaming_mode(enabled: bool):
    """
    Toggle streaming mode on/off

    Args:
        enabled: True to enable streaming, False to disable

    Note: This will recreate the provider. Call before first use.
    """
    global _llm_provider, ENABLE_LLM_STREAMING
    ENABLE_LLM_STREAMING = enabled
    _llm_provider = None  # Force recreation
    logger.info(f"LLM streaming mode set to: {enabled}")
