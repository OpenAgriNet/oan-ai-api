# API Reference Documentation

## Overview
This API provides audio transcription, text-to-speech, and chat services using the Bhashini platform. It supports multiple Indian languages with a focus on Marathi and English.

## Base URL
```
http://localhost:8000
```

## Authentication
All endpoints require JWT authentication. Include the JWT token in the Authorization header:
```
Authorization: Bearer your_jwt_token
```

## Endpoints

### 1. Transcribe Audio
Transcribes audio content from base64 encoded string.

**Endpoint:** `POST /transcribe`

**Request Body:**
```json
{
    "audio_content": "base64_encoded_audio_string",
    "session_id": "optional_session_id"  // Optional, will generate UUID if not provided
}
```

**Curl Command:**
```bash
curl -X POST http://localhost:8000/transcribe \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_jwt_token" \
  -d '{
    "audio_content": "your_base64_encoded_audio",
    "session_id": "optional_session_id"
  }'
```

**Response:**
```json
{
    "status": "success",
    "text": "transcribed text",
    "lang_code": "mr",
    "session_id": "session_id"
}
```

### 2. Text to Speech
Converts text to speech in the specified language.

**Endpoint:** `POST /tts`

**Request Body:**
```json
{
    "text": "text to convert to speech",
    "target_lang": "mr",  // Optional, defaults to 'mr' (Marathi)
    "session_id": "optional_session_id"  // Optional, will generate UUID if not provided
}
```

**Curl Command:**
```bash
curl -X POST http://localhost:8000/tts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_jwt_token" \
  -d '{
    "text": "your text here",
    "target_lang": "mr",
    "session_id": "optional_session_id"
  }'
```

**Response:**
```json
{
    "status": "success",
    "audio_data": "base64_encoded_audio",
    "session_id": "session_id"
}
```

### 3. Chat
Streams chat responses from the AI assistant.

**Endpoint:** `GET /chat`

**Query Parameters:**
- `query` (required): The user's question
- `session_id` (optional): Chat session identifier
- `source_lang` (optional): Source language code, defaults to 'mr'
- `target_lang` (optional): Target language code, defaults to 'mr'
- `user_id` (optional): User identifier, defaults to 'anonymous'

**Curl Command:**
```bash
curl -X GET "http://localhost:8000/chat?query=your_question&session_id=optional_session_id&source_lang=mr&target_lang=mr&user_id=user123" \
  -H "Authorization: Bearer your_jwt_token"
```

**Response:**
Server-Sent Events (SSE) stream with chunks of the response.

### 4. Suggestions
Get suggested follow-up questions for a chat session.

**Endpoint:** `GET /suggestions`

**Query Parameters:**
- `session_id` (required): Chat session identifier
- `target_lang` (optional): Target language code, defaults to 'mr'

**Curl Command:**
```bash
curl -X GET "http://localhost:8000/suggestions?session_id=your_session_id&target_lang=mr" \
  -H "Authorization: Bearer your_jwt_token"
```

**Response:**
```json
[
    "suggestion 1",
    "suggestion 2",
    "suggestion 3"
]
```

## Supported Languages
- Marathi (mr)
- English (en)
