"""
Cosdata client implementation for vector search.
"""
import os
import re
import sys
import time
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from helpers.utils import get_logger
from functools import lru_cache

logger = get_logger(__name__)

DocumentType = Literal['video', 'document']

# Model name from environment
MODEL_NAME = os.getenv('EMBEDDING_MODEL_NAME', 'intfloat/multilingual-e5-large')

# Detect if using Qwen3 model
IS_QWEN3_MODEL = 'qwen3' in MODEL_NAME.lower()


class CosdataSearchHit(BaseModel):
    """Individual search hit from Cosdata"""
    name: str
    text: str
    doc_id: str
    type: str
    source: str
    score: float
    id: str

    @property
    def processed_text(self) -> str:
        """Returns the text with cleaned up whitespace and newlines"""
        cleaned = re.sub(r'\n{2,}', '\n\n', self.text)
        cleaned = re.sub(r'\t+', '\t', cleaned)
        return cleaned

    def __str__(self) -> str:
        if self.type == 'document':
            return f"**{self.name}**\n" + "```\n" + self.processed_text + "\n```\n"
        else:
            return f"**[{self.name}]({self.source})**\n" + "```\n" + self.processed_text + "\n```\n"


@lru_cache(maxsize=1)
def get_embedding_model():
    """
    Lazily load and cache the embedding model.
    Supports both E5 and Qwen3 models.
    """
    from sentence_transformers import SentenceTransformer
    logger.info(f"Loading embedding model: {MODEL_NAME}")

    # Qwen3 models need trust_remote_code
    if IS_QWEN3_MODEL:
        return SentenceTransformer(MODEL_NAME, trust_remote_code=True)
    else:
        return SentenceTransformer(MODEL_NAME)


def generate_query_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for query texts using sentence-transformers.

    For E5 models: Uses 'query: ' prefix.
    For Qwen3 models: Uses prompt_name='query'.
    """
    model = get_embedding_model()

    if IS_QWEN3_MODEL:
        # Qwen3 models use prompt_name for queries
        embeddings = model.encode(texts, prompt_name="query", convert_to_numpy=True)
    else:
        # E5 models require 'query: ' prefix for queries
        prefixed_texts = [f"query: {text}" for text in texts]
        embeddings = model.encode(prefixed_texts, convert_to_numpy=True)

    return embeddings.tolist()


def get_cosdata_client():
    """
    Initialize and return the Cosdata client.
    """
    try:
        from cosdata import Client
    except ImportError:
        raise ImportError(
            "cosdata-client is not installed. "
            "Install it with: pip install cosdata-client"
        )

    endpoint_url = os.getenv('COSDATA_ENDPOINT_URL', 'http://127.0.0.1:8443')
    username = os.getenv('COSDATA_USERNAME', 'admin')
    password = os.getenv('COSDATA_PASSWORD', 'admin')

    client = Client(
        host=endpoint_url,
        username=username,
        password=password,
        verify=False
    )
    return client


def load_document_store():
    """
    Load the document store from local file.

    Supports array format: {"documents": [{"doc_id": "...", ...}, ...]}
    Returns a dict keyed by doc_id for fast lookup.
    """
    import json
    from pathlib import Path

    # Use the combined agricultural docs file
    doc_store_path = Path(__file__).parent.parent.parent / "assets" / "all_agricultural_docs.json"

    if not doc_store_path.exists():
        logger.warning(f"Document store not found: {doc_store_path}")
        return {}

    with open(doc_store_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Handle array format: {"documents": [...]}
    if isinstance(data, dict) and 'documents' in data:
        documents = data['documents']
        return {doc.get('doc_id', f"doc_{i}"): doc for i, doc in enumerate(documents)}

    # Handle raw array format
    if isinstance(data, list):
        return {doc.get('doc_id', f"doc_{i}"): doc for i, doc in enumerate(data)}

    return {}


def search_documents_cosdata(
    query: str,
    top_k: int = 10,
    type: Optional[str] = None
) -> str:
    """
    Semantic search for agricultural knowledge documents and videos using Cosdata vector database.

    Args:
        query: The search query in *English* (required)
        top_k: Maximum number of results to return (default: 10)
        type: Filter by document type: [`video`, `document`].
              Default is None, which means all types are considered.

    Returns:
        search_results: Formatted string with search results or message if no data available
    """
    collection_name = os.getenv('COSDATA_COLLECTION_NAME', 'oan-collection')
    start_time = time.time()

    try:
        client = get_cosdata_client()
        collection = client.get_collection(collection_name)

        # Load document store for metadata lookup
        doc_store = load_document_store()

        # Generate embedding for the query
        embedding_start = time.time()
        query_embedding = generate_query_embeddings([query])[0]
        embedding_time = time.time() - embedding_start
        logger.info(f"RAG embedding generation took {embedding_time:.3f}s for query: '{query}'")
        print(f"\n[RAG] Embedding generation: {embedding_time:.3f}s | Query: '{query}'", flush=True)

        # Perform vector search using dense search
        search_start = time.time()
        search_results = collection.search.dense(query_embedding, top_k=top_k * 2)  # Get extra for filtering
        search_time = time.time() - search_start
        logger.info(f"RAG vector search took {search_time:.3f}s")
        print(f"[RAG] Vector search: {search_time:.3f}s", flush=True)

        results = search_results.get('results', [])

        if not results:
            total_time = time.time() - start_time
            logger.info(f"RAG total time: {total_time:.3f}s - No results found")
            return f"No results found for `{query}`. The information you're looking for may not be available in our knowledge base."

        # Build search hits from results using document store
        search_hits = []
        for result in results:
            if len(search_hits) >= top_k:
                break

            vector_id = result.get('id', '')
            score = result.get('score', 0.0)

            # Look up document data from local store
            doc_data = doc_store.get(vector_id, {})
            if not doc_data:
                continue

            # Filter by type if specified
            if type is not None and doc_data.get('type') != type:
                continue

            hit_data = {
                "name": doc_data.get("name", "Unknown"),
                "text": doc_data.get("text", ""),
                "doc_id": doc_data.get("doc_id", vector_id),
                "type": doc_data.get("type", "document"),
                "source": doc_data.get("source", ""),
                "score": score,
                "id": vector_id,
            }
            search_hits.append(CosdataSearchHit(**hit_data))

        if not search_hits:
            total_time = time.time() - start_time
            logger.info(f"RAG total time: {total_time:.3f}s - No results after filtering")
            return f"No results found for `{query}`. The information you're looking for may not be available in our knowledge base."

        # Format results
        document_string = '\n\n----\n\n'.join([str(doc) for doc in search_hits])
        rag_response = "> Search Results for `" + query + "`\n\n" + document_string

        # Log RAG response and timing
        total_time = time.time() - start_time
        logger.info(f"RAG total time: {total_time:.3f}s (embedding: {embedding_time:.3f}s, search: {search_time:.3f}s)")
        logger.info(f"RAG returned {len(search_hits)} results for query: '{query}'")
        logger.debug(f"RAG response preview (first 500 chars):\n{rag_response[:500]}...")

        # Print RAG summary to terminal
        print(f"[RAG] Query: '{query}' | Results: {len(search_hits)} | Time: {total_time:.2f}s | Chars: {len(rag_response)}", flush=True)

        return rag_response

    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"Cosdata search error after {total_time:.3f}s: {str(e)}")
        return f"Error searching for `{query}`: Unable to retrieve data. Please try again later."
