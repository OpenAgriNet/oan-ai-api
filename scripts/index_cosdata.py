#!/usr/bin/env python3
"""
Cosdata Indexing Script

This script creates a Cosdata collection and indexes documents for the OAN AI API.
It can index from:
1. Sample JSON documents (assets/cosdata_sample_documents.json)
2. Database dumps (CSV/JSON format)

Usage:
    python scripts/index_cosdata.py --sample          # Index sample documents
    python scripts/index_cosdata.py --file data.json  # Index from JSON file
    python scripts/index_cosdata.py --file data.csv   # Index from CSV file
    python scripts/index_cosdata.py --recreate        # Recreate collection from scratch

Environment Variables Required:
    COSDATA_ENDPOINT_URL    - Cosdata server URL (default: http://127.0.0.1:8443)
    COSDATA_USERNAME        - Username (default: admin)
    COSDATA_PASSWORD        - Password (default: admin)
    COSDATA_COLLECTION_NAME - Collection name (default: oan-collection)
    EMBEDDING_MODEL_NAME    - Embedding model (default: intfloat/multilingual-e5-large)
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from functools import lru_cache
import logging

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Model name from environment
MODEL_NAME = os.getenv('EMBEDDING_MODEL_NAME', 'intfloat/multilingual-e5-large')

# Detect if using Qwen3 model
IS_QWEN3_MODEL = 'qwen3' in MODEL_NAME.lower()


@lru_cache(maxsize=1)
def get_embedding_model():
    """Load and cache the embedding model."""
    from sentence_transformers import SentenceTransformer
    logger.info(f"Loading embedding model: {MODEL_NAME}")

    # Qwen3 models need trust_remote_code
    if IS_QWEN3_MODEL:
        model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)
    else:
        model = SentenceTransformer(MODEL_NAME)

    logger.info(f"Model loaded. Embedding dimension: {model.get_sentence_embedding_dimension()}")
    return model


def get_embedding_dimension() -> int:
    """Get the embedding dimension from the loaded model."""
    model = get_embedding_model()
    return model.get_sentence_embedding_dimension()


def generate_embeddings(texts: List[str], is_query: bool = False) -> List[List[float]]:
    """
    Generate embeddings for texts.

    For E5 models: Uses 'passage: ' prefix for documents and 'query: ' for queries.
    For Qwen3 models: Uses prompt_name='query' for queries, no prefix for documents.
    """
    model = get_embedding_model()

    if IS_QWEN3_MODEL:
        # Qwen3 models use prompt_name for queries, no prefix for documents
        if is_query:
            embeddings = model.encode(texts, prompt_name="query", convert_to_numpy=True, show_progress_bar=True)
        else:
            embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=True)
    else:
        # E5 models use prefix
        prefix = "query: " if is_query else "passage: "
        prefixed_texts = [f"{prefix}{text}" for text in texts]
        embeddings = model.encode(prefixed_texts, convert_to_numpy=True, show_progress_bar=True)

    return embeddings.tolist()


def get_cosdata_client():
    """Initialize Cosdata client."""
    try:
        from cosdata import Client
    except ImportError:
        logger.error("cosdata-client not installed. Run: pip install cosdata-client")
        sys.exit(1)

    endpoint_url = os.getenv('COSDATA_ENDPOINT_URL', 'http://127.0.0.1:8443')
    username = os.getenv('COSDATA_USERNAME', 'admin')
    password = os.getenv('COSDATA_PASSWORD', 'admin')

    logger.info(f"Connecting to Cosdata at {endpoint_url}")
    client = Client(
        host=endpoint_url,
        username=username,
        password=password,
        verify=False
    )
    return client


def create_collection(client, collection_name: str, recreate: bool = False):
    """
    Create or get the Cosdata collection.

    Args:
        client: Cosdata client
        collection_name: Name of the collection
        recreate: If True, delete existing collection and create new
    """
    try:
        if recreate:
            try:
                logger.info(f"Deleting existing collection: {collection_name}")
                client.delete_collection(collection_name)
                logger.info("Collection deleted successfully")
            except Exception as e:
                logger.info(f"Collection doesn't exist or couldn't be deleted: {e}")

        # Try to get existing collection
        try:
            collection = client.get_collection(collection_name)
            logger.info(f"Using existing collection: {collection_name}")
            return collection
        except Exception:
            pass

        # Create new collection with dynamic dimension from model
        embedding_dim = get_embedding_dimension()
        logger.info(f"Creating new collection: {collection_name} with dimension {embedding_dim}")
        collection = client.create_collection(
            name=collection_name,
            dimension=embedding_dim,
            description="OAN AI agricultural knowledge base"
        )

        # Create index with optimized parameters
        logger.info("Creating vector index...")
        collection.create_index(
            distance_metric="cosine",
            num_layers=10,
            max_cache_size=1000,
            ef_construction=128,
            ef_search=64,
            neighbors_count=32,
            level_0_neighbors_count=64
        )
        logger.info("Index created successfully")
        return collection

    except Exception as e:
        logger.error(f"Error creating collection: {e}")
        raise


def load_sample_documents() -> List[Dict[str, Any]]:
    """Load sample documents from assets folder."""
    sample_file = project_root / "assets" / "wheat_manual_docs.json"

    if not sample_file.exists():
        logger.error(f"Sample file not found: {sample_file}")
        sys.exit(1)

    with open(sample_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return data.get('documents', [])


def load_documents_from_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Load documents from a JSON or CSV file.

    Expected JSON format:
    {
        "documents": [
            {"doc_id": "...", "type": "...", "name": "...", "text": "...", "location": "..."},
            ...
        ]
    }

    Expected CSV columns:
    doc_id, type, name, text, source, location
    """
    file_path = Path(file_path)

    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        sys.exit(1)

    if file_path.suffix.lower() == '.json':
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('documents', data if isinstance(data, list) else [])

    elif file_path.suffix.lower() == '.csv':
        import csv
        documents = []
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                documents.append(row)
        return documents

    else:
        logger.error(f"Unsupported file format: {file_path.suffix}")
        sys.exit(1)


