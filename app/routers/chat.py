from fastapi.responses import StreamingResponse
import uuid
import asyncio
from fastapi import APIRouter, BackgroundTasks
from helpers.utils import get_logger
from app.utils import _get_message_history
from app.tasks.suggestions import create_suggestions
from app.services.chat import stream_chat_messages
from app.models.requests import ChatRequest
from typing import Optional

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    """Handles chat sessions between a user and the AI assistant."""
    session_id = request.session_id or str(uuid.uuid4())
    
    logger.info(
        f"Chat request received - session_id: {session_id}, user_id: {request.user_id}, "
        f"source_lang: {request.source_lang}, target_lang: {request.target_lang}, query: {request.query}"
    )
    
    # Get the message history
    history = await _get_message_history(session_id)
    logger.debug(f"Retrieved message history for session {session_id} - length: {len(history)}")

    # Create suggestions for the session: 1, 3, 5, 7, ...
    if (len(history)+1) % 2 == 0:
        logger.debug(f"Creating suggestions for session {session_id}")
        background_tasks.add_task(create_suggestions, session_id, request.target_lang)

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
                query=request.query,
                session_id=session_id,
                source_lang=request.source_lang,
                target_lang=request.target_lang,
                user_id=request.user_id,
                history=history
            ):
                chunks_yielded += 1
                yield chunk
            
            logger.info(f"Completed streaming response for session {session_id} - total chunks: {chunks_yielded}")
        except Exception as e:
            logger.error(f"Error during streaming for session {session_id}: {str(e)}")
            raise

    logger.debug(f"Creating StreamingHttpResponse for session {session_id}")
    response = StreamingResponse(
        run_async(),
        media_type='text/event-stream; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )    
    logger.debug(f"StreamingHttpResponse created for session {session_id}")
    return response
