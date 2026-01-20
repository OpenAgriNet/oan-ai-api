from fastapi import APIRouter, WebSocket
from app.services.pipeline import ConversationPipeline
from helpers.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/conv", tags=["conversation"])

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    lang = websocket.query_params.get("lang", "en")
    logger.info(f"WebSocket accepted with lang={lang}")
    
    pipeline = ConversationPipeline(websocket, lang=lang)
    await pipeline.run()

