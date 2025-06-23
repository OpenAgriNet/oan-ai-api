from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from app.utils import get_cache
from app.tasks.suggestions import create_suggestions
from helpers.utils import get_logger
from pydantic import BaseModel, Field
from typing import Optional

logger = get_logger(__name__)

router = APIRouter(prefix="/suggest", tags=["suggest"])

class SuggestionsRequest(BaseModel):
    session_id: str = Field(..., description="Chat session ID", min_length=1)
    target_lang: str = Field(default="mr", description="Target language for suggestions")

@router.post("/")
async def suggest(request: SuggestionsRequest, background_tasks: BackgroundTasks):
    """Get suggestions for a chat session. If not available, trigger generation."""
    
    logger.info(f"Getting suggestions for session {request.session_id} in language {request.target_lang}")
    
    suggestions = await get_cache(f"suggestions_{request.session_id}_{request.target_lang}")
    
    if not suggestions:
        logger.info(f"No cached suggestions found, triggering background generation")
        background_tasks.add_task(create_suggestions, request.session_id, request.target_lang)
        suggestions = []
    
    return {"suggestions": suggestions}