"""
Core cache instance configuration using Redis and aiocache.

This module provides the cache instance that other parts of the application can use.
Uses enhanced Redis configuration with connection pooling and timeouts.
"""
from aiocache import Cache
from aiocache.serializers import JsonSerializer
from app.config import settings
from helpers.utils import get_logger

logger = get_logger(__name__)

# Configure the cache instance with enhanced settings from Django
cache = Cache(
    Cache.REDIS,
    endpoint=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    serializer=JsonSerializer(),
    ttl=settings.default_cache_ttl,
    # Enhanced connection settings
    timeout=settings.redis_socket_timeout,
    pool_max_size=settings.redis_max_connections,
    # Add key prefix support
    key_builder=lambda key, namespace: f"{settings.redis_key_prefix}{namespace}:{key}" if namespace else f"{settings.redis_key_prefix}{key}",
)

logger.info(
    f"Cache configured with Redis at {settings.redis_host}:{settings.redis_port} "
    f"(DB: {settings.redis_db}, Prefix: {settings.redis_key_prefix}, "
    f"Max Connections: {settings.redis_max_connections})"
) 