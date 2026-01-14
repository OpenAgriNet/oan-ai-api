
from typing import AsyncGenerator
import json
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
from helpers.utils import get_logger

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
    # async with agrinet_agent.run_stream(
    #     user_prompt=deps.get_user_message(),
    #     message_history=trim_history(
    #         history,
    #         max_tokens=60_000,
    #         include_system_prompts=True,
    #         include_tool_calls=True
    #     ),
    #     deps=deps,
    # ) as response_stream:  # response_stream is a StreamedRunResult
    #     previous_text = ""
    #     response_stream.get_output()
    #     async for chunk in response_stream.stream_output():
    #         new_text = chunk[len(previous_text):]
    #         if new_text:
    #             yield new_text
    #         previous_text = chunk

    response_stream = await agrinet_agent.run(
            user_prompt=deps.get_user_message(),
            message_history=trim_history(
                history,
                max_tokens=60_000,
                include_system_prompts=True,
                include_tool_calls=True
            ),
            deps=deps,
        )
    yield response_stream.output
    # Extract sources from tool calls
    sources = extract_sources_from_result(response_stream)

    # Save messages to history
    new_messages = response_stream.new_messages()
    messages = [
        *history,
        *new_messages
    ]
    await update_message_history(session_id, messages)

    # Send sources as SSE metadata event (if any)
    if sources:
        metadata = json.dumps({"sources": sources})
        yield f"event: metadata\ndata: {metadata}\n\n"