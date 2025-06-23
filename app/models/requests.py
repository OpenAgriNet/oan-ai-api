from pydantic import BaseModel, Field
from typing import Optional

class ChatRequest(BaseModel):
    query: str = Field(..., description="The user's chat query")
    session_id: Optional[str] = Field(None, description="Session ID for maintaining conversation context")
    source_lang: str = Field('mr', description="Source language code")
    target_lang: str = Field('mr', description="Target language code")
    user_id: str = Field('anonymous', description="User identifier")

class TranscribeRequest(BaseModel):
    audio_content: str = Field(..., description="Base64 encoded audio content")
    session_id: Optional[str] = Field(None, description="Session ID")

class SuggestionsRequest(BaseModel):
    session_id: str = Field(..., description="Session ID to get suggestions for")
    target_lang: str = Field('mr', description="Target language for suggestions")

class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to convert to speech")
    lang_code: str = Field('mr', description="Language code for TTS")
    session_id: Optional[str] = Field(None, description="Session ID")
