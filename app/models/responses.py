from pydantic import BaseModel, Field
from typing import Optional, List, Any

class BaseResponse(BaseModel):
    status: str = Field(..., description="Response status")
    message: Optional[str] = Field(None, description="Response message")

class TranscribeResponse(BaseResponse):
    text: Optional[str] = Field(None, description="Transcribed text")
    lang_code: Optional[str] = Field(None, description="Detected language code")
    session_id: Optional[str] = Field(None, description="Session ID")

class SuggestionsResponse(BaseResponse):
    suggestions: Optional[List[str]] = Field(None, description="List of suggested responses")
    session_id: Optional[str] = Field(None, description="Session ID")

class TTSResponse(BaseResponse):
    audio_content: Optional[str] = Field(None, description="Base64 encoded audio content")
    session_id: Optional[str] = Field(None, description="Session ID")

class ErrorResponse(BaseResponse):
    error_code: Optional[str] = Field(None, description="Error code")
    details: Optional[Any] = Field(None, description="Additional error details")
