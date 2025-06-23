"""
FastAPI Routers
"""
from .chat import router as chat_router
from .suggestions import router as suggestions_router
from .transcribe import router as transcribe_router
from .tts import router as tts_router

__all__ = ["chat_router", "suggestions_router", "transcribe_router", "tts_router"]
