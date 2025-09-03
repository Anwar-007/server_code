import aioredis
import json

redis = None

async def init_redis():
    global redis
    redis = await aioredis.from_url("redis://localhost", decode_responses=True)

async def save_current_stop(bus_number: str, stop_data: dict):
    if redis is None:
        raise RuntimeError("Redis not initialized")
    await redis.set(f"bus:{bus_number}:current_stop", json.dumps(stop_data), ex=60)

async def get_current_stop(bus_number: str):
    if redis is None:
        raise RuntimeError("Redis not initialized")
    data = await redis.get(f"bus:{bus_number}:current_stop")
    return json.loads(data) if data else None

async def get_all_current_stops():
    if redis is None:
        raise RuntimeError("Redis not initialized")
    keys = await redis.keys("bus:*:current_stop")
    result = {}
    for key in keys:
        data = await redis.get(key)
        if data:
            bus_number = key.split(":")[1]
            result[bus_number] = json.loads(data)
    return result