def index_documents(collection, documents: List[Dict[str, Any]], batch_size: int = 50):
    """
    Index documents into Cosdata collection.

    Args:
        collection: Cosdata collection
        documents: List of document dictionaries
        batch_size: Number of documents to index per batch
    """
    total = len(documents)
    logger.info(f"Indexing {total} documents in batches of {batch_size}")

    for i in range(0, total, batch_size):
        batch = documents[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size

        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} documents)")

        # Extract texts for embedding
        texts = [doc.get('text', '') for doc in batch]

        # Generate embeddings (documents, not queries)
        embeddings = generate_embeddings(texts, is_query=False)

        # Prepare vectors for insertion
        # Store full document as JSON in text field for retrieval
        vectors = []
        for j, (doc, embedding) in enumerate(zip(batch, embeddings)):
            import json
            doc_json = json.dumps({
                "doc_id": doc.get('doc_id', ''),
                "type": doc.get('type', 'document'),
                "name": doc.get('name', ''),
                "text": doc.get('text', ''),
                "source": doc.get('source', ''),
            })
            vector = {
                "id": doc.get('doc_id', f"doc_{i + j}"),
                "dense_values": embedding,
                "text": doc_json,  # Store full doc as JSON
            }
            vectors.append(vector)

        # Insert batch using transaction
        try:
            with collection.transaction() as txn:
                for vector in vectors:
                    txn.upsert_vector(vector)
            logger.info(f"Batch {batch_num} indexed successfully")
        except Exception as e:
            logger.error(f"Error indexing batch {batch_num}: {e}")
            raise

    logger.info(f"Indexing complete. Total documents indexed: {total}")


def verify_index(collection, sample_query: str = "how to improve crop yield"):
    """Verify the index by running a test query."""
    logger.info(f"Verifying index with query: '{sample_query}'")

    # Generate query embedding
    query_embedding = generate_embeddings([sample_query], is_query=True)[0]

    # Search using the index
    try:
        index = collection.get_index()
        results = index.search(query_embedding, top_k=3)

        if results:
            logger.info(f"Verification successful. Found {len(results)} results:")
            for i, result in enumerate(results, 1):
                vector_id = result.get('id', 'Unknown')
                score = result.get('score', 0)
                logger.info(f"  {i}. ID: {vector_id} (score: {score:.4f})")
        else:
            logger.warning("Verification returned no results. Check your documents.")
    except Exception as e:
        logger.warning(f"Verification failed: {e}. Index may still be building.")


def main():
    parser = argparse.ArgumentParser(
        description='Index documents into Cosdata for OAN AI RAG',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--sample',
        action='store_true',
        help='Index sample documents from assets/wheat_manual_docs.json'
    )
    parser.add_argument(
        '--file',
        type=str,
        help='Path to JSON or CSV file containing documents to index'
    )
    parser.add_argument(
        '--recreate',
        action='store_true',
        help='Delete existing collection and create new one'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=50,
        help='Number of documents to index per batch (default: 50)'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Run verification query after indexing'
    )
    parser.add_argument(
        '--collection',
        type=str,
        default=os.getenv('COSDATA_COLLECTION_NAME', 'oan-collection'),
        help='Collection name (default: from COSDATA_COLLECTION_NAME env var)'
    )

    args = parser.parse_args()

    if not args.sample and not args.file:
        parser.error("Either --sample or --file must be specified")

    # Initialize client
    client = get_cosdata_client()

    # Create or get collection
    collection = create_collection(client, args.collection, recreate=args.recreate)

    # Load documents
    if args.sample:
        documents = load_sample_documents()
        logger.info(f"Loaded {len(documents)} sample documents")
    else:
        documents = load_documents_from_file(args.file)
        logger.info(f"Loaded {len(documents)} documents from {args.file}")

    # Index documents
    index_documents(collection, documents, batch_size=args.batch_size)

    # Verify if requested
    if args.verify:
        verify_index(collection)

    logger.info("Done!")


if __name__ == '__main__':
    main()
