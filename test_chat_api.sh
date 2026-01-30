#!/bin/bash

# Test the chat endpoint directly
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the current price of wheat in Amber market?",
    "session_id": "test-session-123",
    "user_id": "test-user",
    "source_lang": "en",
    "target_lang": "en"
  }' \
  --no-buffer
