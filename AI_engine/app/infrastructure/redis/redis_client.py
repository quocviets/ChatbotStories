import logging
import json
from typing import Any, Optional
import redis.asyncio as aioredis
from app.config import REDIS_URL

logger = logging.getLogger(__name__)

redis_client: Optional[aioredis.Redis] = None


async def init_redis():
    """Initializes connection to the Redis server."""
    global redis_client
    try:
        logger.info(f"Connecting to Redis at: {REDIS_URL}...")
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
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


# --- Cache Helper Actions ---

async def set_cache(key: str, value: Any, ttl_seconds: Optional[int] = None):
    client = get_redis()
    serialized = json.dumps(value)
    if ttl_seconds:
        await client.setex(key, ttl_seconds, serialized)
    else:
        await client.set(key, serialized)
    logger.debug(f"Redis Cache SET: key={key}, ttl={ttl_seconds}")


async def get_cache(key: str) -> Optional[Any]:
    client = get_redis()
    value = await client.get(key)
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


async def delete_cache(key: str):
    client = get_redis()
    await client.delete(key)
    logger.debug(f"Redis Cache DELETE: key={key}")


# --- Lock Actions ---

async def acquire_lock(lock_key: str, expire_seconds: int = 300) -> bool:
    client = get_redis()
    success = await client.set(lock_key, "locked", ex=expire_seconds, nx=True)
    if success:
        logger.debug(f"Redis Lock ACQUIRED: key={lock_key}")
        return True
    return False


async def release_lock(lock_key: str):
    client = get_redis()
    await client.delete(lock_key)
    logger.debug(f"Redis Lock RELEASED: key={lock_key}")
