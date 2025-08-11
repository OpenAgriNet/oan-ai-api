import json
from enum import Enum
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

# Load term pairs from JSON file
with open('assets/term_glossary.json', 'r', encoding='utf-8') as f:
    term_pairs = json.load(f)

class Language(str, Enum):
    ENGLISH = "en"
    MARATHI = "mr"
    TRANSLITERATION = "transliteration"

class TermPair(BaseModel):
    en: str = Field(description="E nglish term")
    mr: str = Field(description="Marathi term")
    transliteration: str = Field(description="Transliteration of Marathi term to English")

    def __str__(self):
        return f"{self.en} -> {self.mr} ({self.transliteration})"

# Convert raw dictionaries to TermPair objects
TERM_PAIRS = [TermPair(**pair) for pair in term_pairs]

def search_terms(
    text: str, 
    max_results: int = 5,
    similarity_threshold: float = 0.7,
    language: Language = None
) -> str:
    """
    Search for terms using fuzzy partial string matching across all fields.
    
    Args:
        text: The text to search for
        max_results: Maximum number of results to return
        similarity_threshold: Minimum similarity score (0-1) to consider a match
        language: Optional language to restrict search to (en/mr/transliteration)
        
    Returns:
        Formatted string with matching results and their scores
    """
    if not 0 <= similarity_threshold <= 1:
        raise ValueError("similarity_threshold must be between 0 and 1")
        
    matches = []
    text = text.lower()
    
    for term_pair in TERM_PAIRS:
        max_score = 0
        
        # Check English term if no language specified or language is English
        if language in [None, Language.ENGLISH]:
            en_score = fuzz.ratio(text, term_pair.en.lower()) / 100.0
            max_score = max(max_score, en_score)
            
        # Check Marathi term if no language specified or language is Marathi    
        if language in [None, Language.MARATHI]:
            mr_score = fuzz.ratio(text, term_pair.mr.lower()) / 100.0
            max_score = max(max_score, mr_score)
            
        # Check transliteration if no language specified or language is transliteration
        if language in [None, Language.TRANSLITERATION]:
            tr_score = fuzz.ratio(text, term_pair.transliteration.lower()) / 100.0
            max_score = max(max_score, tr_score)
            
        if max_score >= similarity_threshold:
            matches.append((term_pair, max_score))
    
    # Sort by score descending
    matches.sort(key=lambda x: x[1], reverse=True)    
    
    if len(matches) > 0:
        matches = matches[:max_results]
        return f"Matching Terms for `{text}`\n\n" + "\n".join([f"{match[0]} [{match[1]:.0%}]" for match in matches])
    else:
        return f"No matching terms found for `{text}`"