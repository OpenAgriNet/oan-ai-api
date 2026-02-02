from fastapi import APIRouter, WebSocket
import uuid
from app.services.pipecat_pipeline import run_pipecat_pipeline
from helpers.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/conv", tags=["conversation"])

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for voice conversation using Pipecat.
    
    Query Parameters:
        lang (str): Language code (en, am). Default: en
    """
    # Accept the connection first
    await websocket.accept()
    
    lang = websocket.query_params.get("lang", "en")
    session_id = str(uuid.uuid4())
    logger.info(f"WebSocket connection request (Pipecat) received with lang={lang} session={session_id}")
    
    try:
        await run_pipecat_pipeline(websocket, session_id, lang=lang)
    except Exception as e:
        logger.error(f"Pipecat pipeline error: {e}")
        try:
            # Check if open before closing? WebSocketState.CONNECTED
            await websocket.close()
        except Exception:
            pass

