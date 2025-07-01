
# Redis Setup Guide

##  Create a New Docker Network

```bash
docker network create oannetwork
```

##  Run Redis Stack in a Separate Container

```bash
docker run -d --name redis-stack --network oannetwork \
    -p 6379:6379 -p 8001:8001 redis/redis-stack:latest
```

Note: RedisInsight should be running and accessible on port 8000 for monitoring.
