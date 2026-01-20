"""
Production-Ready TTS Provider
"""

import time
from typing import AsyncGenerator, Optional
from app.config import settings
from helpers.utils import get_logger
import asyncio
import re
import azure.cognitiveservices.speech as speechsdk

logger = get_logger(__name__)


def convert_numbers_to_words(text: str, lang: str) -> str:
    """
    Convert numbers in text to words for better TTS pronunciation.
    
    Args:
        text: Text containing numbers
        lang: Language code ('en' or 'am')
    
    Returns:
        Text with numbers converted to words
    """
    if lang == 'en':
        # English number conversion (basic implementation)
        def num_to_words_en(n):
            if n == 0:
                return 'zero'
            
            ones = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine']
            teens = ['ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 
                    'sixteen', 'seventeen', 'eighteen', 'nineteen']
            tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
            
            if n < 10:
                return ones[n]
            elif n < 20:
                return teens[n - 10]
            elif n < 100:
                return tens[n // 10] + ('' if n % 10 == 0 else ' ' + ones[n % 10])
            elif n < 1000:
                return ones[n // 100] + ' hundred' + ('' if n % 100 == 0 else ' ' + num_to_words_en(n % 100))
            elif n < 1000000:
                return num_to_words_en(n // 1000) + ' thousand' + ('' if n % 1000 == 0 else ' ' + num_to_words_en(n % 1000))
            else:
                return str(n)  # Fallback for very large numbers
        
        # Replace numbers with words
        def replace_num(match):
            num_str = match.group(0).replace(',', '')
            try:
                num = int(num_str)
                return num_to_words_en(num)
            except:
                return match.group(0)
        
        text = re.sub(r'\b\d{1,3}(?:,\d{3})*\b', replace_num, text)
        
    elif lang == 'am':
        # Amharic number conversion
        def num_to_words_am(n):
            if n == 0:
                return 'ዜሮ'
            
            ones = ['', 'አንድ', 'ሁለት', 'ሦስት', 'አራት', 'አምስት', 'ስድስት', 'ሰባት', 'ስምንት', 'ዘጠኝ']
            tens = ['', 'አስር', 'ሃያ', 'ሰላሳ', 'አርባ', 'ሃምሳ', 'ስልሳ', 'ሰባ', 'ሰማንያ', 'ዘጠና']
            
            if n < 10:
                return ones[n]
            elif n == 10:
                return 'አስር'
            elif n < 20:
                return 'አስራ ' + ones[n - 10]
            elif n < 100:
                return tens[n // 10] + ('' if n % 10 == 0 else ' ' + ones[n % 10])
            elif n < 1000:
                return ones[n // 100] + ' መቶ' + ('' if n % 100 == 0 else ' ' + num_to_words_am(n % 100))
            elif n < 1000000:
                return num_to_words_am(n // 1000) + ' ሺህ' + ('' if n % 1000 == 0 else ' ' + num_to_words_am(n % 1000))
            else:
                return str(n)  # Fallback
        
        # Replace numbers with Amharic words
        def replace_num(match):
            num_str = match.group(0).replace(',', '')
            try:
                num = int(num_str)
                return num_to_words_am(num)
            except:
                return match.group(0)
        
        text = re.sub(r'\b\d{1,3}(?:,\d{3})*\b', replace_num, text)
    
    return text


class TTSProvider:
    """Abstract base class for TTS providers"""

    async def stream_audio(
        self,
        text_stream: AsyncGenerator[str, None],
        lang: str = "en"
    ) -> AsyncGenerator[bytes, None]:
        raise NotImplementedError


class AzureTTSProvider(TTSProvider):
    """
    Azure TTS Provider with proper resource management
    """

    def __init__(self):
        self.speech_key = settings.azure_foundary_api_key
        self.service_region = settings.azure_foundary_region

        # Voice configuration
        self.voices = {
            "am": "am-ET-MekdesNeural",
            "en": "en-US-CoraMultilingualNeural"
        }

        logger.info(f"Initializing Azure TTS in region: {self.service_region}")

        try:
            # Create speech config (reused)
            self.speech_config = speechsdk.SpeechConfig(
                subscription=self.speech_key,
                region=self.service_region
            )

            # Set output format to raw PCM for streaming
            self.speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
            )

            # Performance optimizations
            self.speech_config.set_property(
                speechsdk.properties.PropertyId.SpeechServiceResponse_SynthesisConnectionLatencyMs,
                "10000"  # Increased from 5000 to 10000ms for better reliability
            )

            self._synthesizers = {}
            self._synthesizer_locks = {}

            logger.info("✅ Azure TTS initialized successfully")

        except Exception as e:
            logger.error(f"❌ Failed to initialize Azure TTS: {e}")
            raise

    def _get_or_create_synthesizer(self, lang: str) -> speechsdk.SpeechSynthesizer:
        """
        Get or create synthesizer for language
        Reuses synthesizers instead of creating new ones

        Args:
            lang: Language code

        Returns:
            SpeechSynthesizer instance
        """
        if lang not in self._synthesizers:
            # Select voice based on language
            voice_name = self.voices.get(lang, self.voices["en"])
            self.speech_config.speech_synthesis_voice_name = voice_name

            # Create new synthesizer
            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=self.speech_config,
                audio_config=None
            )

            self._synthesizers[lang] = synthesizer
            self._synthesizer_locks[lang] = asyncio.Lock()

            logger.info(f"Created synthesizer for language: {lang} (voice: {voice_name})")

        return self._synthesizers[lang]

    async def stream_audio(
        self,
        text_stream: AsyncGenerator[str, None],
        lang: str = "en"
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream audio bytes from text stream

        Args:
            text_stream: Async generator of text chunks
            lang: Language code

        Yields:
            bytes: Audio data chunks
        """
        buffer = ""
        # Sentence delimiters for natural speech breaks
        # Include comma for earlier synthesis on short responses
        delimiters = {".", "!", "?", ";", "\n", ","}
        
        # Track timing for debugging
        first_chunk_time = None
        first_audio_time = None
        chunk_count = 0

        try:
            async for text_chunk in text_stream:
                if not text_chunk:
                    continue
                
                chunk_count += 1
                if first_chunk_time is None:
                    first_chunk_time = time.time()
                    logger.debug(f"TTS received first text chunk: '{text_chunk[:30]}...'")

                buffer += text_chunk

                # Check if we have a complete sentence-like chunk
                should_synthesize = False
                to_synthesize = ""

                # Look for sentence boundaries
                if any(char in delimiters for char in text_chunk):
                    # Find the last delimiter to split safely
                    split_idx = -1
                    for i in range(len(buffer) - 1, -1, -1):
                        if buffer[i] in delimiters:
                            split_idx = i
                            break

                    if split_idx != -1:
                        to_synthesize = buffer[:split_idx + 1].strip()
                        buffer = buffer[split_idx + 1:].strip()
                        should_synthesize = True

                # Force synthesis if buffer reaches threshold (reduced from 150 for faster response)
                elif len(buffer) > 80:
                    to_synthesize = buffer.strip()
                    buffer = ""
                    should_synthesize = True
                
                # OPTIMIZATION: If this is the first chunk and it's substantial (>30 chars),
                # synthesize immediately to start audio playback faster
                elif chunk_count == 1 and len(buffer) > 30:
                    to_synthesize = buffer.strip()
                    buffer = ""
                    should_synthesize = True
                    logger.info(f"TTS early synthesis on first chunk ({len(to_synthesize)} chars)")

                if should_synthesize and to_synthesize:
                    if first_audio_time is None:
                        first_audio_time = time.time()
                        if first_chunk_time:
                            logger.info(f"TTS starting synthesis {first_audio_time - first_chunk_time:.3f}s after first text chunk")
                    audio_bytes = await self._synthesize_chunk(to_synthesize, lang)
                    if audio_bytes:
                        yield audio_bytes

            # Process remaining buffer
            if buffer.strip():
                audio_bytes = await self._synthesize_chunk(buffer.strip(), lang)
                if audio_bytes:
                    yield audio_bytes

        except asyncio.CancelledError:
            logger.debug("TTS stream cancelled")
            raise
        except Exception as e:
            logger.error(f"TTS streaming error: {e}", exc_info=True)
            raise

    async def _synthesize_chunk(self, text: str, lang: str) -> Optional[bytes]:
        """
        Synthesize a single text chunk to audio bytes

        Args:
            text: Text to synthesize
            lang: Language code

        Returns:
            Optional[bytes]: Audio data or None on error
        """
        if not text or not text.strip():
            return None

        try:
            # Convert numbers to words for better TTS pronunciation
            text_for_tts = convert_numbers_to_words(text, lang)
            if text_for_tts != text:
                logger.debug(f"Converted numbers: '{text[:50]}...' -> '{text_for_tts[:50]}...'")
            
            synthesizer = self._get_or_create_synthesizer(lang)
            lock = self._synthesizer_locks[lang]

            # Use lock to prevent concurrent synthesis with same synthesizer
            async with lock:
                # Run synthesis in executor to avoid blocking
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: synthesizer.speak_text_async(text_for_tts).get()
                )

            # Check result
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                logger.debug(f"Synthesized: {text[:50]}...")
                # Return the audio data bytes
                return bytes(result.audio_data)

            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                logger.error(f"Speech synthesis canceled: {cancellation_details.reason}")

                if cancellation_details.reason == speechsdk.CancellationReason.Error:
                    error_msg = cancellation_details.error_details
                    logger.error(f"Error details: {error_msg}")

                    # If codec or connection error, recreate synthesizer
                    if any(keyword in error_msg.lower() for keyword in ["codec", "authentication", "connection", "timeout"]):
                        logger.warning(f"Recreating synthesizer for {lang} due to error: {error_msg}")
                        if lang in self._synthesizers:
                            try:
                                del self._synthesizers[lang]
                                del self._synthesizer_locks[lang]
                            except:
                                pass
                        # Retry once with new synthesizer
                        logger.info(f"Retrying synthesis with new synthesizer...")
                        synthesizer = self._get_or_create_synthesizer(lang)
                        lock = self._synthesizer_locks[lang]
                        async with lock:
                            loop = asyncio.get_event_loop()
                            result = await loop.run_in_executor(
                                None,
                                lambda: synthesizer.speak_text_async(text).get()
                            )
                        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                            logger.info("✅ Retry successful")
                            return bytes(result.audio_data)
                        else:
                            logger.error(f"❌ Retry failed: {result.reason}")

                return None

            else:
                logger.warning(f"Unexpected synthesis result: {result.reason}")
                return None

        except Exception as e:
            logger.error(f"Azure TTS Synthesis error: {e}", exc_info=True)
            return None

    def cleanup(self):
        """Cleanup all synthesizers"""
        for lang, synthesizer in self._synthesizers.items():
            try:
                del synthesizer
                logger.debug(f"Cleaned up synthesizer for {lang}")
            except Exception as e:
                logger.debug(f"Error cleaning up synthesizer for {lang}: {e}")

        self._synthesizers.clear()
        self._synthesizer_locks.clear()


# Singleton
_tts_provider: Optional[TTSProvider] = None


def get_tts_provider() -> TTSProvider:
    """Get TTS provider based on configuration"""
    global _tts_provider
    if _tts_provider is None:
        _tts_provider = AzureTTSProvider()
        logger.info("TTS Provider initialized")

    return _tts_provider


def cleanup_tts_provider():
    """Cleanup TTS provider resources"""
    global _tts_provider
    if _tts_provider is not None and hasattr(_tts_provider, 'cleanup'):
        _tts_provider.cleanup()
        logger.info("TTS Provider cleaned up")
