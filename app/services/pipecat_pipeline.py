import os
import json
import asyncio
import numpy as np
import uuid
import time

from helpers.utils import get_logger

# Ensure NLTK data is available
import nltk
try:
    nltk.data.find('tokenizers/punkt')
except (LookupError, Exception):
    nltk.download('punkt')

try:
    nltk.data.find('tokenizers/punkt_tab')
except (LookupError, Exception):
    nltk.download('punkt_tab')

logger = get_logger(__name__)
from fastapi import WebSocket

# Pipecat imports
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
# Correct new import based on warning
try:
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
except ImportError:
    # Fallback or try another path if that failed too (versions vary wildy)
    from pipecat.transports.network.fastapi_websocket import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.services.ai_services import LLMService
from pipecat.services.azure import AzureSTTService, AzureTTSService
from pipecat.processors.aggregators.llm_response import LLMUserResponseAggregator, LLMAssistantResponseAggregator
from pipecat.frames.frames import (
    Frame,
    TextFrame,
    AudioRawFrame,
    InputAudioRawFrame,
    TTSAudioRawFrame, 
    StartInterruptionFrame,
    LLMFullResponseEndFrame,
    EndFrame,
    StartFrame,
    CancelFrame,
    LLMMessagesFrame,
    UserStoppedSpeakingFrame
)
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.processors.frame_processor import FrameDirection
from dataclasses import dataclass

@dataclass
class JSONMessageFrame(Frame):
    message: dict

# App imports
from agents.agrinet import agrinet_agent, generation_agent
from app.services.router import tool_router, ENABLE_OLLAMA_ROUTER
from agents.deps import FarmerContext
from app.utils import sanitize_history_for_generation

class InstrumentedAzureTTSService(AzureTTSService):
    def __init__(self, metrics: dict, *args, **kwargs):
        self.metrics = metrics
        super().__init__(*args, **kwargs)

    async def process_frame(self, frame, direction):
        if isinstance(frame, TextFrame) or hasattr(frame, 'text'):
            if 'tts_start' not in self.metrics:
                self.metrics['tts_start'] = time.perf_counter()
        
        await super().process_frame(frame, direction)
        
        if isinstance(frame, LLMFullResponseEndFrame):
             self.metrics['tts_end'] = time.perf_counter()
             self.log_metrics()

    def log_metrics(self):
        m = self.metrics
        
        # Calculate Durations
        asr_time = (m.get('asr_end', 0) - m.get('asr_start', 0))*1000 if m.get('asr_start') and m.get('asr_end') else 0
        llm_select = (m.get('first_tool_start', 0) - m.get('llm_start', 0))*1000 if m.get('first_tool_start') else 0
        
        tool_total = 0
        if m.get('timings'):
             for e in m['timings']:
                 if e['step'] == 'tool_end':
                     tool_total += e.get('duration', 0)

        llm_think = 0
        if m.get('first_token') and m.get('last_tool_end'):
            llm_think = (m['first_token'] - m['last_tool_end'])*1000
        elif m.get('first_token') and m.get('llm_start'):
            # No tools?
            if not m.get('first_tool_start'):
                 llm_think = (m['first_token'] - m['llm_start'])*1000

        tts_time = (m.get('tts_end', 0) - m.get('tts_start', 0))*1000 if m.get('tts_start') and m.get('tts_end') else 0
        
        total = (m.get('tts_end', 0) - m.get('asr_start', 0) if m.get('asr_start') else m.get('llm_start', 0))*1000
        if total < 0: total = 0
        
        mod_status = m.get('mod_status', 'Disabled')
        mod_time = "0.00 ms (N/A)"

        # Log
        log_lines = [
            f"\n{'='*50}",
            f"📊 PERFORMANCE METRICS BREAKDOWN",
            f"{'='*50}",
            f"🔹 Query: {m.get('query', 'Unknown')}",
            f"──────────────────────────────────────────────────",
            f"🎤 ASR (Latency):           {asr_time:.2f} ms",
            f"🧠 LLM (Tool Selection):    {llm_select:.2f} ms",
            f"🛠️  Tool Execution:          {tool_total:.2f} ms",
            f"⚖️  Moderation Layer:        {mod_time} [{mod_status}]",
            f"🔊 TTS (Generation+Stream): {tts_time:.2f} ms",
            f"──────────────────────────────────────────────────",
            f"🔴 TOTAL LATENCY:            {total:.2f} ms",
            f"{'='*50}"
        ]
        logger.info("\n".join(log_lines))
        # Reset for next turn 
        self.metrics.clear()

