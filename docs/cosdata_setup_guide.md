# Cosdata Vector Database Setup Guide

This guide explains how to set up and use Cosdata as the RAG (Retrieval-Augmented Generation) backend for the OAN AI API.

## Overview

Cosdata is a high-performance vector database designed for AI applications. The OAN AI API uses it for semantic search over agricultural knowledge documents.

## Prerequisites

- Docker and Docker Compose
- Python 3.10+
- Existing OAN AI API setup

## Quick Start

### 1. Start Cosdata Server

**Option A: Using Docker Compose (Recommended)**

```bash
docker-compose -f docker-compose.cosdata.yml up -d
```

Note: On first run, you may need to set the admin key interactively:

```bash
# Create volume and start with admin key
docker volume create cosdata_data
printf 'admin\nadmin\n' | docker run -i --name cosdata \
  -v cosdata_data:/opt/cosdata/data \
  -p 8443:8443 -p 50051:50051 \
  cosdatateam/cosdata:latest
```

**Option B: Using Docker Run directly**

```bash
docker run -d \
  --name cosdata \
  -p 8443:8443 \
  -p 50051:50051 \
  -v cosdata_data:/opt/cosdata/data \
  cosdatateam/cosdata:latest
```

### 2. Install Python Dependencies

```bash
pip install cosdata-client>=0.2.2 sentence-transformers>=2.2.0
```

### 3. Configure Environment

Add to your `.env` file:

```env
RAG_PROVIDER=cosdata
COSDATA_ENDPOINT_URL=http://127.0.0.1:8443
COSDATA_USERNAME=admin
COSDATA_PASSWORD=admin
COSDATA_COLLECTION_NAME=oan-collection
EMBEDDING_MODEL_NAME=intfloat/multilingual-e5-large
```

### 4. Index Documents

```bash
# Index sample documents (wheat manual)
python scripts/index_cosdata.py --sample --recreate --verify

# Or index from a custom file
python scripts/index_cosdata.py --file /path/to/docs.json --verify
```

## Document Types

The system supports two document types:
- `document` - Agricultural knowledge articles, guides, best practices
- `video` - Educational video content with descriptions

## Sample Queries

The knowledge base answers questions like:
- "What factors affect crop yield?"
- "How to improve cotton yield?"
- "Best practices for soybean farming"
- "How to manage pests organically?"
- "Water management techniques"

## Switching RAG Providers

### Use Marqo (default)
```env
RAG_PROVIDER=marqo
```

### Use Cosdata
```env
RAG_PROVIDER=cosdata
```

## Embedding Model

Uses `intfloat/multilingual-e5-large` for consistency with Marqo:
- Dimension: 1024
- Supports 100+ languages including English, Hindi, Marathi

## Indexing Custom Documents

### JSON Format
```json
{
  "documents": [
    {
      "doc_id": "unique_id",
      "type": "document",
      "name": "Document Title",
      "text": "Full text content",
      "source": "Source name"
    }
  ]
}
```

### Index from File
```bash
python scripts/index_cosdata.py --file /path/to/docs.json --verify
```

## Troubleshooting

### Connection Refused
Ensure Cosdata is running: `docker ps | grep cosdata`

### Collection Not Found
Run: `python scripts/index_cosdata.py --sample`

### Slow First Query
Embedding model is loaded on first use. Subsequent queries are faster.
