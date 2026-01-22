"""
Local Hate Speech Moderation Classifier

Uses local transformer models for hate speech detection:
- Amharic: uhhlt/amharic-hate-speech (labels: offensive, hate, normal)
- English: facebook/roberta-hate-speech-dynabench-r4-target (labels: nothate, hate)
"""

import re
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ModerationResult:
    """Standardized moderation result."""
    is_safe: bool
    label: str
    score: float
    reason: str


class ModerationClassifier:
    """
    Unified moderation classifier for Amharic and English.
    Lazy-loads models on first use to save memory.
    """
    
    AMHARIC_MODEL = "uhhlt/amharic-hate-speech"
    ENGLISH_MODEL = "facebook/roberta-hate-speech-dynabench-r4-target"
    
    def __init__(self):
        self._amharic_classifier = None
        self._english_classifier = None
        self._models_loaded = {"amharic": False, "english": False}
    
    def _is_amharic(self, text: str) -> bool:
        """Check if text contains Ethiopic (Amharic) characters."""
        # Ethiopic Unicode range: U+1200 to U+137F
        ethiopic_pattern = re.compile(r'[\u1200-\u137F]')
        return bool(ethiopic_pattern.search(text))
    
    def _load_amharic_model(self):
        """Lazy load Amharic classifier."""
        if self._amharic_classifier is None:
            logger.info(f"Loading Amharic model: {self.AMHARIC_MODEL}...")
            try:
                from transformers import pipeline, AutoModelForSequenceClassification, AutoTokenizer
                tokenizer = AutoTokenizer.from_pretrained(self.AMHARIC_MODEL)
                model = AutoModelForSequenceClassification.from_pretrained(self.AMHARIC_MODEL)
                self._amharic_classifier = pipeline("text-classification", model=model, tokenizer=tokenizer)
                self._models_loaded["amharic"] = True
                logger.info("Amharic model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load Amharic model: {e}")
                self._amharic_classifier = None
    
    def _load_english_model(self):
        """Lazy load English classifier."""
        if self._english_classifier is None:
            logger.info(f"Loading English model: {self.ENGLISH_MODEL}...")
            try:
                from transformers import pipeline, AutoModelForSequenceClassification, AutoTokenizer
                tokenizer = AutoTokenizer.from_pretrained(self.ENGLISH_MODEL)
                model = AutoModelForSequenceClassification.from_pretrained(self.ENGLISH_MODEL)
                self._english_classifier = pipeline("text-classification", model=model, tokenizer=tokenizer)
                self._models_loaded["english"] = True
                logger.info("English model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load English model: {e}")
                self._english_classifier = None
    
    def classify(self, text: str, lang: Optional[str] = None) -> ModerationResult:
        """
        Classify text for hate speech.
        
        Args:
            text: Text to classify
            lang: Optional language hint ('am' for Amharic, 'en' for English)
                  If not provided, will auto-detect based on script
        
        Returns:
            ModerationResult with is_safe, label, score, reason
        """
        # Determine language
        if lang == "am" or (lang is None and self._is_amharic(text)):
            return self._classify_amharic(text)
        else:
            return self._classify_english(text)
    
    def _classify_amharic(self, text: str) -> ModerationResult:
        """Classify Amharic text."""
        self._load_amharic_model()
        
        if self._amharic_classifier is None:
            return ModerationResult(
                is_safe=True,
                label="ERROR",
                score=0.0,
                reason="Amharic model not loaded - allowing through"
            )
        
        try:
            result = self._amharic_classifier(text)[0]
            label = result['label'].lower()
            score = result['score']
            
            # Labels: normal, offensive, hate
            is_safe = (label == "normal")
            
            return ModerationResult(
                is_safe=is_safe,
                label=label.capitalize(),
                score=score,
                reason=f"Amharic classifier: {label} ({score:.2%} confidence)"
            )
        except Exception as e:
            logger.error(f"Amharic classification error: {e}")
            return ModerationResult(
                is_safe=True,
                label="ERROR",
                score=0.0,
                reason=f"Classification error: {e}"
            )
    
    def _classify_english(self, text: str) -> ModerationResult:
        """Classify English text."""
        self._load_english_model()
        
        if self._english_classifier is None:
            return ModerationResult(
                is_safe=True,
                label="ERROR",
                score=0.0,
                reason="English model not loaded - allowing through"
            )
        
        try:
            result = self._english_classifier(text)[0]
            label = result['label'].lower()
            score = result['score']
            
            # Labels: nothate, hate
            is_safe = (label == "nothate")
            
            # Map to readable labels
            readable_label = "Normal" if label == "nothate" else "Hate"
            
            return ModerationResult(
                is_safe=is_safe,
                label=readable_label,
                score=score,
                reason=f"English classifier: {readable_label} ({score:.2%} confidence)"
            )
        except Exception as e:
            logger.error(f"English classification error: {e}")
            return ModerationResult(
                is_safe=True,
                label="ERROR",
                score=0.0,
                reason=f"Classification error: {e}"
            )


# Global singleton instance
moderation_classifier = ModerationClassifier()
