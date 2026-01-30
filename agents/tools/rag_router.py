"""
RAG Router - Routes search requests to the configured RAG provider.

This module provides a clean abstraction layer that allows switching
between different RAG backends (Marqo, Cosdata) via configuration.
"""
import os
from typing import Optional
from helpers.utils import get_logger

logger = get_logger(__name__)

# Get the configured RAG provider
RAG_PROVIDER = os.getenv('RAG_PROVIDER', 'marqo').lower()

logger.info(f"RAG Provider configured: {RAG_PROVIDER}")


def search_documents(
    query: str,
    top_k: int = 10,
    type: Optional[str] = None
) -> str:
    """
    Semantic search for videos and documents. Routes to the configured RAG provider.

    This function maintains backward compatibility with the existing Marqo implementation
    while allowing seamless switching to Cosdata via the RAG_PROVIDER environment variable.

    Args:
        query: The search query in *English* (required)
        top_k: Maximum number of results to return (default: 10)
        type: Filter by document type: [`video`, `document`].
              Default is None, which means all types are considered.

    Returns:
        search_results: Formatted string with search results
    """
    print(f"\n[RAG ROUTER] Search invoked - provider: {RAG_PROVIDER}", flush=True)
    print(f"[RAG ROUTER] Query: '{query}' | top_k: {top_k} | type: {type}", flush=True)

    if RAG_PROVIDER == 'cosdata':
        from agents.tools.search_cosdata import search_documents_cosdata
        logger.debug(f"Routing search to Cosdata: query='{query}', top_k={top_k}, type={type}")
        return search_documents_cosdata(query=query, top_k=top_k, type=type)
    else:
        # Default to Marqo
        from agents.tools.search import search_documents as search_documents_marqo
        logger.debug(f"Routing search to Marqo: query='{query}', top_k={top_k}, type={type}")
        return search_documents_marqo(query=query, top_k=top_k, type=type)
