import logging
from typing import Optional
import redis.asyncio as aioredis
from urllib.parse import urlsplit
from app.config import REDIS_URL

logger = logging.getLogger(__name__)

redis_client: Optional[aioredis.Redis] = None


async def init_redis():
    """Initializes connection to the Redis server."""
    global redis_client
    try:
        target = urlsplit(REDIS_URL)
        logger.info("Connecting to Redis host=%s port=%s db=%s", target.hostname, target.port, target.path.lstrip("/"))
        redis_client = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
            health_check_interval=30
        )
        await redis_client.ping()
        logger.info("Redis client connected successfully.")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise e


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.aclose()
        logger.info("Redis connection closed.")


def get_redis() -> aioredis.Redis:
    if redis_client is None:
        raise ValueError("Redis client is not initialized.")
    return redis_client
