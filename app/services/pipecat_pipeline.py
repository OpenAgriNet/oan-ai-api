import os
import json
import asyncio
import numpy as np
import uuid
import time
import re
from helpers.utils import get_logger
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

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
try:
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
except ImportError:
    from pipecat.transports.network.fastapi_websocket import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.services.ai_services import LLMService
from pipecat.services.azure import AzureSTTService, AzureTTSService
from pipecat.frames.frames import (
    Frame, TextFrame, AudioRawFrame, InputAudioRawFrame, TTSAudioRawFrame, 
    StartInterruptionFrame, LLMFullResponseEndFrame, EndFrame, StartFrame, 
    CancelFrame, LLMMessagesFrame, UserStoppedSpeakingFrame, 
    UserStartedSpeakingFrame, TranscriptionFrame, InterimTranscriptionFrame
)
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from dataclasses import dataclass

@dataclass
class JSONMessageFrame(Frame):
    message: dict

from agents.agrinet import agrinet_agent, generation_agent
from app.services.router import tool_router, ENABLE_OLLAMA_ROUTER
from agents.deps import FarmerContext
from app.utils import sanitize_history_for_generation

class InstrumentedAzureSTTService(AzureSTTService):
    def __init__(self, metrics: dict, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics = metrics
        self._audio_frame_count = 0
        logger.info(f"🔧 STT initialized (sample_rate={kwargs.get('sample_rate', 16000)})")
        
    async def start(self, frame):
        await super().start(frame)
        if hasattr(self, '_speech_recognizer') and self._speech_recognizer:
            def on_canceled(evt):
                logger.warning(f"❌ Azure STT - CANCELED: {evt.result.cancellation_details}")
            self._speech_recognizer.canceled.connect(on_canceled)
        else:
            logger.warning("⚠️ STT: Speech recognizer not created!")
        
    async def process_frame(self, frame, direction):
        if isinstance(frame, InputAudioRawFrame):
            self._audio_frame_count += 1
            # Start timing on first audio packet
            if 'asr_start' not in self.metrics:
                self.metrics['asr_start'] = time.perf_counter()
                
        await super().process_frame(frame, direction)
        
    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frame, TranscriptionFrame):
            t = time.perf_counter()
            self.metrics['asr_end'] = t
            self.metrics['llm_start'] = t
            logger.info(f"📝 STT: '{frame.text}'")
            
        await super().push_frame(frame, direction)

