import uuid
from helpers.transcription import transcribe_bhashini, detect_audio_language_bhashini
from helpers.utils import get_logger
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from app.models.requests import TranscribeRequest
from app.models.responses import TranscribeResponse, ErrorResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/transcribe", tags=["transcribe"])

@router.post("/", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest):
    """Handles language detection and transcription of audio using Bhashini service."""
    
    if not request.audio_content:
        raise HTTPException(status_code=400, detail="audio_content is required")
   
    try:
        lang_code = detect_audio_language_bhashini(request.audio_content)
        logger.info(f"Detected language code: {lang_code}")
        
        transcription = transcribe_bhashini(request.audio_content, lang_code)
        logger.info(f"Transcription: {transcription}")
        
        return TranscribeResponse(
            status='success',
            text=transcription,
            lang_code=lang_code,
            session_id=request.session_id or str(uuid.uuid4())
        )
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