class AgriNetLLMService(LLMService):
    """Custom LLM Service for Pipecat that uses AgriNet Router + Generator"""
    
    def __init__(self, context: FarmerContext, metrics: dict):
        super().__init__()
        self.context = context
        self.metrics = metrics
        self.history = [] 

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Track VAD/ASR Start (End of Speech)
        if isinstance(frame, UserStoppedSpeakingFrame):
             self.metrics['asr_start'] = time.perf_counter()

        # Track ASR End (Text Arrival)
        if isinstance(frame, (TextFrame, LLMMessagesFrame)):
             if 'asr_end' not in self.metrics:
                 self.metrics['asr_end'] = time.perf_counter()

        await super().process_frame(frame, direction)

        # Handle TextFrame (Direct from STT - Partial or Final) OR LLMMessagesFrame (From Aggregator - Final)
        # With Aggregator, we mostly get LLMMessagesFrame.
        
        user_text = None
        
        if isinstance(frame, TextFrame):
            user_text = frame.text
        elif isinstance(frame, LLMMessagesFrame):
            # Extract last user message
            if frame.messages and frame.messages[-1]["role"] == "user":
                user_text = frame.messages[-1]["content"]
        
        if user_text:
            logger.info(f"User text: {user_text}")
            
            # Update context
            self.context.query = user_text
            self.metrics['query'] = user_text
            
            # Send User Text to Frontend (One Bubble Final)
            await self.push_frame(JSONMessageFrame({
                "type": "transcription",
                "text": user_text,
                "role": "user"
            }))
            
            try:
                # Run Agent
                ai_full_text = ""
                t_llm_start = time.perf_counter()
                self.metrics['llm_start'] = t_llm_start
                t_first_token = None
                
                logger.info(f"🚀 Starting LLM Generation for: '{user_text[:30]}...'")

                async with agrinet_agent.run_stream(
                    user_text,
                    deps=self.context
                ) as result:
                    async for chunk in result.stream_text(delta=True):
                        if chunk:
                            if t_first_token is None:
                                t_first_token = time.perf_counter()
                                self.metrics['first_token'] = t_first_token
                            
                            ai_full_text += chunk
                            await self.push_frame(TextFrame(text=chunk))
                    
                    t_llm_end = time.perf_counter()
                    self.metrics['llm_end'] = t_llm_end
                    
                    # Store timings from context for TTS Service logger
                    timings = self.context.timings
                    self.metrics['timings'] = timings
                    
                    if timings:
                        starts = [e for e in timings if e['step'] == 'tool_start']
                        ends = [e for e in timings if e['step'] == 'tool_end']
                        if starts: self.metrics['first_tool_start'] = starts[0]['timestamp']
                        if ends: self.metrics['last_tool_end'] = ends[-1]['timestamp']
                
                # Send Full AI Text via JSONMessageFrame (llm_chunk)
                await self.push_frame(JSONMessageFrame({
                    "type": "llm_chunk",
                    "text": ai_full_text,
                    "turn_id": str(uuid.uuid4())
                }))

                await self.push_frame(LLMFullResponseEndFrame())
                
            except Exception as e:
                logger.error(f"LLM Error: {e}")
                err_msg = " I encountered an error. Please try again."
                await self.push_frame(TextFrame(text=err_msg))
                await self.push_frame(LLMFullResponseEndFrame())

        else:
            await self.push_frame(frame, direction)


