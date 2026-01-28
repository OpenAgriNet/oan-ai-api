from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, TTSAudioRawFrame, TextFrame, EndFrame, StartFrame, CancelFrame
import logging
import httpx
import os
import asyncio

logger = logging.getLogger(__name__)

class SimpleAzureTTSService(FrameProcessor):
    """
    A stateless, HTTP-based Azure TTS implementation.
    Bypasses Azure SDK to ensure reliability in multi-turn conversations.
    """
    def __init__(self, api_key: str, region: str, voice: str = "en-US-AriaNeural"):
        super().__init__()
        self.api_key = api_key
        self.region = region
        self.voice = voice
        self.endpoint = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        self._is_generating = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Pass control frames through
        if isinstance(frame, (StartFrame, EndFrame, CancelFrame)):
            await self.push_frame(frame, direction)
            return

        # Process TextFrames
        if isinstance(frame, TextFrame):
            text = frame.text.strip()
            if not text:
                return
            
            # Simple aggregation logic could go here, but we rely on upstream optimization
            await self._synthesize_and_push(text, direction)

        # Ignore other frames (like InputAudioRawFrame) - just pass them?
        # Standard Pipecat services usually swallow input frames if they are a sink,
        # but this is a processor. Let's pass non-text frames just in case.
        # But wait, TextFrame -> TTSAudioRawFrame.
        # InputAudioRawFrame (User Mic) -> Should pass through? 
        # Yes, usually pipeline is linear.
        elif not isinstance(frame, TextFrame):
            await self.push_frame(frame, direction)

    async def _synthesize_and_push(self, text: str, direction: FrameDirection):
        logger.info(f"🎤 SimpleAzureTTS: Synthesizing '{text[:30]}...'")
        
        ssml = f"""
        <speak version='1.0' xml:lang='en-US'>
            <voice xml:lang='en-US' xml:gender='Female' name='{self.voice}'>
                {text}
            </voice>
        </speak>
        """
        
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "raw-16khz-16bit-mono-pcm",
            "User-Agent": "OanAI-Pipecat"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.endpoint, 
                    content=ssml, 
                    headers=headers, 
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    audio_data = response.content
                    # Send as one big chunk (or split if needed, but 16khz is fast)
                    # Pipecat prefers smaller chunks for streaming? 
                    # Actually, raw-16khz-16bit-mono-pcm IS the raw bytes.
                    
                    # Create frame
                    # InputAudioRawFrame vs TTSAudioRawFrame
                    # We output TTSAudioRawFrame
                    
                    # Log success
                    logger.info(f"✅ SimpleAzureTTS: Generated {len(audio_data)} bytes")
                    
                    # Push frame
                    # We can push one large frame or chop it. 
                    # Chopping is better for transport.
                    chunk_size = 4096 * 4 # 16KB chunks
                    for i in range(0, len(audio_data), chunk_size):
                        chunk = audio_data[i:i+chunk_size]
                        frame = TTSAudioRawFrame(audio=chunk, sample_rate=16000, num_channels=1)
                        await self.push_frame(frame, direction)
                        # yield execution to allow event loop (prevent blocking)
                        await asyncio.sleep(0)
                        
                else:
                    logger.error(f"❌ SimpleAzureTTS Error: {response.status_code} - {response.text}")
                    
        except Exception as e:
            logger.error(f"❌ SimpleAzureTTS Exception: {e}")
