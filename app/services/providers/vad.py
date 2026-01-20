import torch
from typing import Optional, Any, Tuple
from helpers.utils import get_logger

logger = get_logger(__name__)

class VADProvider:
    def __init__(self):
        logger.info("Loading Silero VAD model...")
        try:
            self.model, self.utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False
            )
            logger.info("✅ Silero VAD model loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load Silero VAD: {e}")
            raise

    def get_iterator(self, sampling_rate: int = 16000, threshold: float = 0.5) -> Any:
        """Get a new VADIterator instance"""
        (get_speech_timestamps, save_audio, read_audio, VADIterator, collect_chunks) = self.utils
        return VADIterator(self.model, sampling_rate=sampling_rate, threshold=threshold)

# Singleton
_vad_provider: Optional[VADProvider] = None

def get_vad_provider() -> VADProvider:
    global _vad_provider
    if _vad_provider is None:
        _vad_provider = VADProvider()
    return _vad_provider