class InstrumentedAzureTTSService(AzureTTSService):
    def __init__(self, metrics: dict, *args, **kwargs):
        self.metrics = metrics
        self._audio_frame_count = 0
        super().__init__(*args, **kwargs)
        
    async def process_frame(self, frame, direction):
        if (isinstance(frame, TextFrame) or hasattr(frame, 'text')) and not isinstance(frame, TranscriptionFrame):
            if 'tts_start' not in self.metrics:
                self.metrics['tts_start'] = time.perf_counter()
                text_preview = getattr(frame, 'text', 'NoText')[:30]
                logger.info(f"🐛 TTS START: '{text_preview}' at {self.metrics['tts_start']}")
        
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseEndFrame):
             self.metrics['tts_end'] = time.perf_counter()
             logger.info(f"🔊 TTS: Complete ({self._audio_frame_count} audio frames)")
             self._audio_frame_count = 0
             
             # Calculate and log metrics, and get the dict to send to client
             metrics_data = self.log_metrics()
             
             # Send metrics to frontend/client via JSON frame
             if metrics_data:
                 await self.push_frame(JSONMessageFrame(message={
                     "type": "metrics", 
                     "data": metrics_data
                 }))

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frame, TTSAudioRawFrame):
            self._audio_frame_count += 1
            if 'tts_first_audio' not in self.metrics:
                now = time.perf_counter()
                self.metrics['tts_first_audio'] = now
                logger.info(f"🔊 TTS: First audio frame produced ({len(frame.audio)} bytes) at {now}")
                if 'tts_start' in self.metrics:
                    delta = (now - self.metrics['tts_start']) * 1000
                    logger.info(f"🐛 TTS Latency Debug: {delta:.2f}ms")
        
        await super().push_frame(frame, direction)

    def log_metrics(self):
        m = self.metrics
        
        # ═══════════════════════════════════════════════════════
        # COMPREHENSIVE LATENCY METRICS
        # ═══════════════════════════════════════════════════════
        
        # 1. ASR/STT Time 
        # Latency: processing time after speech stopped
        stt_latency = 0
        if m.get('asr_end') and m.get('speech_stopped'):
            stt_latency = (m['asr_end'] - m['speech_stopped'])*1000
            
        # Duration: Total time from first audio packet to text ready
        stt_duration = 0
        if m.get('asr_end') and m.get('asr_start'):
            stt_duration = (m['asr_end'] - m['asr_start'])*1000
        
        # 2. Buffer Wait (Intentional Delay)
        buffer_wait = 0
        if m.get('buffer_end') and m.get('buffer_start'):
            buffer_wait = (m['buffer_end'] - m['buffer_start'])*1000
            
        # 3. LLM Time to First Token (TTFB) - Pure Inference Latency
        llm_ttfb = 0
        if m.get('first_token') and m.get('llm_start') and m['first_token'] > m['llm_start']:
            llm_ttfb = (m['first_token'] - m['llm_start'])*1000
        
        # 4. LLM Tool Selection
        llm_select = 0
        if m.get('first_tool_start') and m.get('llm_start'):
            llm_select = (m['first_tool_start'] - m['llm_start'])*1000
        
        # 5. Tool Execution
        tool_total = 0
        tool_count = 0
        if m.get('timings'):
            for e in m['timings']:
                if e['step'] == 'tool_end':
                    tool_total += e.get('duration', 0)
                    tool_count += 1

        # 6. Response Generation (Time spent generating the final answer)
        response_gen = 0
        if m.get('first_token') and m.get('last_tool_end'):
            response_gen = (m['first_token'] - m['last_tool_end'])*1000
        elif m.get('first_token') and m.get('llm_start') and not m.get('first_tool_start'):
            response_gen = llm_ttfb
        elif m.get('llm_end') and m.get('last_tool_end'):
            response_gen = (m['llm_end'] - m['last_tool_end'])*1000

        # 7. Text Streaming
        llm_gen = 0
        if m.get('llm_end') and m.get('first_token'):
            llm_gen = (m['llm_end'] - m['first_token'])*1000
        
        # 8. Pure LLM Inference Total (Start to End of Generation)
        llm_inference_total = 0
        if m.get('llm_end') and m.get('llm_start'):
            llm_inference_total = (m['llm_end'] - m['llm_start'])*1000
            
        # Calculate Intermediate Thinking (Gaps between tools)
        # Total = Select + Exec + Gen + Intermediate
        intermediate_think = llm_inference_total - llm_select - tool_total - response_gen
        if intermediate_think < 0: intermediate_think = 0

        # 9. TTS Synthesis (Time to produce first audio chunk)
        tts_time = 0
        if m.get('tts_start') and m.get('tts_first_audio'):
            tts_time = (m['tts_first_audio'] - m['tts_start'])*1000
        
        # 10. E2E Latency (Speech Stop -> First Audio)
        e2e_latency = 0
        if m.get('tts_first_audio') and m.get('speech_stopped'):
            e2e_latency = (m['tts_first_audio'] - m['speech_stopped'])*1000
        
        # 11. Full Pipeline Processing Time (Speech Stop -> Audio Done)
        full_pipeline = 0
        if m.get('tts_end') and m.get('speech_stopped'):
            full_pipeline = (m['tts_end'] - m['speech_stopped'])*1000

        query_preview = m.get('query', 'Unknown')[:60]
        if len(m.get('query', '')) > 60:
            query_preview += "..."
            
        mod_status = m.get('mod_status', 'Disabled')
        mod_time = m.get('mod_time', 0.0)
        mod_display = f"{mod_time:>8.2f} ms" if mod_status == 'Enabled' else f"N/A [{mod_status}]"

        log_lines = [
            f"\n{'═'*60}",
            f"📊 PERFORMANCE METRICS BREAKDOWN",
            f"{'═'*60}",
            f"🔹 Query: {query_preview}",
            f"{'─'*60}",
            f"",
            f"📍 STAGE TIMINGS:",
            f"   🎤 STT Duration:          {stt_duration:>8.2f} ms (Processing: {stt_latency:.2f} ms)",
            f"",
            f"   ⏳ Pipeline Overhead:",
            f"      🛑 Buffer Wait:        {buffer_wait:>8.2f} ms",
            f"      ⚖️  Moderation:         {mod_display}",
            f"",
            f"   ⚡ LLM Inference Total:   {llm_inference_total:>8.2f} ms",
            f"      🧠 Initial Thought:    {llm_select:>8.2f} ms",
            f"      🛠️  Tool Execution:     {tool_total:>8.2f} ms ({tool_count} calls)",
            f"      🤔 Multi-turn Think:   {intermediate_think:>8.2f} ms",
            f"      💬 Final Response Gen: {response_gen:>8.2f} ms",
            f"",
            f"   🔊 TTS Synthesis:         {tts_time:>8.2f} ms",
            f"",
            f"{'─'*60}",
            f"📊 AGGREGATE METRICS:",
            f"   ⏱️  User Percieved Latency:{e2e_latency:>8.2f} ms (Speech Stop → Audio Start)",
            f"   🔴 Total Pipeline Time:   {full_pipeline:>8.2f} ms",
            f"{'═'*60}"
        ]
        logger.info("\n".join(log_lines))
        
        # Build dictionary for client
        metrics_dict = {
            "query": query_preview,
            "stt_duration": round(stt_duration, 2),
            "stt_latency": round(stt_latency, 2),
            "buffer_wait": round(buffer_wait, 2),
            "moderation": round(mod_time, 2) if mod_status == 'Enabled' else "Disabled",
            "llm_ttfb": round(llm_ttfb, 2),
            "llm_inference_total": round(llm_inference_total, 2),
            "tool_calls": tool_count,
            "tool_processing": round(tool_total, 2),
            "response_generation": round(response_gen, 2),
            "tts_synthesis": round(tts_time, 2),
            "e2e_latency": round(e2e_latency, 2),
            "full_pipeline_time": round(full_pipeline, 2)
        }
        
        # Reset metrics for next turn (preserving structure)
        self.metrics.clear()
        self.metrics['timings'] = []
        
        return metrics_dict

