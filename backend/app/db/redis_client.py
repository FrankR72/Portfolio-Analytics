"""Redis client for caching stock prices.

One client for the whole process, created on import (like the engine in
database.py). It holds its own connection pool and doesn't connect until
the first command. None when REDIS_URL is not set: the cache is off.
"""

import redis
from core.config import settings


def create_redis_client() -> redis.Redis | None:
    """Return the Redis client, or None when REDIS_URL is not set."""
    if not settings.redis_url:
        return None
    return redis.Redis.from_url(
        url=settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )

redis_client = create_redis_client()
