"""
Marqo client implementation for vector search.
"""
import os
import re
import marqo
from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field
from helpers.utils import get_logger
from helpers.translation import add_marathi_terms


logger = get_logger(__name__)

DocumentType = Literal['video', 'document']

class SearchHit(BaseModel):
    """Individual search hit from elasticsearch"""
    name: str
    text: str
    doc_id: str
    type: str
    source: str
    score: float = Field(alias="_score")
    id: str = Field(alias="_id")

    @property
    def processed_text(self) -> str:
        """Returns the text with cleaned up whitespace and newlines"""
        # Replace multiple newlines with a single line
        cleaned = re.sub(r'\n{2,}', '\n\n', self.text)
        cleaned = re.sub(r'\t+', '\t', cleaned)
        return cleaned

    def __str__(self) -> str:
        if self.type == 'document':
            return f"**{self.name}**\n" + "```\n" + self.processed_text +  "\n```\n" 
        else:
            return f"**[{self.name}]({self.source})**\n" + "```\n" + self.processed_text + "\n```\n"


def search_documents(
    query: str, 
    top_k: int = 10, 
    type: Optional[str] = None
) -> str:
    """
    Semantic search for videos and documents. Use this tool to search for relevant videos and documents.
    
    Args:
        query: The search query in *English* (required)
        top_k: Maximum number of results to return (default: 10)
        type: Filter by document type: [`video`, `document`]. Default is None, which means all types are considered.
        
    Returns:
        search_results: Formatted string with search results
    """
    # Initialize Marqo client
    endpoint_url = os.getenv('MARQO_ENDPOINT_URL')
    if not endpoint_url:
        raise ValueError("Marqo endpoint URL is required")
    
    index_name = os.getenv('MARQO_INDEX_NAME', 'oan-index')
    if not index_name:
        raise ValueError("Marqo index name is required")
    
    client = marqo.Client(url=endpoint_url)
    logger.info(f"Searching for '{query}' in index '{index_name}'")
    
    # Default to all types if none specified
    if type is None:
        filter_string = f"type:video OR type:document"
    else:
        filter_string = f"type:{type}"

    filter_string = f"({filter_string})"
        
    # Perform search
    search_params = {
        "q": query,
        "limit": top_k,
        "filter_string": filter_string,
        "search_method": "hybrid",
        "hybrid_parameters": {
            "retrievalMethod": "disjunction",
            "rankingMethod": "rrf",
            "alpha": 0.5,
            "rrfK": 60,
        },        
    }
    
    results = client.index(index_name).search(**search_params)['hits']
    
    if len(results) == 0:
        return f"No results found for `{query}`"
    else:            
        search_hits = [SearchHit(**hit) for hit in results]
        
        # Convert back to dict format for compatibility
        document_string = '\n\n----\n\n'.join([str(document) for document in search_hits])
        return "> Search Results for `" + query + "`\n\n" + document_string