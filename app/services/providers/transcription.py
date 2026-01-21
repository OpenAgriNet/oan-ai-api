"""
Production-Ready Transcription Provider
"""

import asyncio
import base64
from typing import Optional
from abc import ABC, abstractmethod
from helpers.utils import get_logger
from app.config import settings
import azure.cognitiveservices.speech as speechsdk

logger = get_logger(__name__)


# Custom Exceptions
class TranscriptionException(Exception):
    """Base exception for transcription errors"""
    pass


class ModelLoadException(TranscriptionException):
    """Exception raised when model fails to load"""
    def __init__(self, model_name: str):
        self.model_name = model_name
        super().__init__(f"Failed to load model: {model_name}")


class InvalidAudioException(TranscriptionException):
    """Exception raised for invalid audio input"""
    pass


class TranscriptionProvider(ABC):
    """Abstract base class for transcription providers"""

    @abstractmethod
    async def transcribe(self, audio_content: str, lang: str = "en") -> str:
        """
        Transcribe audio content

        Args:
            audio_content: Base64 encoded audio string
            lang: Language code

        Returns:
            str: Transcribed text
        """
        pass

    @abstractmethod
    def validate_audio(self, audio_content: str) -> bool:
        """Validate audio input"""
        pass


class AzureTranscriptionProvider(TranscriptionProvider):
    """
    Azure Speech-to-Text transcription provider
    Production-ready with proper async handling and resource management
    """

    def __init__(self, subscription_key: str = None, region: str = None, session_id: str = None):
        """
        Initialize Azure transcription provider

        Args:
            subscription_key: Azure Speech service subscription key
            region: Azure region (e.g., 'eastus', 'westus')
            session_id: Optional session ID for tracking
        """
        self.subscription_key = subscription_key or settings.azure_foundary_api_key
        self.region = region or settings.azure_foundary_region

        if not self.subscription_key or not self.region:
            raise ValueError("Azure Speech subscription key and region are required")

        # Create speech config (reused across requests)
        self.speech_config = speechsdk.SpeechConfig(
            subscription=self.subscription_key,
            region=self.region
        )

        # Set timeout properties for longer audio clips
        # InitialSilenceTimeoutMs: How long to wait before first speech detected
        # For pre-recorded audio pushed to stream, this should be generous
        self.speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs,
            "15000"  # 15 seconds (was 5s - too short)
        )
        # EndSilenceTimeoutMs: How long silence after speech before ending
        self.speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
            "2000"  # 2 seconds (was 1s)
        )
        # Overall recognition timeout
        self.speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_RecoLanguage,
            "20000"  # 20 seconds overall timeout
        )

        logger.info(f"✅ Azure Transcription Provider initialized in region: {self.region}")

    def validate_audio(self, audio_content: str) -> bytes:
        """
        Validate and decode base64 audio input

        Args:
            audio_content: Base64 encoded audio string

        Returns:
            bytes: Decoded audio bytes

        Raises:
            InvalidAudioException: If audio is invalid
        """
        if not audio_content:
            raise InvalidAudioException("Audio content is empty")

        try:
            # Decode base64
            audio_bytes = base64.b64decode(audio_content)

            # Basic size check (50MB max)
            size_mb = len(audio_bytes) / (1024 * 1024)
            if size_mb > 50:
                raise InvalidAudioException(
                    f"Audio size ({size_mb:.2f}MB) exceeds maximum (50MB)"
                )

            # Basic validation - check if we have enough data
            if len(audio_bytes) < 100:
                raise InvalidAudioException("Audio data too short")

            return audio_bytes

        except base64.binascii.Error as e:
            raise InvalidAudioException(f"Invalid base64 audio data: {str(e)}")
        except Exception as e:
            raise InvalidAudioException(f"Audio validation failed: {str(e)}")

    async def transcribe(self, audio_content: str, lang: str = "en") -> str:
        """
        Transcribe audio using Azure Speech-to-Text
        
        Args:
            audio_content: Base64 encoded audio string (WAV format with header)
            lang: Language code (e.g., "en-US", "es-ES")

        Returns:
            str: Transcribed text

        Raises:
            TranscriptionException: If transcription fails
        """
        stream = None
        audio_config = None
        speech_recognizer = None

        try:
            # Validate and decode audio
            audio_bytes = self.validate_audio(audio_content)

            # Map language code to Azure format
            azure_lang = self._map_language_code(lang)
            self.speech_config.speech_recognition_language = azure_lang

            # Check if audio is WAV format (has RIFF header)
            if audio_bytes[:4] == b'RIFF':
                # Extract PCM data from WAV file
                # WAV format: RIFF header (12 bytes) + fmt chunk (24 bytes) + data chunk header (8 bytes) = 44 bytes
                logger.debug(f"Detected WAV format, audio size: {len(audio_bytes)} bytes")
                
                # Verify it's a valid WAV file
                if len(audio_bytes) < 44:
                    logger.error(f"WAV file too short: {len(audio_bytes)} bytes")
                    return ""
                
                # Skip WAV header (44 bytes) to get raw PCM data
                pcm_data = audio_bytes[44:]
                logger.debug(f"Extracted PCM data: {len(pcm_data)} bytes")
                
                # Check if we have enough PCM data (at least 0.1 seconds of audio)
                # 16kHz * 2 bytes/sample * 0.1s = 3200 bytes minimum
                if len(pcm_data) < 3200:
                    logger.warning(f"PCM data too short: {len(pcm_data)} bytes (< 0.1s of audio)")
                    return ""
                
                audio_bytes = pcm_data
            else:
                logger.debug(f"Raw PCM format detected, size: {len(audio_bytes)} bytes")

            # Define audio format: 16kHz, 16-bit, mono PCM (matching old backend)
            audio_format = speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000,
                bits_per_sample=16,
                channels=1
            )

            # Create audio stream with explicit format for better performance
            stream = speechsdk.audio.PushAudioInputStream(stream_format=audio_format)
            audio_config = speechsdk.audio.AudioConfig(stream=stream)

            # Create speech recognizer
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=self.speech_config,
                audio_config=audio_config
            )

            # Push audio data to stream
            stream.write(audio_bytes)
            stream.close()

            # Run blocking recognize_once in executor (non-blocking for async)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                speech_recognizer.recognize_once
            )

            # Handle results
            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                text = result.text.strip()
                logger.info(f"Transcription successful: {text[:50]}...")
                return text

            elif result.reason == speechsdk.ResultReason.NoMatch:
                logger.warning(f"No speech recognized: {result.no_match_details}")
                return ""  # Return empty instead of exception

            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation = result.cancellation_details
                logger.error(f"Transcription canceled: {cancellation.reason}")

                if cancellation.reason == speechsdk.CancellationReason.Error:
                    error_msg = cancellation.error_details
                    logger.error(f"Error details: {error_msg}")

                    # Don't raise for common errors, return empty
                    if "timeout" in error_msg.lower() or "no speech" in error_msg.lower():
                        return ""

                    raise TranscriptionException(f"Azure Speech error: {error_msg}")

                return ""  # Canceled but not error

            else:
                logger.error(f"Unexpected result reason: {result.reason}")
                return ""

        except InvalidAudioException:
            raise
        except TranscriptionException:
            raise
        except Exception as e:
            logger.error(f"Transcription error: {str(e)}", exc_info=True)
            raise TranscriptionException(str(e))

        finally:
            if speech_recognizer is not None:
                try:
                    # Azure SDK cleanup - no explicit close method but ensure GC
                    del speech_recognizer
                except Exception as e:
                    logger.debug(f"Error cleaning up recognizer: {e}")

            if audio_config is not None:
                try:
                    del audio_config
                except Exception as e:
                    logger.debug(f"Error cleaning up audio config: {e}")

            # Stream already closed above, but ensure cleanup
            if stream is not None:
                try:
                    del stream
                except Exception as e:
                    logger.debug(f"Error cleaning up stream: {e}")

    def _map_language_code(self, lang: str) -> str:
        """
        Map simple language codes to Azure locale format

        Args:
            lang: Simple language code (e.g., "en", "es")

        Returns:
            str: Azure locale code (e.g., "en-US", "es-ES")
        """
        # Comprehensive language mappings
        lang_map = {
            # English variants
            "en": "en-US",
            "en-gb": "en-GB",
            "en-au": "en-AU",
            "en-ca": "en-CA",
            "en-in": "en-IN",

            # African languages
            "am": "am-ET",  # Amharic
            "sw": "sw-KE",  # Swahili
            "zu": "zu-ZA",  # Zulu
            "af": "af-ZA",  # Afrikaans

            # Major languages
            "es": "es-ES",
            "fr": "fr-FR",
            "de": "de-DE",
            "it": "it-IT",
            "pt": "pt-BR",
            "pt-pt": "pt-PT",
            "zh": "zh-CN",
            "ja": "ja-JP",
            "ko": "ko-KR",
            "hi": "hi-IN",
            "ar": "ar-SA",
            "ru": "ru-RU",
            "tr": "tr-TR",
            "pl": "pl-PL",
            "nl": "nl-NL",
            "sv": "sv-SE",
            "da": "da-DK",
            "fi": "fi-FI",
            "no": "nb-NO",
            "cs": "cs-CZ",
            "hu": "hu-HU",
            "ro": "ro-RO",
            "th": "th-TH",
            "vi": "vi-VN",
            "id": "id-ID",
            "ms": "ms-MY",
        }

        # If already in correct format, return as-is
        if "-" in lang and len(lang) > 4:
            return lang

        # Map or default to en-US with warning
        mapped = lang_map.get(lang.lower())
        if mapped:
            return mapped
        else:
            logger.warning(
                f"Language '{lang}' not in mapping, defaulting to en-US. "
                f"Supported: {', '.join(sorted(lang_map.keys()))}"
            )
            return "en-US"


# Singleton instance - initialized once at startup
_transcription_provider: Optional[TranscriptionProvider] = None


def get_transcription_provider() -> TranscriptionProvider:
    """
    Get or create transcription provider singleton

    Returns:
        TranscriptionProvider: Transcription provider instance
    """
    global _transcription_provider
    if _transcription_provider is None:
        _transcription_provider = AzureTranscriptionProvider()
    return _transcription_provider
