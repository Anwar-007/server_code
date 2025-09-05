import json
import logging
import redis.asyncio as aioredis
import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# -----------------------
# Async Redis (for FastAPI)
# -----------------------
redis_async: aioredis.Redis = None

async def init_redis():
    """Initialize async Redis connection for FastAPI"""
    global redis_async
    redis_async = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=20
    )
    try:
        pong = await redis_async.ping()
        if pong:
            logger.info("✅ Connected to Redis (async)")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Redis (async): {e}")


async def get_current_stop(bus_id: str):
    """Fetch current stop for a bus from Redis"""
    if not redis_async:
        raise RuntimeError("Redis not initialized")
    key = f"current_stop:{bus_id}"
    data = await redis_async.get(key)
    return json.loads(data) if data else None


async def ack_current_stop(bus_id: str, stop_id: str):
    """Application acknowledges stop message"""
    if not redis_async:
        raise RuntimeError("Redis not initialized")
    key = f"ack:{bus_id}:{stop_id}"
    await redis_async.set(key, "1", ex=60)
    return True


# -----------------------
# Sync Redis (for Celery workers)
# -----------------------
redis_sync: redis.Redis = redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_timeout=5
)

def push_sync(key: str, value: dict, expire: int = 60):
    try:
        redis_sync.set(key, json.dumps(value), ex=expire)
        return True
    except Exception as e:
        logger.error(f"[Redis Sync] Failed to push {key}: {e}")
        return False


def get_sync(key: str):
    try:
        data = redis_sync.get(key)
        return json.loads(data) if data else None
    except Exception as e:
        logger.error(f"[Redis Sync] Failed to get {key}: {e}")
        return None
