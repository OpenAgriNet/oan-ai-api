"""
Production-Ready Conversation Pipeline
Industry standard implementation with proper concurrency, resource management, and error handling.
"""

import asyncio
import uuid
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional, List, Tuple
import numpy as np
import torch
from fastapi import WebSocket, WebSocketDisconnect

from app.services.providers.transcription import get_transcription_provider
from app.services.providers.llm import get_llm_provider
from app.services.providers.tts import get_tts_provider
from app.services.providers.vad import get_vad_provider
from helpers.utils import get_logger, pcm_to_base64_wav

from agents.agrinet import agrinet_agent
from agents.deps import FarmerContext

logger = get_logger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for Conversation Pipeline"""
    SAMPLE_RATE: int = 16000
    VAD_CHUNK_SIZE: int = 512  # 512 samples @ 16kHz = 32ms per chunk
    VAD_THRESHOLD: float = 0.5

   
    SILENCE_DURATION_SHORT: float = 0.8  # Increased from 0.5s - allow natural pauses in speech
    SILENCE_DURATION_LONG: float = 1.2   # Increased from 0.8s - allow thinking pauses
    SPEECH_DURATION_THRESHOLD: float = 2.0  
    
    MAX_SPEECH_DURATION: float = 60.0  
    MIN_SPEECH_DURATION: float = 0.3   # Reduced from 0.5s - filter very short noise

    # Timeouts
    ASR_TIMEOUT: float = 10.0
    LLM_TIMEOUT: float = 30.0
    TTS_TIMEOUT: float = 15.0
    QUEUE_GET_TIMEOUT: float = 0.1  

    # Queue limits to prevent unbounded growth
    AUDIO_QUEUE_SIZE: int = 100
    SPEECH_QUEUE_SIZE: int = 10
    TEXT_QUEUE_SIZE: int = 10
    LLM_QUEUE_SIZE: int = 50
    TTS_QUEUE_SIZE: int = 100

    @property
    def CHUNK_DURATION_MS(self) -> float:
        """Duration of each VAD chunk in milliseconds"""
        return (self.VAD_CHUNK_SIZE / self.SAMPLE_RATE) * 1000  # ~32ms

    def get_silence_chunks(self, speech_duration_seconds: float) -> int:
        """
        Get adaptive silence threshold based on how long user has been speaking.
        
        Rationale:
        - Short utterances (e.g., "yes", "no", "hello"): User is likely done, 
          use shorter silence (0.5s) for faster response.
        - Longer utterances (questions, descriptions): User may pause to think,
          use longer silence (0.8s) to avoid cutting off mid-thought.
        
        Args:
            speech_duration_seconds: How long the user has been speaking
            
        Returns:
            Number of silence chunks needed before finalizing
        """
        if speech_duration_seconds < self.SPEECH_DURATION_THRESHOLD:
            silence_duration = self.SILENCE_DURATION_SHORT
        else:
            silence_duration = self.SILENCE_DURATION_LONG
            
        return int((silence_duration * self.SAMPLE_RATE) / self.VAD_CHUNK_SIZE)

    @property
    def MAX_SPEECH_CHUNKS(self) -> int:
        """Maximum chunks for speech (prevents unbounded accumulation)"""
        return int((self.MAX_SPEECH_DURATION * self.SAMPLE_RATE) / self.VAD_CHUNK_SIZE)
    
    @property
    def SPEECH_THRESHOLD_CHUNKS(self) -> int:
        """Chunks threshold to determine short vs long utterance"""
        return int((self.SPEECH_DURATION_THRESHOLD * self.SAMPLE_RATE) / self.VAD_CHUNK_SIZE)


class PipelineState:
    """Thread-safe state manager with proper synchronization"""

    def __init__(self, lang: str = "en"):
        self.turn_id: int = 0
        self.is_speaking: bool = False
        self.is_processing: bool = False  # NEW: Track if system is processing (LLM/TTS)
        self.is_playing_audio: bool = False  # NEW: Track if system is playing audio back
        self.pending_amendment: Optional[str] = None  # NEW: Speech captured during processing
        self.amendment_original_query: Optional[str] = None  # NEW: Original query when amendment was captured
        self.current_query: str = ""  # NEW: Track current query being processed
        self.conversation_id: str = str(uuid.uuid4())
        self.lang: str = lang
        self.should_stop: bool = False
        self.history: List[dict] = [
            {"role": "system", "content": "You are a helpful assistant. Keep answers concise."}
        ]

        # Locks for thread-safe access
        self._turn_lock = asyncio.Lock()
        self._speaking_lock = asyncio.Lock()
        self._processing_lock = asyncio.Lock()
        self._playing_lock = asyncio.Lock()
        self._amendment_lock = asyncio.Lock()
        self._history_lock = asyncio.Lock()

    async def increment_turn(self) -> int:
        """Safely increment turn ID"""
        async with self._turn_lock:
            self.turn_id += 1
            return self.turn_id

    async def get_turn_id(self) -> int:
        """Safely get current turn ID"""
        async with self._turn_lock:
            return self.turn_id

    async def set_speaking(self, value: bool):
        """Safely set speaking state"""
        async with self._speaking_lock:
            self.is_speaking = value

    async def get_speaking(self) -> bool:
        """Safely get speaking state"""
        async with self._speaking_lock:
            return self.is_speaking

    async def set_processing(self, value: bool):
        """Safely set processing state (LLM/TTS working)"""
        async with self._processing_lock:
            self.is_processing = value

    async def get_processing(self) -> bool:
        """Safely get processing state"""
        async with self._processing_lock:
            return self.is_processing

    async def set_playing_audio(self, value: bool):
        """Safely set audio playback state"""
        async with self._playing_lock:
            self.is_playing_audio = value

    async def get_playing_audio(self) -> bool:
        """Safely get audio playback state"""
        async with self._playing_lock:
            return self.is_playing_audio

    async def set_pending_amendment(self, text: Optional[str]):
        """Set pending amendment text (speech captured during processing)"""
        async with self._amendment_lock:
            if text:
                if self.pending_amendment:
                    # Append to existing amendment
                    self.pending_amendment = f"{self.pending_amendment} {text}"
                    logger.info(f"Appended to amendment: '{text}' -> '{self.pending_amendment}'")
                else:
                    # First amendment - store with original query
                    self.pending_amendment = text
                    self.amendment_original_query = self.current_query
                    logger.info(f"Stored amendment: '{text}' for original query: '{self.current_query}'")
            else:
                self.pending_amendment = None
                self.amendment_original_query = None

    async def get_and_clear_amendment(self) -> Tuple[Optional[str], Optional[str]]:
        """Get and clear pending amendment, returns (amendment_text, original_query)"""
        async with self._amendment_lock:
            amendment = self.pending_amendment
            original = self.amendment_original_query
            self.pending_amendment = None
            self.amendment_original_query = None
            return (amendment, original)

    async def set_current_query(self, query: str):
        """Set the current query being processed"""
        async with self._amendment_lock:
            self.current_query = query

    async def get_current_query(self) -> str:
        """Get the current query"""
        async with self._amendment_lock:
            return self.current_query

    async def add_to_history(self, role: str, content: str):
        """Safely add to conversation history"""
        async with self._history_lock:
            self.history.append({"role": role, "content": content})

    async def get_history(self) -> List[dict]:
        """Safely get conversation history"""
        async with self._history_lock:
            return self.history.copy()


class AudioBuffer:
    """Efficient audio buffer with thread-safe operations"""

    def __init__(self):
        self._buffer = bytearray()
        self._lock = asyncio.Lock()

    async def extend(self, data: bytes):
        """Thread-safe extend"""
        async with self._lock:
            self._buffer.extend(data)

    async def get_chunk(self, size: int) -> Optional[bytes]:
        """Thread-safe chunk retrieval"""
        async with self._lock:
            if len(self._buffer) >= size:
                chunk = self._buffer[:size]
                self._buffer = self._buffer[size:]
                return bytes(chunk)
            return None

    async def clear(self):
        """Thread-safe clear"""
        async with self._lock:
            self._buffer.clear()

    async def size(self) -> int:
        """Thread-safe size check"""
        async with self._lock:
            return len(self._buffer)


class WebSocketManager:
    """Thread-safe WebSocket sender"""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self._send_lock = asyncio.Lock()

    async def send_json(self, data: dict):
        """Thread-safe JSON send"""
        async with self._send_lock:
            try:
                await self.websocket.send_json(data)
            except Exception as e:
                logger.warning(f"Failed to send JSON: {e}")
                raise

    async def send_bytes(self, data: bytes):
        """Thread-safe binary send"""
        async with self._send_lock:
            try:
                await self.websocket.send_bytes(data)
            except Exception as e:
                logger.warning(f"Failed to send bytes: {e}")
                raise

    async def accept(self):
        """Safe WebSocket accept"""
        try:
            await self.websocket.accept()
        except Exception as e:
            logger.error(f"Failed to accept WebSocket: {e}")
            raise


class ConversationPipeline:
    """Production-ready conversation pipeline with all bugs fixed"""

    def __init__(self, websocket: WebSocket, lang: str = "en"):
        self.ws_manager = WebSocketManager(websocket)
        self.config = PipelineConfig()
        self.state = PipelineState(lang)

        # Queues with backpressure limits
        self.audio_queue: asyncio.Queue = asyncio.Queue(maxsize=self.config.AUDIO_QUEUE_SIZE)
        self.speech_queue: asyncio.Queue = asyncio.Queue(maxsize=self.config.SPEECH_QUEUE_SIZE)
        self.text_queue: asyncio.Queue = asyncio.Queue(maxsize=self.config.TEXT_QUEUE_SIZE)
        self.llm_queue: asyncio.Queue = asyncio.Queue(maxsize=self.config.LLM_QUEUE_SIZE)
        self.tts_queue: asyncio.Queue = asyncio.Queue(maxsize=self.config.TTS_QUEUE_SIZE)

        # Initialize providers once
        self.vad_provider = get_vad_provider()
        self.asr_provider = get_transcription_provider()
        self.llm_provider = get_llm_provider()
        self.tts_provider = get_tts_provider()

        # Metrics - Enhanced with detailed timing
        self.metrics = {
            "turns": 0,
            "interruptions": 0,
            "errors": 0,
            "start_time": time.time(),
            "asr_times": [],  
            "llm_times": [],  
            "tts_times": [],  
            "turn_durations": [],  
            "total_audio_received": 0,  
            "total_audio_sent": 0,  
        }

        
        self.turn_timings = {}  

    async def run(self):
        try:
            await self.ws_manager.accept()
            logger.info(f"Pipeline started for {self.state.conversation_id} (lang={self.state.lang})")

            tasks = [
                asyncio.create_task(self._receive_worker(), name="receive"),
                asyncio.create_task(self._vad_worker(), name="vad"),
                asyncio.create_task(self._asr_worker(), name="asr"),
                asyncio.create_task(self._llm_worker(), name="llm"),
                asyncio.create_task(self._tts_worker(), name="tts"),
                asyncio.create_task(self._send_worker(), name="send"),
            ]

            try:
                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Log completion/failure
                for task in done:
                    if task.exception():
                        logger.error(f"Task {task.get_name()} failed: {task.exception()}")
                    else:
                        logger.info(f"Task {task.get_name()} completed")

            except Exception as e:
                logger.error(f"Pipeline runtime error: {e}", exc_info=True)
            finally:
                await self._cleanup(tasks)

        except Exception as e:
            logger.error(f"Pipeline initialization error: {e}", exc_info=True)
            raise

    async def _cleanup(self, tasks: List[asyncio.Task]):
        """Proper cleanup with awaited cancellation"""
        logger.info("Starting pipeline cleanup...")
        self.state.should_stop = True

        # Cancel all tasks
        for task in tasks:
            if not task.done():
                task.cancel()

        # Wait for cancellation to complete 
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Calculate comprehensive metrics
        runtime = time.time() - self.metrics["start_time"]

        # Calculate averages
        avg_asr_time = (
            sum(t[1] for t in self.metrics["asr_times"]) / len(self.metrics["asr_times"])
            if self.metrics["asr_times"] else 0
        )
        avg_llm_time = (
            sum(t[1] for t in self.metrics["llm_times"]) / len(self.metrics["llm_times"])
            if self.metrics["llm_times"] else 0
        )
        avg_tts_time = (
            sum(t[1] for t in self.metrics["tts_times"]) / len(self.metrics["tts_times"])
            if self.metrics["tts_times"] else 0
        )

        # Log comprehensive summary
        logger.info("=" * 80)
        logger.info("CONVERSATION SESSION SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Conversation ID: {self.state.conversation_id}")
        logger.info(f"Language: {self.state.lang}")
        logger.info(f"Total Runtime: {runtime:.2f}s ({runtime/60:.1f} minutes)")
        logger.info("-" * 80)
        logger.info(f"Total Turns: {self.metrics['turns']}")
        logger.info(f"Total Interruptions: {self.metrics['interruptions']}")
        logger.info(f"Total Errors: {self.metrics['errors']}")
        logger.info("-" * 80)
        logger.info(f"Audio Received: {self.metrics['total_audio_received'] / 1024:.1f} KB")
        logger.info(f"Audio Sent: {self.metrics['total_audio_sent'] / 1024:.1f} KB")
        logger.info("-" * 80)
        logger.info("TIMING BREAKDOWN:")
        logger.info(f"  ASR (Transcription):")
        logger.info(f"    • Requests: {len(self.metrics['asr_times'])}")
        logger.info(f"    • Average Time: {avg_asr_time:.3f}s")
        logger.info(f"    • Min: {min((t[1] for t in self.metrics['asr_times']), default=0):.3f}s")
        logger.info(f"    • Max: {max((t[1] for t in self.metrics['asr_times']), default=0):.3f}s")
        logger.info(f"  LLM (Generation):")
        logger.info(f"    • Requests: {len(self.metrics['llm_times'])}")
        logger.info(f"    • Average Time: {avg_llm_time:.3f}s")
        logger.info(f"    • Min: {min((t[1] for t in self.metrics['llm_times']), default=0):.3f}s")
        logger.info(f"    • Max: {max((t[1] for t in self.metrics['llm_times']), default=0):.3f}s")
        logger.info(f"  TTS (Synthesis):")
        logger.info(f"    • Requests: {len(self.metrics['tts_times'])}")
        logger.info(f"    • Average Time: {avg_tts_time:.3f}s")
        logger.info(f"    • Min: {min((t[1] for t in self.metrics['tts_times']), default=0):.3f}s")
        logger.info(f"    • Max: {max((t[1] for t in self.metrics['tts_times']), default=0):.3f}s")
        logger.info("-" * 80)

        # Per-turn breakdown with detailed timing
        if self.turn_timings:
            logger.info("PER-TURN DETAILED TIMING:")
            for turn_id in sorted(self.turn_timings.keys()):
                timings = self.turn_timings[turn_id]

                # Calculate phase durations
                start = timings.get("start", 0)
                speech_end = timings.get("speech_end", 0)
                asr_start = timings.get("asr_start", 0)
                asr_end = timings.get("asr_end", 0)
                llm_start = timings.get("llm_start", 0)
                llm_end = timings.get("llm_end", 0)
                tts_start = timings.get("tts_start", 0)
                tts_end = timings.get("tts_end", 0)
                last_audio = timings.get("last_audio_sent", 0)

                # Calculate durations
                speech_duration = (speech_end - start) if speech_end and start else 0
                asr_duration = (asr_end - asr_start) if asr_end and asr_start else 0
                llm_duration = (llm_end - llm_start) if llm_end and llm_start else 0
                tts_duration = (tts_end - tts_start) if tts_end and tts_start else 0
                total_duration = (last_audio - start) if last_audio and start else 0

                # Log detailed breakdown
                logger.info(f"  Turn {turn_id}:")
                logger.info(f"    ├─ User Speech: {speech_duration:.2f}s")
                logger.info(f"    ├─ ASR Processing: {asr_duration:.3f}s")
                logger.info(f"    ├─ LLM Generation: {llm_duration:.3f}s")
                logger.info(f"    ├─ TTS Synthesis: {tts_duration:.3f}s")
                logger.info(f"    └─ Total Turn Duration: {total_duration:.2f}s")

                # Store total duration for summary
                if total_duration > 0:
                    self.metrics["turn_durations"].append((turn_id, total_duration))

        logger.info("=" * 80)

    async def _receive_worker(self):
        """Reads WebSocket frame-by-frame"""
        try:
            while not self.state.should_stop:
                try:
                    # Try to receive either bytes (audio) or text (JSON commands)
                    message = await self.ws_manager.websocket.receive()
                    
                    if "bytes" in message:
                        # Audio data
                        data = message["bytes"]
                        # Track audio received
                        self.metrics["total_audio_received"] += len(data)

                        # Use put with timeout to prevent blocking if queue full
                        try:
                            await asyncio.wait_for(
                                self.audio_queue.put(data),
                                timeout=1.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning("Audio queue full, dropping frame")
                    
                    elif "text" in message:
                        # JSON message (e.g., text query from clicking suggestion)
                        import json
                        try:
                            data = json.loads(message["text"])
                            if data.get("type") == "text" and data.get("text"):
                                # User sent text message (clicked suggestion)
                                text_query = data["text"]
                                logger.info(f"Received text message: '{text_query}'")
                                
                                # Process as if it was transcribed speech
                                # Put directly into speech queue
                                turn_id = await self.state.increment_turn()
                                await self.speech_queue.put((text_query, turn_id))
                                
                                # Send transcription event to frontend
                                await self.ws_manager.send_json({
                                    "type": "transcription",
                                    "text": text_query,
                                    "turn_id": turn_id
                                })
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid JSON message: {message['text']}")

                except WebSocketDisconnect:
                    logger.info("Client disconnected")
                    self.state.should_stop = True
                    break

        except asyncio.CancelledError:
            logger.debug("Receive worker cancelled")
            raise
        except Exception as e:
            logger.error(f"Receive error: {e}", exc_info=True)
            self.state.should_stop = True

    async def _vad_worker(self):
        """
        VAD Logic with adaptive silence detection
        Uses speech duration to determine appropriate silence threshold:
        - Short utterances: faster response (0.5s silence)
        - Long utterances: allow thinking pauses (0.8s silence)
        """
        buffer = AudioBuffer()
        processing_buffer = bytearray()

        speech_accumulator = []  
        silence_counter = 0
        speech_chunk_counter = 0  
        pending_speech_end = False
        pending_turn_id = None

        vad_iterator = self.vad_provider.get_iterator(
            sampling_rate=self.config.SAMPLE_RATE,
            threshold=self.config.VAD_THRESHOLD
        )

        CHUNK_SIZE_BYTES = self.config.VAD_CHUNK_SIZE * 4  # float32 = 4 bytes

        try:
            while not self.state.should_stop:
                try:
                    # Get data with timeout
                    try:
                        data = await asyncio.wait_for(
                            self.audio_queue.get(),
                            timeout=self.config.QUEUE_GET_TIMEOUT
                        )
                        await buffer.extend(data)
                    except asyncio.TimeoutError:
                        pass

                    # Process chunks
                    while True:
                        chunk_bytes = await buffer.get_chunk(CHUNK_SIZE_BYTES)
                        if not chunk_bytes:
                            break

                        # Convert to float32 tensor
                        chunk_np = np.frombuffer(chunk_bytes, dtype=np.float32)
                        chunk_copy = chunk_np.copy()  # Safety copy
                        audio_tensor = torch.from_numpy(chunk_np)

                        # Run VAD in executor to avoid blocking
                        loop = asyncio.get_running_loop()
                        speech_dict = await loop.run_in_executor(
                            None,
                            lambda: vad_iterator(audio_tensor, return_seconds=True)
                        )

                        is_speaking = await self.state.get_speaking()

                        if speech_dict is None:
                            # No state change
                            if is_speaking:
                                # Check for maximum speech duration
                                if speech_chunk_counter >= self.config.MAX_SPEECH_CHUNKS:
                                    logger.warning(
                                        f"Max speech duration ({self.config.MAX_SPEECH_DURATION}s) "
                                        f"reached, force finalizing turn"
                                    )
                                    await self._finalize_turn(
                                        speech_accumulator.copy(),
                                        pending_turn_id
                                    )
                                    speech_accumulator = []
                                    pending_speech_end = False
                                    silence_counter = 0
                                    speech_chunk_counter = 0
                                    await self.state.set_speaking(False)
                                    continue

                                speech_accumulator.append(chunk_copy)
                                speech_chunk_counter += 1

                                # Adaptive silence detection based on speech duration
                                if pending_speech_end:
                                    silence_counter += 1
                                    
                                    # Calculate current speech duration
                                    speech_duration = speech_chunk_counter * self.config.VAD_CHUNK_SIZE / self.config.SAMPLE_RATE
                                    
                                    # Get adaptive silence threshold
                                    required_silence_chunks = self.config.get_silence_chunks(speech_duration)

                                    # Finalize when silence threshold met
                                    if silence_counter >= required_silence_chunks:
                                        await self._finalize_turn(
                                            speech_accumulator.copy(),  
                                            pending_turn_id
                                        )
                                        speech_accumulator = []
                                        pending_speech_end = False
                                        silence_counter = 0
                                        speech_chunk_counter = 0

                        elif "start" in speech_dict:
                            # Speech start detected
                            current_turn = await self.state.get_turn_id()
                            was_speaking = await self.state.get_speaking()
                            is_processing = await self.state.get_processing()
                            is_playing = await self.state.get_playing_audio()

                            # Check if this is resumption of current speech (not a real barge-in)
                            if was_speaking and pending_speech_end:
                                # User resumed speaking during silence countdown
                                # This is NOT a barge-in, just continuation of same speech
                                logger.debug(f"Speech resumed during silence countdown (Turn {current_turn})")
                                pending_speech_end = False
                                silence_counter = 0
                                speech_accumulator.append(chunk_copy)
                                speech_chunk_counter += 1
                                # Don't create new turn, continue current one

                            elif is_processing and not is_playing:
                                # System is processing (LLM/TTS) but not yet playing audio
                                # Capture this speech - it might be an amendment to the query
                                # We'll transcribe it and decide later if it's meaningful
                                logger.info(f"Speech detected during processing (Turn {current_turn}) - capturing for potential amendment")
                                
                                # Start capturing amendment speech
                                new_turn_id = await self.state.increment_turn()
                                await self.state.set_speaking(True)
                                pending_turn_id = new_turn_id

                                # Reset counters
                                pending_speech_end = False
                                silence_counter = 0
                                speech_accumulator = [chunk_copy]
                                speech_chunk_counter = 1

                                # Track turn start time
                                self.turn_timings[new_turn_id] = {"start": time.time(), "is_amendment": True}

                                logger.info(f"Amendment Speech START (Turn {new_turn_id})")
                                # Don't increment turns metric for amendments

                                await self.ws_manager.send_json({
                                    "type": "speech_start",
                                    "turn_id": new_turn_id,
                                    "is_amendment": True
                                })

                            elif is_processing and is_playing:
                                # System is processing AND playing "thinking" audio
                                # This is still an amendment - user is adding to their query
                                logger.info(f"Speech detected during thinking audio (Turn {current_turn}) - capturing as amendment")
                                
                                # Start capturing amendment speech
                                new_turn_id = await self.state.increment_turn()
                                await self.state.set_speaking(True)
                                pending_turn_id = new_turn_id

                                # Reset counters
                                pending_speech_end = False
                                silence_counter = 0
                                speech_accumulator = [chunk_copy]
                                speech_chunk_counter = 1

                                # Track turn start time
                                self.turn_timings[new_turn_id] = {"start": time.time(), "is_amendment": True}

                                logger.info(f"Amendment Speech START during thinking (Turn {new_turn_id})")

                                await self.ws_manager.send_json({
                                    "type": "speech_start",
                                    "turn_id": new_turn_id,
                                    "is_amendment": True
                                })

                            else:
                                # Real barge-in (during audio playback) or first speech start
                                if was_speaking:
                                    # User interrupted - genuine barge-in
                                    logger.info(f"Barge-in detected during turn {current_turn}")
                                    self.metrics["interruptions"] += 1
                                elif is_playing:
                                    # User interrupted during audio playback - this is intentional
                                    logger.info(f"User interrupted audio playback (Turn {current_turn})")
                                    self.metrics["interruptions"] += 1
                                    # Clear any pending amendments - user is starting fresh
                                    await self.state.set_pending_amendment(None)

                                # Clear processing state since user is taking over
                                await self.state.set_processing(False)
                                await self.state.set_playing_audio(False)

                                # Start new turn with proper synchronization
                                new_turn_id = await self.state.increment_turn()
                                await self.state.set_speaking(True)
                                pending_turn_id = new_turn_id

                                # Reset counters
                                pending_speech_end = False
                                silence_counter = 0
                                speech_accumulator = [chunk_copy]
                                speech_chunk_counter = 1

                                # Track turn start time
                                self.turn_timings[new_turn_id] = {"start": time.time()}

                                logger.info(f"Speech START (Turn {new_turn_id})")
                                self.metrics["turns"] += 1

                                await self.ws_manager.send_json({
                                    "type": "speech_start",
                                    "turn_id": new_turn_id
                                })

                        elif "end" in speech_dict:
                            if is_speaking:
                                # Silence detected, start counting
                                # Don't finalize immediately - wait for adaptive threshold
                                if not pending_speech_end:
                                    # Calculate current speech duration for logging
                                    speech_duration = speech_chunk_counter * self.config.VAD_CHUNK_SIZE / self.config.SAMPLE_RATE
                                    silence_threshold = self.config.get_silence_chunks(speech_duration) * self.config.VAD_CHUNK_SIZE / self.config.SAMPLE_RATE
                                    logger.info(f"Silence detected, waiting {silence_threshold:.1f}s (speech was {speech_duration:.1f}s)...")
                                pending_speech_end = True
                                silence_counter = 0
                                speech_accumulator.append(chunk_copy)
                                speech_chunk_counter += 1
                            # else: Silence when not speaking

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"VAD Error: {e}", exc_info=True)
                    self.metrics["errors"] += 1

        except asyncio.CancelledError:
            logger.debug("VAD worker cancelled")
            raise

    async def _finalize_turn(self, chunks: List[np.ndarray], turn_id: int):
        """
        End of turn logic with validation
        Uses copy of chunks to prevent race condition
        """
        try:
            logger.info(f"Speech END (Turn {turn_id})")
            await self.state.set_speaking(False)

            # Track speech end time
            if turn_id in self.turn_timings:
                self.turn_timings[turn_id]["speech_end"] = time.time()

            if not chunks:
                logger.warning("Empty chunks in finalize_turn")
                return

            full_audio = np.concatenate(chunks)
            duration = len(full_audio) / self.config.SAMPLE_RATE

            logger.info(f"Turn {turn_id} audio duration: {duration:.2f}s")

            if duration >= self.config.MIN_SPEECH_DURATION:
                try:
                    await asyncio.wait_for(
                        self.speech_queue.put((full_audio, turn_id)),
                        timeout=1.0
                    )
                    await self.ws_manager.send_json({
                        "type": "speech_end",
                        "turn_id": turn_id,
                        "duration": duration
                    })
                except asyncio.TimeoutError:
                    logger.error("Speech queue full, dropping turn")
                    self.metrics["errors"] += 1
            else:
                logger.info(f"Ignored short speech ({duration:.2f}s)")

        except Exception as e:
            logger.error(f"Error finalizing turn: {e}", exc_info=True)
            self.metrics["errors"] += 1

    async def _asr_worker(self):
        """ASR worker with proper timeout and validation"""
        try:
            while not self.state.should_stop:
                try:
                    # Get with timeout
                    item = await asyncio.wait_for(
                        self.speech_queue.get(),
                        timeout=self.config.QUEUE_GET_TIMEOUT
                    )
                    audio_np, turn_id = item

                    # Check if this is an amendment turn (speech during processing)
                    is_amendment = turn_id in self.turn_timings and self.turn_timings[turn_id].get("is_amendment", False)

                    # Convert and transcribe with timeout
                    audio_int16 = (audio_np * 32767).astype(np.int16)
                    audio_b64 = pcm_to_base64_wav(audio_int16)

                    # Track ASR start time
                    asr_start_time = time.time()
                    if turn_id in self.turn_timings:
                        self.turn_timings[turn_id]["asr_start"] = asr_start_time

                    try:
                        # Transcribe with timeout
                        text = await asyncio.wait_for(
                            self.asr_provider.transcribe(audio_b64, self.state.lang),
                            timeout=self.config.ASR_TIMEOUT
                        )

                        # Validate response
                        if text is None or not isinstance(text, str):
                            logger.error(f"Invalid ASR response: {type(text)}")
                            text = ""

                        text = text.strip()

                    except asyncio.TimeoutError:
                        logger.error(f"ASR timeout for turn {turn_id}")
                        text = ""

                    # Track ASR end time and duration
                    asr_end_time = time.time()
                    asr_duration = asr_end_time - asr_start_time
                    if turn_id in self.turn_timings:
                        self.turn_timings[turn_id]["asr_end"] = asr_end_time
                    self.metrics["asr_times"].append((turn_id, asr_duration))

                    # Handle amendment speech (captured during processing)
                    # Use the is_amendment flag from turn_timings as the reliable indicator
                    if is_amendment:
                        if text:
                            # Meaningful speech during processing - store as amendment
                            logger.info(f"ASR Amendment [{turn_id}]: '{text}' - storing for reprocessing")
                            await self.state.set_pending_amendment(text)
                            
                            await self.ws_manager.send_json({
                                "type": "transcription",
                                "text": text,
                                "turn_id": turn_id,
                                "is_amendment": True
                            })
                        else:
                            # Empty transcription during processing - just noise, ignore
                            logger.info(f"ASR Amendment [{turn_id}]: empty - ignoring noise")
                        continue  # Don't process as regular turn

                    # Regular turn processing
                    if text:
                        logger.info(f"ASR [{turn_id}]: {text} (took {asr_duration:.3f}s)")

                        # Mark this turn as having real transcription (not noise)
                        if turn_id in self.turn_timings:
                            self.turn_timings[turn_id]["has_transcription"] = True

                        # Add to history
                        await self.state.add_to_history("user", text)

                        try:
                            await asyncio.wait_for(
                                self.text_queue.put((text, turn_id)),
                                timeout=1.0
                            )
                            await self.ws_manager.send_json({
                                "type": "transcription",
                                "text": text,
                                "turn_id": turn_id
                            })
                        except asyncio.TimeoutError:
                            logger.error("Text queue full")
                            self.metrics["errors"] += 1
                    else:
                        logger.info(f"Empty transcription for turn {turn_id}")
                        
                        # Mark this turn as noise (no real transcription)
                        if turn_id in self.turn_timings:
                            self.turn_timings[turn_id]["has_transcription"] = False
                        
                        error_msg = "I'm sorry, I couldn't hear you clearly. Could you please repeat?"

                        # Send to LLM queue to be spoken via TTS
                        await self.llm_queue.put((error_msg, turn_id))
                        await self.llm_queue.put((None, turn_id))

                        # Also send JSON notification
                        await self.ws_manager.send_json({
                            "type": "llm_chunk",
                            "text": error_msg,
                            "turn_id": turn_id
                        })


                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"ASR Error: {e}", exc_info=True)
                    self.metrics["errors"] += 1

                    # Error recovery
                    error_msg = "I'm sorry, I couldn't hear you clearly. Could you please repeat?"
                    try:
                        current_turn = await self.state.get_turn_id()
                        await self.ws_manager.send_json({
                            "type": "error",
                            "message": error_msg,
                            "turn_id": current_turn
                        })
                    except Exception as e2:
                        logger.error(f"Failed to send error message: {e2}")

        except asyncio.CancelledError:
            logger.debug("ASR worker cancelled")
            raise

    async def _llm_worker(self):
        """LLM worker with proper resource management and amendment support"""
        try:
            while not self.state.should_stop:
                try:
                    # Get with timeout
                    item = await asyncio.wait_for(
                        self.text_queue.get(),
                        timeout=self.config.QUEUE_GET_TIMEOUT
                    )
                    text, turn_id = item

                    # Check if turn still valid - but be smart about it
                    # Don't drop a turn just because a newer turn exists
                    # Only drop if the newer turn has MEANINGFUL content (not noise/empty)
                    current_turn = await self.state.get_turn_id()
                    if turn_id != current_turn:
                        # Wait briefly for ASR to complete on newer turns before deciding
                        # This prevents dropping valid turns due to noise that hasn't been transcribed yet
                        await asyncio.sleep(0.5)  # Give ASR time to process newer turn
                        
                        # Re-check current turn (might have changed during sleep)
                        current_turn = await self.state.get_turn_id()
                        if turn_id == current_turn:
                            # Turn is now current again (newer turn was processed as noise)
                            logger.info(f"Turn {turn_id} is now current after waiting")
                        else:
                            # Check if ALL turns between turn_id and current_turn are:
                            # 1. Amendments (is_amendment=True), OR
                            # 2. Noise/empty (has_transcription=False)
                            should_drop = False
                            for check_turn in range(turn_id + 1, current_turn + 1):
                                if check_turn in self.turn_timings:
                                    turn_info = self.turn_timings[check_turn]
                                    is_amendment = turn_info.get("is_amendment", False)
                                    has_transcription = turn_info.get("has_transcription", None)
                                    
                                    # If newer turn has real transcription and is NOT an amendment, drop this turn
                                    if has_transcription is True and not is_amendment:
                                        should_drop = True
                                        logger.debug(f"Turn {check_turn} has real transcription, will drop turn {turn_id}")
                                        break
                                    # If has_transcription is False (noise) or None (still processing), continue checking
                            
                            if should_drop:
                                logger.debug(f"Dropping stale LLM turn {turn_id} (current: {current_turn}, newer turn has content)")
                                continue
                            else:
                                logger.info(f"Processing turn {turn_id} despite newer turn {current_turn} (newer turns are amendments/noise/pending)")

                    # Mark system as processing - captures amendments instead of interrupting
                    await self.state.set_processing(True)
                    await self.state.set_current_query(text)

                    # Get history for context
                    history = await self.state.get_history()

                    collected_text = ""
                    stream = None

                    # Track LLM start time
                    llm_start_time = time.time()
                    if turn_id in self.turn_timings:
                        self.turn_timings[turn_id]["llm_start"] = llm_start_time

                    # Send "thinking" feedback to user while LLM processes
                    # Run thinking audio synthesis in PARALLEL with LLM (don't block!)
                    # Note: Keep thinking messages minimal and non-committal
                    thinking_phrases = {
                        "en": "",  # No thinking message - go straight to response
                        "am": ""   # No thinking message in Amharic either
                    }
                    thinking_msg = thinking_phrases.get(self.state.lang, thinking_phrases["en"])
                    
                    # Only send thinking message if it's not empty
                    if thinking_msg:
                        # Send text to frontend immediately (don't wait for audio)
                        try:
                            await self.ws_manager.send_json({
                                "type": "thinking",
                                "text": thinking_msg,
                                "turn_id": turn_id
                            })
                            logger.info(f"Sent thinking message for turn {turn_id}")
                        except Exception as e:
                            logger.warning(f"Failed to send thinking message: {e}")
                        
                        # Synthesize thinking audio in background (non-blocking)
                        async def synthesize_thinking_audio():
                            try:
                                thinking_audio = await self.tts_provider._synthesize_chunk(thinking_msg, self.state.lang)
                                if thinking_audio:
                                    logger.info(f"Thinking audio synthesized ({len(thinking_audio)} bytes), sending to queue")
                                    await self.tts_queue.put((thinking_audio, turn_id))
                                    logger.info(f"Thinking audio queued for turn {turn_id}")
                            except Exception as e:
                                logger.warning(f"Failed to synthesize thinking audio: {e}")
                        
                        # Start thinking audio synthesis in background (don't await!)
                        asyncio.create_task(synthesize_thinking_audio())

                    # Track if we've sent the first real response chunk
                    first_response_chunk = True
                    chunk_count = 0  # Track chunks received from LLM

                    try:
                        # Use agent.run_stream for consistent caching and performance
                        # This matches text chat behavior and enables prompt caching
                        # Agent and context imported at module level for performance
                        
                        # Create context for agent
                        context = FarmerContext(
                            query=text,
                            lang_code=self.state.lang,
                        )
                        
                        # Format recent conversation context like text chat does
                        # This helps the LLM understand the conversation flow better
                        recent_context = ""
                        if len(history) > 1:  # More than just system prompt
                            # Get last few exchanges (user + assistant pairs)
                            recent_messages = []
                            for msg in history[-6:]:  # Last 6 messages (3 pairs)
                                if isinstance(msg, dict):
                                    role = msg.get('role', '')
                                    content = msg.get('content', '')
                                    if role in ['user', 'assistant'] and content:
                                        recent_messages.append(f"{role.capitalize()}: {content}")
                            
                            if recent_messages:
                                recent_context = "\n".join(recent_messages) + "\n\n"
                                logger.info(f"[Turn {turn_id}] 📝 Recent context:\n{recent_context}")
                        
                        # Prepend context to current query like text chat does
                        user_prompt_with_context = f"{recent_context}Current query: {text}" if recent_context else text
                        
                        # Use agent's run_stream for proper caching
                        # Match text chat behavior - don't pass instructions, let system prompt handle it
                        logger.info(f"[Turn {turn_id}] 🤖 Calling agent with:")
                        logger.info(f"  - user_prompt: '{user_prompt_with_context[:100]}...'")
                        logger.info(f"  - history length: {len(history)}")
                        
                        # Log last 3 messages from history for debugging
                        for i, msg in enumerate(history[-3:]):
                            if isinstance(msg, dict):
                                role = msg.get('role', 'unknown')
                                content = str(msg.get('content', ''))[:80]
                                logger.info(f"    History[-{3-i}]: {role}: {content}...")
                            else:
                                logger.info(f"    History[-{3-i}]: {type(msg).__name__}")
                        
                        # Start suggestions agent in parallel (non-blocking)
                        # This will run while the main agent is generating the response
                        # Can be disabled via ENABLE_SUGGESTIONS env var
                        suggestions_task = None
                        import os
                        enable_suggestions = os.getenv("ENABLE_SUGGESTIONS", "false").lower() == "true"
                        
                        if enable_suggestions:
                            try:
                                from agents.suggestions import suggestions_agent
                                # Format history for suggestions agent
                                history_text = "\n".join([
                                    f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                                    for msg in history[-6:] if isinstance(msg, dict) and msg.get('role') in ['user', 'assistant']
                                ])
                                suggestions_prompt = f"Conversation History:\n{history_text}\n\nCurrent Query: {text}\n\nGenerate Suggestions In: English"
                                
                                # Start suggestions agent in background
                                suggestions_task = asyncio.create_task(
                                    suggestions_agent.run(suggestions_prompt)
                                )
                                logger.info(f"[Turn {turn_id}] 💡 Started suggestions agent in parallel")
                            except Exception as e:
                                logger.warning(f"[Turn {turn_id}] Failed to start suggestions agent: {e}")
                        else:
                            logger.debug(f"[Turn {turn_id}] Suggestions disabled via ENABLE_SUGGESTIONS env var")
                        
                        stream_context = agrinet_agent.run_stream(
                            user_prompt=user_prompt_with_context,  # Include recent context in prompt
                            message_history=history,
                            deps=context,
                            # NO instructions parameter - let system prompt handle everything
                        )

                        # Use async context manager for agent stream
                        stream_obj = None  # Save reference to stream for later
                        async with stream_context as stream:
                            stream_obj = stream  # Save reference
                            # Stream text chunks using stream_text(delta=True)
                            async for chunk in stream.stream_text(delta=True):
                                logger.debug(f"[Turn {turn_id}] Received chunk from LLM: '{chunk[:30] if chunk else 'None'}...'")
                                # Check for interruption - but NOT for amendments or noise
                                current_turn = await self.state.get_turn_id()
                                
                                if current_turn != turn_id:
                                    # Check if the newer turn should preempt this one
                                    # Don't preempt if newer turn is:
                                    # 1. An amendment (is_amendment=True)
                                    # 2. Noise/empty transcription (has_transcription=False)
                                    # 3. Still being processed (has_transcription not set yet)
                                    should_preempt = False
                                    for check_turn in range(turn_id + 1, current_turn + 1):
                                        if check_turn in self.turn_timings:
                                            turn_info = self.turn_timings[check_turn]
                                            is_amendment = turn_info.get("is_amendment", False)
                                            has_transcription = turn_info.get("has_transcription", None)
                                            
                                            # Preempt only if newer turn has real content and is not amendment
                                            if has_transcription is True and not is_amendment:
                                                should_preempt = True
                                                break
                                    
                                    if should_preempt:
                                        logger.info(f"LLM preempted (turn {turn_id} -> {current_turn})")
                                        break
                                    # else: continue processing - newer turns are noise/amendments/pending
                                
                                if self.state.should_stop:
                                    break

                                if chunk and isinstance(chunk, str):
                                    # Handle intermediate message (LLM outputs this at start if calling tools)
                                    if "[INTERMEDIATE:" in chunk:
                                        logger.info(f"[Turn {turn_id}] 🔵 DETECTED [INTERMEDIATE:] in chunk: '{chunk}'")
                                        # Extract intermediate message
                                        start_idx = chunk.find("[INTERMEDIATE:")
                                        end_idx = chunk.find("]", start_idx)
                                        if end_idx > 0:
                                            intermediate_msg = chunk[start_idx + 14:end_idx]  # Extract from [INTERMEDIATE:message]
                                            logger.info(f"🔵 [Voice] LLM provided intermediate message: '{intermediate_msg}'")
                                            
                                            # Send as WebSocket message
                                            await self.ws_manager.send_json({
                                                "type": "intermediate",
                                                "text": intermediate_msg,
                                                "turn_id": turn_id
                                            })
                                            logger.info(f"🔵 [Voice] Sent intermediate WebSocket message")
                                            
                                            # Synthesize and send intermediate audio
                                            try:
                                                intermediate_audio = await self.tts_provider._synthesize_chunk(intermediate_msg, self.state.lang)
                                                if intermediate_audio:
                                                    await self.tts_queue.put((intermediate_audio, turn_id))
                                                    logger.info(f"🔵 [Voice] Intermediate audio sent for turn {turn_id}")
                                            except Exception as e:
                                                logger.warning(f"Failed to synthesize intermediate audio: {e}")
                                            
                                            # Remove the marker from chunk and continue with rest
                                            chunk = chunk[:start_idx] + chunk[end_idx + 1:]
                                            logger.info(f"🔵 [Voice] Chunk after removing marker: '{chunk}'")
                                            if not chunk.strip():
                                                logger.info(f"🔵 [Voice] Chunk empty after removing marker, continuing to next chunk")
                                                continue  # Skip if chunk is now empty after removing marker
                                    
                                    # Handle status messages (show to user but don't send to TTS)
                                    if chunk.startswith("[STATUS:"):
                                        # Extract status message
                                        status_msg = chunk[8:-1]  # Extract status from [STATUS:message]
                                        logger.info(f"Status update: {status_msg}")
                                        await self.ws_manager.send_json({
                                            "type": "status",
                                            "message": status_msg,
                                            "turn_id": turn_id
                                        })
                                        continue  # Don't add to collected_text or TTS queue
                                    
                                    # Handle tool events (don't send to TTS, just notify frontend)
                                    elif chunk.startswith("[TOOL:"):
                                        # Tool call started - notify frontend for progress
                                        tool_name = chunk[6:-1]  # Extract tool name from [TOOL:name]
                                        logger.info(f"Tool call: {tool_name}")
                                        await self.ws_manager.send_json({
                                            "type": "tool_call",
                                            "tool": tool_name,
                                            "turn_id": turn_id
                                        })
                                        continue  # Don't add to collected_text or TTS queue
                                    
                                    elif chunk == "[TOOL_DONE]":
                                        # Tool completed - notify frontend
                                        await self.ws_manager.send_json({
                                            "type": "tool_done",
                                            "turn_id": turn_id
                                        })
                                        continue  # Don't add to collected_text or TTS queue
                                    
                                    # Regular text chunk - send to TTS and frontend
                                    collected_text += chunk
                                    chunk_count += 1

                                    try:
                                        await asyncio.wait_for(
                                            self.llm_queue.put((chunk, turn_id)),
                                            timeout=1.0
                                        )
                                        # Mark first response chunk so frontend knows to start new line
                                        msg = {
                                            "type": "llm_chunk",
                                            "text": chunk,
                                            "turn_id": turn_id
                                        }
                                        if first_response_chunk:
                                            msg["is_first"] = True
                                            first_response_chunk = False
                                        logger.info(f"[Turn {turn_id}] Sending chunk #{chunk_count}: '{chunk[:30]}...' ({len(chunk)} chars)")
                                        await self.ws_manager.send_json(msg)
                                        logger.info(f"[Turn {turn_id}] Chunk #{chunk_count} sent to frontend")
                                    except asyncio.TimeoutError:
                                        logger.warning("LLM queue full, dropping chunk")

                            # Send EOS marker - check if we completed or were preempted
                            current_turn = await self.state.get_turn_id()
                            is_newer_turn_amendment = (
                                current_turn in self.turn_timings and 
                                self.turn_timings[current_turn].get("is_amendment", False)
                            )
                            
                            # Complete if: same turn, OR newer turn is just an amendment
                            should_complete = (current_turn == turn_id) or is_newer_turn_amendment
                            
                            if should_complete and collected_text:
                                await self.llm_queue.put((None, turn_id))
                        
                        # AFTER exiting async with block, we can access stream.result
                        # Extract sources from tool calls
                        sources = set()
                        TOOL_SOURCE_MAP = {
                            'get_current_weather': 'OpenWeatherMap',
                            'get_weather_forecast': 'OpenWeatherMap',
                            
                            'list_livestock_in_marketplace': 'https://nmis.et/',
                            'get_livestock_price_in_marketplace': 'https://nmis.et/',
                            'get_livestock_price_quick': 'https://nmis.et/',
                            'compare_livestock_prices_nearby': 'https://nmis.et/',
                            
                            'list_crops_in_marketplace': 'https://nmis.et/',
                            'get_crop_price_in_marketplace': 'https://nmis.et/',
                            'get_crop_price_quick': 'https://nmis.et/',
                            'compare_crop_prices_nearby': 'https://nmis.et/',
                        }
                        
                        # Save history using agent's result (includes tool calls, etc.)
                        # This ensures proper history management and caching
                        if should_complete and collected_text:
                            logger.info(f"[Turn {turn_id}] 💾 Attempting to save history...")
                            try:

                                await self.state.add_to_history("assistant", collected_text)
                                logger.info(f"[Turn {turn_id}] ✅ Added assistant response to history: {collected_text[:80]}...")
                                
                                # Extract sources from result for tool calls
                                result = stream_obj
                                if result and hasattr(result, "new_messages"):
                                    new_messages = result.new_messages()
                                    logger.info(f"[Turn {turn_id}] Checking {len(new_messages) if new_messages else 0} messages for tool calls")
                                    
                                    if new_messages:
                                        # Extract sources from tool calls in new messages
                                        logger.info(f"🔍 Extracting sources from {len(new_messages)} new messages")
                                        for i, msg in enumerate(new_messages):
                                            logger.info(f"  Message {i}: type={type(msg).__name__}, has_parts={hasattr(msg, 'parts')}")
                                            if hasattr(msg, 'parts'):
                                                logger.info(f"    Parts count: {len(msg.parts)}")
                                                for j, part in enumerate(msg.parts):
                                                    kind = getattr(part, 'part_kind', 'unknown')
                                                    logger.info(f"    Part {j}: kind={kind}")
                                                    if kind == 'tool-call':
                                                        tool_name = getattr(part, 'tool_name', None)
                                                        logger.info(f"  ✅ Found tool call: {tool_name}")
                                                        if tool_name and tool_name in TOOL_SOURCE_MAP:
                                                            sources.add(TOOL_SOURCE_MAP[tool_name])
                                                            logger.info(f"  ✅ Mapped tool '{tool_name}' to source '{TOOL_SOURCE_MAP[tool_name]}'")
                                                        elif tool_name:
                                                            logger.warning(f"  ⚠️ Tool '{tool_name}' not in TOOL_SOURCE_MAP")
                                    else:
                                        logger.warning("⚠️ new_messages() returned empty list")
                                    
                            except Exception as e:
                                logger.error(f"Error saving history: {e}", exc_info=True)
                                # Fallback to simple history
                                await self.state.add_to_history("assistant", collected_text)
                                await self.state.add_to_history("assistant", collected_text)

                            # Send sources to frontend if any were found
                            # Small delay to ensure last llm_chunk is processed
                            await asyncio.sleep(0.1)
                            
                            if sources:
                                source_list = list(sources)
                                logger.info(f"📚 Sending sources for turn {turn_id}: {source_list}")
                                await self.ws_manager.send_json({
                                    "type": "sources",
                                    "sources": source_list,
                                    "turn_id": turn_id
                                })
                                logger.info(f"✅ Sources sent successfully for turn {turn_id}")
                            else:
                                logger.warning(f"⚠️ No sources found for turn {turn_id}")

                            # Get suggestions from parallel task if available
                            if suggestions_task:
                                try:
                                    # Wait for suggestions with timeout (don't block too long)
                                    suggestions_result = await asyncio.wait_for(
                                        suggestions_task,
                                        timeout=5.0  # Max 5 seconds for suggestions
                                    )
                                    if suggestions_result and hasattr(suggestions_result, 'output'):
                                        suggestions_list = suggestions_result.output
                                        if suggestions_list and len(suggestions_list) > 0:
                                            logger.info(f"💡 Sending {len(suggestions_list)} suggestions for turn {turn_id}")
                                            await self.ws_manager.send_json({
                                                "type": "suggestions",
                                                "suggestions": suggestions_list,
                                                "turn_id": turn_id
                                            })
                                            logger.info(f"✅ Suggestions sent successfully for turn {turn_id}")
                                        else:
                                            logger.warning(f"⚠️ Suggestions agent returned empty list for turn {turn_id}")
                                    else:
                                        logger.warning(f"⚠️ Suggestions agent returned no output for turn {turn_id}")
                                except asyncio.TimeoutError:
                                    logger.warning(f"⚠️ Suggestions agent timed out for turn {turn_id}")
                                except Exception as e:
                                    logger.warning(f"⚠️ Failed to get suggestions for turn {turn_id}: {e}")

                            # Track LLM end time and duration
                            llm_end_time = time.time()
                            llm_duration = llm_end_time - llm_start_time
                            if turn_id in self.turn_timings:
                                self.turn_timings[turn_id]["llm_end"] = llm_end_time
                            self.metrics["llm_times"].append((turn_id, llm_duration))
                            logger.info(f"LLM generation completed for turn {turn_id} (took {llm_duration:.3f}s)")

                            # Check for pending amendments (speech captured during processing)
                            amendment, original_query = await self.state.get_and_clear_amendment()
                            if amendment:
                                # Always combine the amendment with original query
                                # The LLM has conversation history for context
                                query_to_amend = original_query if original_query else text
                                amended_query = f"{query_to_amend} {amendment}"
                                
                                logger.info(f"Found amendment: '{amendment}'")
                                logger.info(f"Combined query: '{query_to_amend}' + '{amendment}' = '{amended_query}'")
                                
                                # Add the combined context to history
                                await self.state.add_to_history("user", f"[User added: {amendment}]")
                                
                                # Create new turn for combined query
                                new_turn_id = await self.state.increment_turn()
                                
                                await self.ws_manager.send_json({
                                    "type": "amendment_detected",
                                    "original_query": query_to_amend,
                                    "amendment": amendment,
                                    "amended_query": amended_query,
                                    "turn_id": new_turn_id
                                })
                                
                                # Queue the combined query
                                try:
                                    await asyncio.wait_for(
                                        self.text_queue.put((amended_query, new_turn_id)),
                                        timeout=1.0
                                    )
                                    logger.info(f"Queued combined query for turn {new_turn_id}: '{amended_query}'")
                                except asyncio.TimeoutError:
                                    logger.error("Failed to queue combined query")
                                    await self.state.set_processing(False)
                            else:
                                # No amendment - clear processing state
                                await self.state.set_processing(False)
                                logger.debug(f"LLM done, no amendment - cleared processing state")

                    except asyncio.TimeoutError:
                        logger.error(f"LLM timeout for turn {turn_id}")
                        self.metrics["errors"] += 1

                        # Send error message to user
                        error_msg = "I'm taking too long to respond. Can you try something simpler."

                        try:
                            await asyncio.wait_for(
                                self.llm_queue.put((error_msg, turn_id)),
                                timeout=1.0
                            )
                            await asyncio.wait_for(
                                self.llm_queue.put((None, turn_id)),  # EOS
                                timeout=1.0
                            )
                            await self.ws_manager.send_json({
                                "type": "llm_chunk",
                                "message": error_msg,
                                "turn_id": turn_id
                            })
                        except asyncio.TimeoutError:
                            logger.error("Failed to send LLM timeout message to user")
                    except Exception as e:
                        logger.error(f"LLM Stream Error: {e}", exc_info=True)
                        self.metrics["errors"] += 1

                        # Send error message to user
                        error_msg = "I encountered an error while thinking. Could you rephrase your question?"

                        try:
                            await asyncio.wait_for(
                                self.llm_queue.put((error_msg, turn_id)),
                                timeout=1.0
                            )
                            await asyncio.wait_for(
                                self.llm_queue.put((None, turn_id)),  # EOS
                                timeout=1.0
                            )
                            await self.ws_manager.send_json({
                                "type": "llm_chunk",
                                "message": error_msg,
                                "turn_id": turn_id
                            })
                        except asyncio.TimeoutError:
                            logger.error("Failed to send LLM error message to user")
                    finally:
                        # Proper cleanup
                        if stream is not None:
                            try:
                                if hasattr(stream, 'aclose'):
                                    await stream.aclose()
                            except Exception as e:
                                logger.debug(f"Error closing LLM stream: {e}")
                        
                        # Clear processing state on any error/exception path
                        # (Normal completion clears it after checking amendments)
                        is_still_processing = await self.state.get_processing()
                        if is_still_processing:
                            await self.state.set_processing(False)
                            logger.debug("Cleared processing state in finally block")

                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"LLM Worker Error: {e}", exc_info=True)
                    self.metrics["errors"] += 1

                    # Send error message to user
                    error_msg = "Something went wrong. Please try asking again."

                    try:
                        current_turn = await self.state.get_turn_id()
                        await asyncio.wait_for(
                            self.llm_queue.put((error_msg, current_turn)),
                            timeout=1.0
                        )
                        await asyncio.wait_for(
                            self.llm_queue.put((None, current_turn)),  # EOS
                            timeout=1.0
                        )
                        await self.ws_manager.send_json({
                            "type": "llm_chunk",
                            "message": error_msg,
                            "turn_id": current_turn
                        })
                    except Exception as e2:
                        logger.error(f"Failed to send LLM worker error message: {e2}")

        except asyncio.CancelledError:
            logger.debug("LLM worker cancelled")
            raise

    async def _tts_worker(self):
        """TTS worker with proper resource management"""
        try:
            while not self.state.should_stop:
                stream = None  # Initialize in outer scope

                try:
                    # Get with timeout
                    item = await asyncio.wait_for(
                        self.llm_queue.get(),
                        timeout=self.config.QUEUE_GET_TIMEOUT
                    )
                    chunk, turn_id = item

                    # Check if turn still valid - but don't drop for noise/amendments
                    current_turn = await self.state.get_turn_id()
                    if turn_id != current_turn:
                        # Check if newer turns are just noise/amendments
                        should_drop = False
                        for check_turn in range(turn_id + 1, current_turn + 1):
                            if check_turn in self.turn_timings:
                                turn_info = self.turn_timings[check_turn]
                                is_amendment = turn_info.get("is_amendment", False)
                                has_transcription = turn_info.get("has_transcription", None)
                                
                                # Drop only if newer turn has real content and is not amendment
                                if has_transcription is True and not is_amendment:
                                    should_drop = True
                                    break
                        
                        if should_drop:
                            logger.debug(f"Dropping stale TTS turn {turn_id} (current: {current_turn})")
                            continue
                        # else: continue processing - newer turns are noise/amendments

                    if chunk is None:
                        continue  # EOS marker

                    # Create text iterator
                    async def text_iterator():
                        """Iterator that yields LLM chunks for this turn"""
                        yield chunk  # First chunk

                        while True:
                            try:
                                next_item = await asyncio.wait_for(
                                    self.llm_queue.get(),
                                    timeout=2.0
                                )
                                n_chunk, n_tid = next_item

                                # If different turn, put it back
                                if n_tid != turn_id:
                                    # Try to put back, but don't block
                                    try:
                                        await asyncio.wait_for(
                                            self.llm_queue.put((n_chunk, n_tid)),
                                            timeout=0.5
                                        )
                                    except asyncio.TimeoutError:
                                        logger.warning("Failed to requeue chunk from new turn")
                                    break

                                if n_chunk is None:
                                    break  # EOS

                                yield n_chunk

                            except asyncio.TimeoutError:
                                break
                            except asyncio.CancelledError:
                                break

                    # Stream audio
                    # Track TTS start time
                    tts_start_time = time.time()
                    if turn_id in self.turn_timings:
                        self.turn_timings[turn_id]["tts_start"] = tts_start_time

                    try:
                        stream = self.tts_provider.stream_audio(
                            text_iterator(),
                            lang=self.state.lang
                        )

                        audio_chunks_sent = 0
                        async for audio_chunk in stream:
                            audio_chunks_sent += 1
                            current_turn = await self.state.get_turn_id()
                            if current_turn != turn_id:
                                logger.debug(f"TTS interrupted (turn {turn_id} -> {current_turn})")
                                break

                            try:
                                await asyncio.wait_for(
                                    self.tts_queue.put((audio_chunk, turn_id)),
                                    timeout=1.0
                                )
                            except asyncio.TimeoutError:
                                logger.warning("TTS queue full, dropping audio")

                    except Exception as e:
                        logger.error(f"TTS streaming error: {e}", exc_info=True)
                        self.metrics["errors"] += 1

                        # Send error notification to client
                        try:
                            await self.ws_manager.send_json({
                                "type": "llm_chunk",
                                "code": "tts_error",
                                "message": "Voice synthesis failed. Please check your audio settings.",
                                "severity": "error",
                                "turn_id": turn_id
                            })
                        except Exception as send_error:
                            logger.error(f"Failed to send TTS error notification: {send_error}")

                    finally:
                        # Track TTS end time and duration
                        tts_end_time = time.time()
                        tts_duration = tts_end_time - tts_start_time
                        if turn_id in self.turn_timings:
                            self.turn_timings[turn_id]["tts_end"] = tts_end_time
                        self.metrics["tts_times"].append((turn_id, tts_duration))
                        logger.info(f"TTS synthesis completed for turn {turn_id} (took {tts_duration:.3f}s, {audio_chunks_sent} chunks)")
                        if stream is not None:
                            try:
                                if hasattr(stream, 'aclose'):
                                    await stream.aclose()
                            except Exception as e:
                                logger.debug(f"Error closing TTS stream: {e}")

                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"TTS Worker Error: {e}", exc_info=True)
                    self.metrics["errors"] += 1

                    # Send error notification to client
                    try:
                        current_turn = await self.state.get_turn_id()
                        await self.ws_manager.send_json({
                            "type": "llm_chunk",
                            "code": "tts_worker_error",
                            "message": "Audio system error occurred.",
                            "severity": "error",
                            "turn_id": current_turn
                        })
                    except Exception as send_error:
                        logger.error(f"Failed to send TTS worker error notification: {send_error}")

        except asyncio.CancelledError:
            logger.debug("TTS worker cancelled")
            raise

    async def _send_worker(self):
        """Send worker with graceful handling"""
        try:
            while not self.state.should_stop:
                try:
                    # Get with timeout
                    item = await asyncio.wait_for(
                        self.tts_queue.get(),
                        timeout=self.config.QUEUE_GET_TIMEOUT
                    )
                    audio_chunk, turn_id = item
                    logger.debug(f"Send worker got audio chunk ({len(audio_chunk)} bytes) for turn {turn_id}")

                    # Check if should send
                    current_turn = await self.state.get_turn_id()
                    is_speaking = await self.state.get_speaking()

                    if turn_id != current_turn or is_speaking:
                        # Don't send if interrupted
                        logger.debug(f"Dropping audio: turn_id={turn_id}, current={current_turn}, is_speaking={is_speaking}")
                        # Clear states when turn changes
                        await self.state.set_playing_audio(False)
                        await self.state.set_processing(False)
                        continue

                    try:

                        await self.state.set_playing_audio(True)
                        
                        await self.ws_manager.send_bytes(audio_chunk)
                        logger.debug(f"Sent audio chunk ({len(audio_chunk)} bytes) for turn {turn_id}")
                        # Track audio sent
                        self.metrics["total_audio_sent"] += len(audio_chunk)

                        # Track last send time for this turn (will be overwritten with each chunk)
                        if turn_id in self.turn_timings:
                            self.turn_timings[turn_id]["last_audio_sent"] = time.time()

                    except Exception as e:
                        logger.error(f"Failed to send audio: {e}")
                        await self.state.set_playing_audio(False)
                        await self.state.set_processing(False)
                        break

                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Send worker error: {e}", exc_info=True)
                    await self.state.set_playing_audio(False)
                    await self.state.set_processing(False)
                    break

        except asyncio.CancelledError:
            logger.debug("Send worker cancelled")
            raise
