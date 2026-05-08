
from typing import AsyncGenerator
from agents.agrinet import agrinet_agent
from agents.moderation import moderation_agent
from helpers.utils import get_logger
from app.utils import (
    update_message_history, 
    trim_history, 
    format_message_pairs
)
from dotenv import load_dotenv
from agents.deps import FarmerContext
from helpers.utils import get_logger
from app.telemetry import (
    build_assistant_event,
    build_error_event,
    build_tool_call_event,
    build_tool_result_event,
    build_user_event,
    emit_session_event,
)

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
    # Generate a unique content ID for this query
    content_id = f"query_{session_id}_{len(history)//2 + 1}"
    emit_session_event(
        build_user_event(
            session_id=session_id,
            user_id=user_id,
            source_lang=source_lang,
            target_lang=target_lang,
            content=query,
        )
    )
       
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
    moderation_run = await moderation_agent.run(user_message)
    moderation_data = moderation_run.output
    
    deps.update_moderation_str(str(moderation_data))

    # Run the main agent
    try:
        async with agrinet_agent.run_stream(
            user_prompt=deps.get_user_message(),
            message_history=trim_history(
                history,
                max_tokens=60_000,
                include_system_prompts=True,
                include_tool_calls=True
            ),
            deps=deps,
        ) as response_stream:  # response_stream is a StreamedRunResult
            collected_response = []
            async for chunk in response_stream.stream_text(delta=True, debounce_by=0.1):
                if chunk:  # Ensure non-empty chunks are yielded
                    collected_response.append(chunk)
                    yield chunk

            # After streaming is complete, get the run result for history
            new_messages = response_stream.new_messages()
            messages = [
                *history,
                *new_messages
            ]
            await update_message_history(session_id, messages)

            # Emit tool call/result events extracted from new messages.
            for message in new_messages:
                for part in getattr(message, "parts", []):
                    kind = getattr(part, "part_kind", "")
                    if kind == "tool-call":
                        emit_session_event(
                            build_tool_call_event(
                                session_id=session_id,
                                user_id=user_id,
                                source_lang=source_lang,
                                target_lang=target_lang,
                                tool_name=getattr(part, "tool_name", ""),
                                tool_call_id=getattr(part, "tool_call_id", ""),
                                tool_args=getattr(part, "args", {}),
                            )
                        )
                    elif kind == "tool-return":
                        emit_session_event(
                            build_tool_result_event(
                                session_id=session_id,
                                user_id=user_id,
                                source_lang=source_lang,
                                target_lang=target_lang,
                                tool_name=getattr(part, "tool_name", ""),
                                tool_call_id=getattr(part, "tool_call_id", ""),
                                tool_result=getattr(part, "content", None),
                            )
                        )

            emit_session_event(
                build_assistant_event(
                    session_id=session_id,
                    user_id=user_id,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    content="".join(collected_response),
                    metadata={"content_id": content_id},
                )
            )
    except Exception as exc:
        emit_session_event(
            build_error_event(
                session_id=session_id,
                user_id=user_id,
                source_lang=source_lang,
                target_lang=target_lang,
                error_type=type(exc).__name__,
                error_message=str(exc),
                metadata={"content_id": content_id},
            )
        )
        raise
