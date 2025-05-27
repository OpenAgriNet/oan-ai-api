# oan-ai-api
OpenAgriNet AI API

## Delete all volumes
```
docker system prune -a --volumes
```

----
# Create a new network
```
docker network create oannetwork
```
# Run seperate Redis
```
docker run -d --name redis-stack --network oannetwork -p 6379:6379 -p 8001:8001 redis/redis-stack:latest
```
# Docker Setup
```
docker compose up --build --force-recreate --detach
```
# Stop
```
docker compose down --remove-orphans
```

# Docker logs
```
docker logs -f oan_app
```

# Marqo
```
docker run --name marqo -p 8882:8882 \
    -e MARQO_MAX_CONCURRENT_SEARCH=50 \
    -e VESPA_POOL_SIZE=50 \
    marqoai/marqo:latest
```