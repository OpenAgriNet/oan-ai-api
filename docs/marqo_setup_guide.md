
# Marqo Setup & Ingestion Guide

## 1. Setup Marqo Server

Run the following Docker command to start the Marqo server:

```bash
docker run --name marqo -p 8882:8882 \
    -e MARQO_MAX_CONCURRENT_SEARCH=50 \
    -e VESPA_POOL_SIZE=50 \
    marqoai/marqo:latest
```

## 2. Create a Marqo Index

- **Settings file**: `assets/new_marqo_settings.json`  
- **Model used**: `hf/multilingual-e5-large`

### Initialize Marqo Client

```python
import marqo

mq = marqo.Client(url=MARQO_ENDPOINT_URL)
```

### Create Index

```python
with open("assets/new_marqo_settings.json") as f:
    settings = json.load(f)

mq.create_index(index_name="your_index_name", settings_dict=settings)
```

## 3. Ingest Documents

```python
mq.index("your_index_name").add_documents(documents=[...])
```

## 4. Check Index Stats

```python
mq.index("your_index_name").get_stats()
```

## 5. Search Documents

```python
mq.index("your_index_name").search(q="your query", limit=10)
```