class RawFastAPIWebsocketInputTransport(BaseInputTransport):
    def __init__(self, websocket: WebSocket, params):
        super().__init__(params)
        self._websocket = websocket
        self._running = True

    async def start(self, frame_processor):
        await super().start(frame_processor)
        self._task = asyncio.create_task(self._read_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        await super().stop()

    async def _read_loop(self):
        logger.info("Raw Websocket Read Loop Started")
        try:
            while self._running:
                message = await self._websocket.receive()
                if "bytes" in message:
                    data = message["bytes"]
                    # logger.info(f"Received audio bytes: {len(data)}") 
                    
                    # Conversion: Float32 (Frontend) -> Int16 (Azure STT)
                    # Frontend parses as Float32 (from legacy code analysis)
                    try:
                        audio_float = np.frombuffer(data, dtype=np.float32)
                        # Scale to int16 range and convert
                        audio_int16 = (audio_float * 32767).astype(np.int16)
                        pcm_data = audio_int16.tobytes()
                        
                        frame = InputAudioRawFrame(
                            audio=pcm_data,
                            num_channels=1,
                            sample_rate=16000
                        )
                        await self.push_frame(frame)
                    except ValueError:
                         logger.warning("Failed to convert audio bytes - size mismatch?")
                elif "text" in message:
                     logger.info(f"Received text message: {message['text']}")
                     pass
        except Exception as e:
            logger.warning(f"Websocket read error: {e}")
            await self.push_frame(EndFrame())

class RawFastAPIWebsocketOutputTransport(BaseOutputTransport):
    def __init__(self, websocket: WebSocket, params):
        super().__init__(params)
        self._websocket = websocket
        self._text_buffer = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Delegate Control/Lifecycle frames to super to ensure state updates (StartFrame etc)
        if isinstance(frame, (StartFrame, EndFrame, CancelFrame, StartInterruptionFrame)):
             await super().process_frame(frame, direction)
             return

        # Override for Data Frames to bypass BaseOutputTransport strict destination checks
        # Direct send for TTS/Text/JSON/End
        if isinstance(frame, (TTSAudioRawFrame, TextFrame, LLMFullResponseEndFrame, JSONMessageFrame)):
             await self.send_frame(frame)
        
        # Allow passing through if needed (e.g. for metrics or chaining)
        await self.push_frame(frame, direction)

    async def send_frame(self, frame: Frame):
        # Handle TTS Audio (Response)
        if isinstance(frame, TTSAudioRawFrame):
            try:
                # logger.info(f"Sending audio bytes: {len(frame.audio)}")
                await self._websocket.send_bytes(frame.audio)
            except Exception as e:
                logger.error(f"Failed to send audio: {e}")
        
        # Buffer Text for AI Response
        elif isinstance(frame, TextFrame):
             self._text_buffer.append(frame.text)
             
        # Flush Buffer on End of LLM Response
        elif isinstance(frame, LLMFullResponseEndFrame):
             # Logic moved to AgriNetLLMService using JSONMessageFrame 
             # to avoid TTS swallowing EndFrames or Race Conditions
             self._text_buffer = []

        # Handle Immediate JSON Messages (User Text & AI Response)
        elif isinstance(frame, JSONMessageFrame):
             try:
                 await self._websocket.send_json(frame.message)
             except Exception as e:
                 logger.error(f"Failed to send JSON frame: {e}")
        
class RawFastAPIWebsocketTransport(BaseTransport):
    def __init__(self, websocket: WebSocket, params: TransportParams):
        super().__init__()
        self._input = RawFastAPIWebsocketInputTransport(websocket, params)
        self._output = RawFastAPIWebsocketOutputTransport(websocket, params)

    def input(self): return self._input
    def output(self): return self._output

async def run_pipecat_pipeline(websocket: WebSocket, session_id: str, lang: str = "en"):
    """
    Runs the Pipecat pipeline using Custom Raw WebSocket Transport.
    """
    # 1. Transport
    # Use our Custom Raw Transport
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    
    vad_analyzer = SileroVADAnalyzer(params=VADParams(
        start_secs=0.2,       # Quicker detection start
        stop_secs=0.8,        # Wait a bit before stopping (sentence pauses)
        confidence=0.5        # Balanced confidence
    ))

    transport = RawFastAPIWebsocketTransport(
        websocket=websocket,
        params=TransportParams(
            audio_out_enabled=True,
            audio_in_enabled=True,
            vad_enabled=True, # Still needed for some transports or backward compat
            vad_analyzer=vad_analyzer, 
            vad_audio_passthrough=True
        )
    )

    # 2. Services
    # Azure credentials
    azure_key = os.getenv("azure_foundary_api_key")
    azure_region = os.getenv("azure_foundary_region")

    stt = AzureSTTService(
        api_key=azure_key,
        region=azure_region,
        language="en-US" if lang == "en" else "am-ET", # Ensure locale for Azure
    )
    
    # Shared Metrics Dictionary
    metrics = {}
    
    enable_mod = os.getenv("ENABLE_MODERATION", "false").lower() == "true"
    metrics['mod_status'] = "Enabled" if enable_mod else "Disabled"

    tts = InstrumentedAzureTTSService(
        metrics=metrics,
        api_key=azure_key,
        region=azure_region,
        voice="en-US-JennyNeural" if lang == "en" else "am-ET-MekdesNeural" # Approximate for Amharic
    )

    # LLM
    context = FarmerContext(lang_code=lang, query="[Voice Session Initialized]")
    llm = AgriNetLLMService(context=context, metrics=metrics)
    
    # User Response Aggregator (collects user speech until silence)
    user_aggregator = LLMUserResponseAggregator()

    # 3. Pipeline Definition
    pipeline = Pipeline([
        transport.input(),   # Source: WebSocket Audio
        stt,                 # Audio -> Text (Interim+Final)
        user_aggregator,     # Text -> LLMMessages (Buffers until silence)
        llm,                 # LLMMessages -> Text (Stream)
        tts,                 # Text -> Audio
        transport.output()   # Audio -> WebSocket
    ])
    
    if enable_mod:
        logger.info("Moderation ENABLED (Configuration detected)")
        # If we had a filter, we'd insert it here:
        # pipeline = Pipeline([..., stt, mod_filter, user_aggregator, ...])

    # 4. Run
    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    
    logger.info(f"Starting Pipecat pipeline for session {session_id}")
    await runner.run(task)
