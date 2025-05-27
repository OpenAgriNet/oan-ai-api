import nest_asyncio
nest_asyncio.apply()
import uuid
import asyncio
from typing import AsyncGenerator
from rest_framework.decorators import api_view
from agents.agrinet import agrinet_agent
from agents.moderation import moderation_agent
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from helpers.utils import get_logger
from oan_app.views.utils import (
    _get_message_history, 
    update_message_history, 
    trim_history, 
    format_message_pairs
)
from oan_app.tasks.suggestions import create_suggestions
from django.http import StreamingHttpResponse, HttpRequest
from oan_app.authentication import CustomJWTAuthentication
from rest_framework.permissions import IsAuthenticated
from dotenv import load_dotenv
from agents.deps import FarmerContext

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
    moderation_run = moderation_agent.run_sync(user_message)
    moderation_data = moderation_run.output
    
    deps.update_moderation_str(str(moderation_data))

    # Run the main agent
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
        async for chunk in response_stream.stream_text(delta=True, debounce_by=0.1):
            if chunk:  # Ensure non-empty chunks are yielded
                yield chunk
        
        # After streaming is complete, get the run result for history
        new_messages = response_stream.new_messages()
        messages = [
            *history,
            *new_messages
        ]
        update_message_history(session_id, messages)

@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
@api_view(['GET', 'OPTIONS'])
def chat(request: HttpRequest) -> StreamingHttpResponse:
    """Handles chat sessions between a user and the AI assistant."""
    session_id = request.query_params.get('session_id', str(uuid.uuid4()))
    query = request.query_params.get('query')
    source_lang = request.query_params.get('source_lang', 'mr')  # Optimistic assumption that source language is Marathi
    target_lang = request.query_params.get('target_lang', 'mr')  # Target language is Marathi, unless otherwise specified
    user_id = request.query_params.get('user_id', 'anonymous')
    
    logger.info(
        f"Chat request received - session_id: {session_id}, user_id: {user_id}, "
        f"source_lang: {source_lang}, target_lang: {target_lang}, query: {query}"
    )
    
    # Get the message history
    history = _get_message_history(session_id)
    logger.debug(f"Retrieved message history for session {session_id} - length: {len(history)}")

    # Create suggestions for the session: 1, 3, 5, 7, ...
    if (len(history)+1) % 2 == 0:
        logger.debug(f"Creating suggestions for session {session_id}")
        create_suggestions.s(session_id, target_lang).apply_async()

    # Create an event loop for running the async generator
    async def run_async():
        logger.debug(f"Generator function run_async created for session {session_id}")
        try:
            # Log the event loop state
            loop = asyncio.get_running_loop()
            logger.debug(f"Using event loop {id(loop)} for session {session_id}")
            
            logger.debug(f"Starting streaming response for session {session_id}")
            chunks_yielded = 0
            async for chunk in stream_chat_messages(
                query=query,
                session_id=session_id,
                source_lang=source_lang,
                target_lang=target_lang,
                user_id=user_id,
                history=history
            ):
                chunks_yielded += 1
                if chunks_yielded == 1:
                    logger.debug(f"First chunk yielded for session {session_id}")
                yield chunk
            
            logger.info(f"Completed streaming response for session {session_id} - total chunks: {chunks_yielded}")
        except asyncio.CancelledError:
            logger.warning(f"Streaming was cancelled for session {session_id} - possible client disconnect")
            raise
        except Exception as e:
            logger.error(f"Error during streaming for session {session_id}: {str(e)}", exc_info=True)
            raise
        finally:
            logger.debug(f"Generator function exiting for session {session_id}")

    logger.debug(f"Creating StreamingHttpResponse for session {session_id}")
    response = StreamingHttpResponse(
        streaming_content=run_async(),
        content_type='text/event-stream; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )
    logger.debug(f"StreamingHttpResponse created for session {session_id}")
    return response