# OpenAgriNet AI API

OpenAgriNet is part of Maharashtra's smart farming Digital Public Infrastructure (DPI) initiative. OAN powers MahaVistaar, an AI-driven agricultural assistant that brings expert farming knowledge to every farmer in simple language.

For more information about OpenAgriNet, visit: https://openagrinet.global/

## Features

- Location-based market prices for crops
- Current and upcoming weather information
- Nearest storage facility lookup
- Crop selection guidance by region
- Pest and disease management advice
- Best practices for specific crops

## Benefits

- Multi-language support (Marathi and English)
- 24/7 accessibility via mobile or computer
- Integration with trusted agricultural sources
- Location-specific personalized advice
- Continuous improvement based on farmer feedback

## Data Sources

- Agricultural universities' Package of Practices (PoP)
- IMD (India Meteorological Department) weather data
- APMC (Agricultural Produce Market Committee) market prices
- Registered warehouse database

## Docker Setup

### Prerequisites

- Docker installed on your system
- Docker Compose installed on your system

### Network Setup

Create a dedicated network:
```bash
docker network create oannetwork
```

### Redis Setup

Run Redis Stack:
```bash
docker run -d --name redis-stack --network oannetwork \
    -p 6379:6379 -p 8001:8001 redis/redis-stack:latest
```

### Marqo Setup

Run Marqo search engine:
```bash
docker run --name marqo -p 8882:8882 \
    -e MARQO_MAX_CONCURRENT_SEARCH=50 \
    -e VESPA_POOL_SIZE=50 \
    marqoai/marqo:latest
```

### Main Application

Start the application:
```bash
docker compose up --build --force-recreate --detach
```

Stop the application:
```bash
docker compose down --remove-orphans
```

View application logs:
```bash
docker logs -f oan_app
```

## API Reference

### Base URL
```
http://localhost:8000
```

### Authentication
All endpoints require JWT authentication. Include the JWT token in the Authorization header:
```
Authorization: Bearer your_jwt_token
```

### Available Endpoints

#### 1. Transcribe Audio
```bash
curl -X POST http://localhost:8000/transcribe \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_jwt_token" \
  -d '{
    "audio_content": "your_base64_encoded_audio",
    "session_id": "optional_session_id"
  }'
```

#### 2. Text to Speech
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

#### 3. Chat
```bash
curl -X GET "http://localhost:8000/chat?query=your_question&session_id=optional_session_id&source_lang=mr&target_lang=mr&user_id=user123" \
  -H "Authorization: Bearer your_jwt_token"
```

#### 4. Suggestions
```bash
curl -X GET "http://localhost:8000/suggestions?session_id=your_session_id&target_lang=mr" \
  -H "Authorization: Bearer your_jwt_token"
```

### Supported Languages
- Marathi (mr)
- English (en)

For detailed API documentation including request/response schemas, please see [API_REFERENCE.md](docs/api.md)

## Contributing

Contribution guidelines will be added soon.