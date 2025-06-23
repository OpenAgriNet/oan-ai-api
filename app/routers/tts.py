from helpers.tts import text_to_speech_bhashini
from helpers.utils import get_logger
import uuid
import base64
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter(prefix="/tts", tags=["tts"])

class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to convert to speech")
    target_lang: str = Field(default="mr", description="Target language code")
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Session ID")

@router.post("/")
async def tts(request: TTSRequest):
    """Handles text to speech conversion."""
    
    if not request.text:
        raise HTTPException(status_code=400, detail="text is required")
    
    try:
        audio_data = text_to_speech_bhashini(request.text, request.target_lang, gender='female', sampling_rate=8000)
        
        # Base64 encode the binary audio data for JSON serialization
        if isinstance(audio_data, bytes):
            audio_data = base64.b64encode(audio_data).decode('utf-8')
        
        return {
            'status': 'success',
            'audio_data': audio_data,
            'session_id': request.session_id
        }
    except Exception as e:
        logger.error(f"TTS error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"TTS failed: {str(e)}")