class AgriNetLLMService(FrameProcessor):
    """Custom LLM Service that handles Buffering, Delay, and Generation directly."""
    
    def __init__(self, context: FarmerContext, metrics: dict, websocket: WebSocket):
        super().__init__()
        logger.info("🟢 AgriNetLLMService INITIALIZED")
        self.context = context
        self.metrics = metrics
        self.history = [] 
        self._text_buffer = ""
        self._response_task = None
        self._websocket = websocket  # Direct websocket access for sending responses

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Handle control frames - call super AND push to next processor
        if isinstance(frame, (StartFrame, EndFrame, CancelFrame)):
            logger.critical(f"🎭 AgriNet PROPAGATING Control Frame: {type(frame).__name__}")
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return
            
        # DEBUG: Log non-audio frames
        if not isinstance(frame, (InputAudioRawFrame, TTSAudioRawFrame)):
            logger.critical(f"🎭 AgriNet RECEIVED: {type(frame).__name__}")
        
        # 1. Speech Start: Propagate it! (Verification)
        if isinstance(frame, UserStartedSpeakingFrame):
             if self._response_task and not self._response_task.done():
                 try:
                     self._response_task.cancel()
                     logger.info("🛑 Previous Response Task Cancelled (Interruption)")
                 except Exception: pass

             self.metrics.clear() # Reset metrics for new turn
             self.metrics['speech_started'] = time.perf_counter()
             logger.critical("🎤 SPEECH DETECTED - PROPAGATING (Verification Mode)")
             await super().process_frame(frame, direction)
             await self.push_frame(frame, direction)
             return
             
        # 2. Input Audio: SWALLOW IT (Do not send to TTS)
        if isinstance(frame, InputAudioRawFrame):
             # Do not push downstream
             return
             
        # 2. Text Arrival: Accumulate Buffer
        elif isinstance(frame, TextFrame):
             # CRITICAL: Ignore Interim frames to avoid duplication
             if isinstance(frame, InterimTranscriptionFrame):
                 # logger.debug(f"Skipping Interim: {frame.text}")
                 return

             # Set ASR End timestamp (Last text arrival determines end of transcription latency)
             self.metrics['asr_end'] = time.perf_counter()
             
             # Append text instead of replacing (handles multiple phrases or noise+phrase)
             if self._text_buffer:
                 self._text_buffer += " " + frame.text
             else:
                 self._text_buffer = frame.text
             logger.critical(f"📝 AgriNet TEXT BUFF: '{self._text_buffer}'")
             
        # 3. Speech Stop: Wait for latency, then Trigger Generation
        elif isinstance(frame, UserStoppedSpeakingFrame):
             self.metrics['speech_stopped'] = time.perf_counter()
             
             # Start background task to wait and generate
             self._response_task = asyncio.create_task(self._wait_and_generate(direction))

        # Pass frames through to next processor
        logger.critical(f"⏭️  AgriNet PUSHING Downstream: {type(frame).__name__}")
        await self.push_frame(frame, direction)

    async def _wait_and_generate(self, direction):
        """Wait for late STT frames, then generate."""
        try:
            # Capture Buffer Wait Time
            self.metrics['buffer_start'] = time.perf_counter()
            
            # Wait 3.0s for Cloud STT latency (logs show ~2s delay)
            logger.info("⏳ AgriNet: Waiting 3.0s for final text...")
            await asyncio.sleep(3.0)
            
            self.metrics['buffer_end'] = time.perf_counter()
            
            user_text = self._text_buffer.strip()
            if not user_text:
                logger.warning("⚠️ AgriNet: No text received after wait. Ignoring turn.")
                return

            # Clear buffer immediately after picking it up to avoid re-processing
            self._text_buffer = ""

            logger.info(f"🚀 AgriNet: Proceeding with query: '{user_text}'")
            
            # --- GENERATION LOGIC ---
            self.context.query = user_text
            self.metrics['query'] = user_text
            
            # Update history with User Message
            self.history.append({"role": "user", "content": user_text})
            # Keep history manageable
            if len(self.history) > 10:
                self.history = self.history[-10:]
            
            # Import FastGemini services
            from app.services.fast_gemini import FastGeminiService, FastModerationService
            
            # Run moderation first (if enabled)
            moderation_service = FastModerationService()
            is_safe, mod_category, mod_action = await moderation_service.moderate(user_text, self.metrics)
            
            if not is_safe:
                logger.info(f"⛔ Query blocked by moderation: {mod_category}")
                rejection_msg = "I can only help with agricultural topics."
                # Send directly via websocket
                await self._websocket.send_json({
                    "type": "llm_chunk",
                    "text": rejection_msg,
                    "turn_id": str(uuid.uuid4())
                })
                # Don't add rejection to history usually, or maybe do.
                return
            
            # Generate
            model_name = os.getenv("LLM_MODEL_NAME", "gemini-2.0-flash-exp")
            logger.info(f"🧠 Using LLM Model: {model_name}")
            fast_service = FastGeminiService(model=model_name, lang=self.context.lang_code)
            ai_full_text = ""
            
            # Construct Prompt with History
            full_prompt = ""
            if len(self.history) > 1: # Has previous messages
                history_str = "Conversation History:\n"
                for msg in self.history[:-1]: # Exclude current query which is last
                    role = "User" if msg["role"] == "user" else "Assistant"
                    history_str += f"{role}: {msg['content']}\n"
                full_prompt = f"{history_str}\nCurrent User Query: {user_text}"
                logger.info(f"📜 Added history context ({len(self.history)-1} msgs)")
            else:
                full_prompt = user_text
            
            # CRITICAL: Force TTS Reset for Multi-Turn Stability
            # Send an EndFrame to flush any previous state in the TTS service
            # This ensures it's ready for the new turn.
            try:
                logger.critical("🔄 AgriNet: Forcing TTS Reset (EndFrame) before new turn")
                await self.push_frame(EndFrame())
            except: pass

            logger.info(f"🚀 Starting FAST LLM Generation...")
            
            # Helper for sentence buffering to avoid spamming TTS
            frame_buffer = ""
            
            async for chunk in fast_service.generate_response(full_prompt, self.metrics):
                if chunk:
                    ai_full_text += chunk
                    frame_buffer += chunk
                    
                    # Split on sentence boundaries, keeping the delimiter
                    # Supports: . ! ? \n and Amharic ። (Full Stop)
                    parts = re.split('([.!?\n።])', frame_buffer)
                    
                    # If we have delimiters, we have complete sentences
                    # Format: [sent, delim, sent, delim, ..., remainder]
                    if len(parts) > 1:
                        # Iterate over pairs (sent + delim)
                        for i in range(0, len(parts)-1, 2):
                            sentence = parts[i] + parts[i+1]
                            
                            try:
                                logger.critical(f"🗣️ Pushing TTS Chunk: '{sentence}'")
                                # Append \n to FORCE FLUSH the aggregator
                                await self.push_frame(TextFrame(text=sentence + "\n"))
                            except Exception as e:
                                logger.warning(f"Frame push failed: {e}")
                        
                        # Set buffer to the last part (remainder)
                        frame_buffer = parts[-1]
                    
                    # Safety valve: If buffer huge (no punctuation), flush it
                    if len(frame_buffer) > 200:
                         try:
                             logger.critical(f"🗣️ Pushing TTS Buffer (Overflow): '{frame_buffer}'")
                             await self.push_frame(TextFrame(text=frame_buffer + "\n"))
                             frame_buffer = ""
                         except Exception as e:
                             pass
            
            # Push remaining buffer
            if frame_buffer:
                 try:
                     logger.critical(f"🗣️ Pushing Final TTS Chunk: '{frame_buffer}'")
                     await self.push_frame(TextFrame(text=frame_buffer))
                 except Exception as e:
                     logger.warning(f"Frame push failed: {e}")
            
            # Check if we generated anything
            if not ai_full_text:
                logger.warning("⚠️ AgriNet: No response generated! Sending fallback.")
                ai_full_text = "I'm sorry, I couldn't find the information you asked for. Please try again."
                try:
                    await self.push_frame(TextFrame(text=ai_full_text))
                except:
                    pass

            # Add AI Response to History
            self.history.append({"role": "assistant", "content": ai_full_text})

            # Send full response directly to frontend via websocket
            logger.info(f"📤 Sending response to frontend: '{ai_full_text[:50]}...'")
            await self._websocket.send_json({
                "type": "llm_chunk",
                "text": ai_full_text,
                "turn_id": str(uuid.uuid4())
            })
            
            # Try to push end frame for TTS
            try:
                await self.push_frame(LLMFullResponseEndFrame())
            except Exception as e:
                logger.warning(f"EndFrame push failed: {e}")

        except asyncio.CancelledError:
            logger.info("🛑 AgriNet: Response generation cancelled (User spoke again)")
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            import traceback
            traceback.print_exc()

