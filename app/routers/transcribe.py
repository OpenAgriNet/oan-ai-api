import uuid
from helpers.transcription import transcribe_bhashini, detect_audio_language_bhashini
from helpers.utils import get_logger
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter(prefix="/transcribe", tags=["transcribe"])

class TranscribeRequest(BaseModel):
    audio_content: str = Field(..., description="Base64 encoded audio content")
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Session ID")

@router.post("/")
async def transcribe(request: TranscribeRequest):
    """Handles language detection and transcription of audio."""
    
    if not request.audio_content:
        raise HTTPException(status_code=400, detail="audio_content is required")
   
    try:
        lang_code = detect_audio_language_bhashini(request.audio_content)
        logger.info(f"Detected language code: {lang_code}")
        
        transcription = transcribe_bhashini(request.audio_content, lang_code)
        logger.info(f"Transcription: {transcription}")
       
        return {
            'status': 'success',
            'text': transcription,
            'lang_code': lang_code,
            'session_id': request.session_id
        }
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
