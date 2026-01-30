"""
Local Hate Speech Moderation Classifier

Uses local transformer models for hate speech detection:
- Amharic: uhhlt/amharic-hate-speech (labels: offensive, hate, normal)
- English: facebook/roberta-hate-speech-dynabench-r4-target (labels: nothate, hate)

Includes whitelist for agricultural terms to prevent false positives.
"""

import re
import logging
from typing import Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ModerationResult:
    """Standardized moderation result."""
    is_safe: bool
    label: str
    score: float
    reason: str


# ============================================================================
# AGRICULTURAL WHITELIST - Terms that should always pass moderation
# ============================================================================
AGRICULTURAL_WHITELIST = [
    # Livestock
    "ox", "cow", "calf", "bull", "heifer",
    "male young goat", "male adult goat", "male old goat",
    "female young goat", "female adult goat", "female old goat",
    "male young sheep", "male adult sheep", "male old sheep",
    "female young sheep", "female adult sheep", "female old sheep",
    "male young camel", "male adult camel", "male old camel",
    "female young camel", "female adult camel", "female old camel",
    "male immature camel", "female immature camel",
    "rooster", "chicken", "chickens", "pullet", "laying eggs", "egg", "eggs",
    "goat", "sheep", "camel", "cattle", "poultry",
    
    # Crops - Teff
    "white teff", "red teff", "mixed teff", "teff",
    
    # Crops - Grains
    "white wheat", "wheat", "white maize", "maize", "corn",
    "sorghum", "local rice", "rice", "malt barley", "barley",
    
    # Crops - Vegetables
    "onion", "tomato", "potato", "garlic", "red pepper", "pepper",
    
    # Crops - Fruits
    "avocado", "mango", "raw banana", "ripe banana", "banana", "pineapple",
    
    # Crops - Legumes & Seeds
    "red kidney bean", "white pea bean", "soybean", "green mung", "mung bean",
    "mixed bean", "bean", "beans",
    "white sesame", "red sesame", "mixed sesame", "sesame",
    
    # Units
    "quintal", "kg", "kilogram",
    
    # Amharic agricultural terms
    "ጤፍ", "ነጭ ጤፍ", "ቀይ ጤፍ", "ድርብ ጤፍ",  # Teff
    "ስንዴ", "ነጭ ስንዴ",  # Wheat
    "በቆሎ", "ነጭ በቆሎ",  # Maize
    "ሽንኩርት", "ቲማቲም", "ድንች", "ነጭ ሽንኩርት", "በርበሬ",  # Vegetables
    "አቮካዶ", "ማንጎ", "ሙዝ", "አናናስ",  # Fruits
    "ማሽላ", "ሩዝ", "ገብስ",  # Grains
    "ባቄላ", "ቀይ ባቄላ", "ነጭ ባቄላ", "አኩሪ አተር", "ማሽ",  # Legumes
    "ሰሊጥ", "ነጭ ሰሊጥ", "ቀይ ሰሊጥ", "ድርብ ሰሊጥ",  # Sesame
    "በሬ", "ላም", "ጥጃ", "ኮርማ", "ጊደር",  # Cattle
    "ፍየል", "በግ", "ግመል",  # Livestock
    "ዶሮ", "አውራ ዶሮ", "እንቁላል",  # Poultry
    "ኩንታል", "ኪሎ",  # Units
    "ዋጋ", "ገበያ", "መግዛት", "መሸጥ",  # Market terms
]


# ============================================================================
# PROMPT INJECTION DETECTION
# ============================================================================
INJECTION_PATTERNS = [
    # Direct instruction override
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+(all\s+)?(previous|above|prior)",
    r"forget\s+(everything|all|what)\s+(you|i)\s+(said|told|wrote)",
    
    # Role manipulation
    r"you\s+are\s+now\s+(?:a|an|the)\s+\w+",
    r"pretend\s+(to\s+be|you\s+are)",
    r"act\s+as\s+(if|though|a|an)",
    r"roleplay\s+as",
    r"switch\s+(to|into)\s+\w+\s+mode",
    
    # System prompt extraction
    r"(show|tell|reveal|display|print|output)\s+(me\s+)?(your|the)\s+(system|initial|original)\s+(prompt|instructions?|message)",
    r"what\s+(are|is)\s+your\s+(?:(system|initial|original)\s+)?(instructions?|rules?|prompt)",
    r"repeat\s+(your|the)\s+(system|initial)\s+(prompt|message)",
    
    # Jailbreak attempts
    r"dan\s+mode",
    r"developer\s+mode",
    r"jailbreak",
    r"bypass\s+(the\s+)?(restrictions?|filters?|rules?)",
    r"override\s+(the\s+)?(safety|content)\s+(filters?|rules?)",
    
    # Delimiter injection
    r"```system",
    r"\[system\]",
    r"<\|im_start\|>",
    r"<\|endoftext\|>",
    
    # Code injection
    r"eval\s*\(",
    r"exec\s*\(",
    r"import\s+os",
    r"subprocess",
    r"__import__",
]


class ModerationClassifier:
    """
    Unified moderation classifier for Amharic and English.
    Lazy-loads models on first use to save memory.
    Includes whitelist for agricultural terms.
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
    
    def _is_whitelisted(self, text: str) -> bool:
        """
        Check if text contains whitelisted agricultural terms.
        Returns True if text appears to be agricultural content.
        """
        text_lower = text.lower()
        
        # Count how many whitelist terms appear
        matches = sum(1 for term in AGRICULTURAL_WHITELIST if term.lower() in text_lower)
        
        # If 2+ agricultural terms found, likely agricultural content
        if matches >= 2:
            return True
        
        # Also check for common agricultural question patterns
        agri_patterns = [
            r'\b(price|cost|buy|sell|market)\b.*\b(teff|wheat|maize|goat|sheep|cow|ox)\b',
            r'\b(teff|wheat|maize|goat|sheep|cow|ox)\b.*\b(price|cost|buy|sell|market)\b',
            r'\bዋጋ\b',  # Amharic "price"
            r'\bገበያ\b',  # Amharic "market"
            r'\bመግዛት\b',  # Amharic "buy"
            r'\bመሸጥ\b',  # Amharic "sell"
        ]
        
        for pattern in agri_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        return False

    def _detect_prompt_injection(self, text: str) -> Tuple[bool, float, List[str]]:
        """
        Detect prompt injection attempts.
        Returns: (is_injection, confidence, matched_patterns)
        """
        text_lower = text.lower()
        matched = []
        
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                matched.append(pattern)
        
        if matched:
            confidence = min(1.0, len(matched) * 0.3)  # More matches = higher confidence
            return True, confidence, matched
        
        return False, 0.0, []
    
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
        # 1. Check for prompt injection FIRST (Security Priority)
        # Even if it contains agricultural terms, we don't want to allow system prompts to be leaked
        is_injection, confidence, matches = self._detect_prompt_injection(text)
        if is_injection:
            logger.warning(f"Prompt injection detected: {matches}")
            return ModerationResult(
                is_safe=False,
                label="Injection",
                score=confidence,
                reason=f"Prompt injection detected ({len(matches)} patterns matched)"
            )

        # 2. Check whitelist - agricultural content should pass through
        if self._is_whitelisted(text):
            logger.debug(f"Whitelisted agricultural content: {text[:50]}...")
            return ModerationResult(
                is_safe=True,
                label="Whitelisted",
                score=1.0,
                reason="Agricultural content - whitelisted"
            )
        
        # 3. Determine language and classify
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