class RawFastAPIWebsocketInputTransport(BaseInputTransport):
    def __init__(self, websocket: WebSocket, params):
        super().__init__(params)
        self._websocket = websocket
        self._running = True
        self._packet_count = 0
        self._vad_analyzer = params.vad_analyzer

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
        
        # VAD state tracking
        self._speech_started = False
        self._speaking_count = 0 
        self._quiet_count = 0
        SPEAKING_THRESHOLD = 2
        QUIET_THRESHOLD = 6
        
        try:
            while self._running:
                message = await self._websocket.receive()
                if "bytes" in message:
                    data = message["bytes"]
                    self._packet_count += 1
                    if self._packet_count % 25 == 0:
                        logger.info(f"📦 Received {self._packet_count} packets")
                    
                    try:
                        audio_float = np.frombuffer(data, dtype=np.float32)
                        audio_float = audio_float * 4.0
                        audio_float = np.clip(audio_float, -1.0, 1.0)
                        
                        audio_int16 = (audio_float * 32767).astype(np.int16)
                        pcm_data = audio_int16.tobytes()
                        frame = InputAudioRawFrame(
                            audio=pcm_data,
                            num_channels=1,
                            sample_rate=16000
                        )
                        
                        if self._vad_analyzer:
                            try:
                                vad_result = await self._vad_analyzer.analyze_audio(frame.audio)
                                res_str = str(vad_result)
                                
                                if "SPEAKING" in res_str or "STARTING" in res_str:
                                    self._speaking_count += 1
                                    self._quiet_count = 0
                                    
                                    if not self._speech_started and self._speaking_count >= SPEAKING_THRESHOLD:
                                        self._speech_started = True
                                        logger.info(f"🟢 Speech STARTED")
                                        await self.push_frame(UserStartedSpeakingFrame())
                                        await self._websocket.send_json({"type": "speech_start"})
                                        
                                elif "STOPPING" in res_str or "QUIET" in res_str:
                                    self._quiet_count += 1
                                    self._speaking_count = 0
                                    
                                    if self._speech_started and self._quiet_count >= QUIET_THRESHOLD:
                                        self._speech_started = False
                                        logger.info(f"🔴 Speech STOPPED")
                                        await self.push_frame(UserStoppedSpeakingFrame())
                                        await self._websocket.send_json({"type": "speech_end"})
                                
                            except Exception as e:
                                logger.error(f"VAD error: {e}")
                        
                        await self.push_frame(frame)
                        
                    except ValueError as ve:
                        logger.warning(f"Failed to convert audio bytes: {ve}")
                        
                elif "text" in message:
                    logger.info(f"Received text message: {message['text']}")
                    
        except Exception as e:
            logger.warning(f"Websocket read error: {e}")
            await self.push_frame(EndFrame())

class RawFastAPIWebsocketOutputTransport(BaseOutputTransport):
    def __init__(self, websocket: WebSocket, params):
        super().__init__(params)
        self._websocket = websocket
        self._text_buffer = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, (StartFrame, EndFrame, CancelFrame, StartInterruptionFrame)):
             await super().process_frame(frame, direction)
             return

        if isinstance(frame, (TTSAudioRawFrame, TextFrame, LLMFullResponseEndFrame, JSONMessageFrame)):
             await self.send_frame(frame)
        
        await self.push_frame(frame, direction)

    async def send_frame(self, frame: Frame):
        if isinstance(frame, TTSAudioRawFrame):
            try:
                logger.info(f"📤 Sending Audio Chunk: {len(frame.audio)} bytes")
                await self._websocket.send_bytes(frame.audio)
            except Exception as e:
                logger.error(f"Failed to send audio: {e}")
        elif isinstance(frame, TextFrame):
             self._text_buffer.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
             self._text_buffer = []
        elif isinstance(frame, JSONMessageFrame):
             try:
                 await self._websocket.send_json(frame.message)
             except Exception as e:
                 logger.error(f"Failed to send JSON frame: {e}")

class TranscriptionNotifier(FrameProcessor):
    def __init__(self, websocket):
        super().__init__()
        self._websocket = websocket

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Handle control frames - call super AND push to next processor
        if isinstance(frame, (StartFrame, EndFrame, CancelFrame)):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)  # Also push to next processor!
            return
        
        # For all other frames, explicitly push to next processor
        await self.push_frame(frame, direction)
        
        text_content = ""
        is_final = False
        
        if isinstance(frame, TextFrame):
            text_content = frame.text
            is_final = True
            logger.info(f"🔔 Final Transcript: {text_content}")
            
        elif isinstance(frame, TranscriptionFrame):
            text_content = frame.text
            is_final = False 
            
        if text_content:
             try:
                 await self._websocket.send_json({
                     "type": "transcription",
                     "text": text_content,
                     "role": "user",
                     "is_final": is_final
                 })
             except Exception as e:
                 logger.error(f"Failed to send transcription: {e}")

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
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams

    # Settings optimized for 128ms packets (buffer=2048)
    vad_analyzer = SileroVADAnalyzer(params=VADParams(
        start_secs=0.15,      # Start detection after 150ms of speech
        stop_secs=0.8,        # Snappy VAD - Latency handled by Service
        confidence=0.4,       
        min_volume=0.01       
    ))

    # 0. Wrap WebSocket with Lock to prevent concurrent write errors
    class LockedWebSocket:
        def __init__(self, ws: WebSocket):
            self.ws = ws
            self.lock = asyncio.Lock()
            # Proxy other attrs
            self.client = ws.client
            self.query_params = ws.query_params
        
        async def send_json(self, data: dict):
            async with self.lock:
                try:
                    await self.ws.send_json(data)
                except (RuntimeError, ConnectionError) as e:
                     logger.warning(f"⚠️ ws.send_json failed (client disconnected?): {e}")
        
        async def send_bytes(self, data: bytes):
            async with self.lock:
                logger.critical(f"🔊 SENDING AUDIO: {len(data)} bytes")
                try:
                    await self.ws.send_bytes(data)
                    # logger.critical("✅ AUDIO SENT SUCCESSFULLY")
                except Exception as e:
                    logger.critical(f"❌ SEND FAILED: {e}")
                    raise
                
        async def receive_bytes(self):
            return await self.ws.receive_bytes()
            
        async def receive(self):
            return await self.ws.receive()

        async def accept(self):
            await self.ws.accept()

        async def close(self, code=1000):
            await self.ws.close(code)

    locked_ws = LockedWebSocket(websocket)

    transport = RawFastAPIWebsocketTransport(
        websocket=locked_ws,
        params=TransportParams(
            audio_out_enabled=True,
            audio_in_enabled=True,
            vad_analyzer=vad_analyzer
        )
    )

    # 2. Services
    azure_key = os.getenv("azure_foundary_api_key")
    azure_region = os.getenv("azure_foundary_region")

    logger.info(f"Azure STT initialized: region={azure_region}")
    
    # Initialize metrics with required keys to prevent KeyErrors
    enable_mod = os.getenv("ENABLE_MODERATION", "false").lower().strip() == "true"
    metrics = {
        'timings': [],
        'mod_status': "Enabled" if enable_mod else "Disabled"
    }

    # Use Instrumented service for metrics
    stt = InstrumentedAzureSTTService(
        metrics=metrics,
        api_key=azure_key,
        region=azure_region,
        language="en-US" if lang == "en" else "am-ET",
        sample_rate=16000
    )
    
    selected_voice = "en-US-AriaNeural" if lang == "en" else "am-ET-MekdesNeural"
    
    # Use Instrumented service for metrics
    tts = InstrumentedAzureTTSService(
        metrics=metrics,
        api_key=azure_key,
        region=azure_region,
        voice=selected_voice,
        sample_rate=16000
    )

    # LLM (with Buffer Logic)
    context = FarmerContext(lang_code=lang, query="[Voice Session Initialized]")
    llm = AgriNetLLMService(context=context, metrics=metrics, websocket=locked_ws)
    
    # Notifier
    transcription_notifier = TranscriptionNotifier(websocket=locked_ws)

    # 3. Pipeline Definition
    pipeline = Pipeline([
        transport.input(),   # Source
        stt,                 # STT
        transcription_notifier, # Streaming Logs
        llm,                 # Logic + Generation + Delay
        tts,                 # Audio Output
        transport.output()   # Sink
    ])
    
    # 4. Run
    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    
    logger.info(f"Starting Pipecat pipeline for session {session_id}")
    await runner.run(task)
