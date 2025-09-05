# app/tasks/current_stop.py
import logging
import json
import asyncio
import redis
from datetime import datetime
from sqlalchemy import select
from app.celery_worker import celery_app
from app.database import async_session
from app.models import RouteStops, StopData, GPSData
from geopy.distance import geodesic

logger = logging.getLogger(__name__)

REDIS_URL = "redis://localhost:6379/1"
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)


async def _push_current_stop(bus_id: str, route_id: str):
    async with async_session() as db:
        result = await db.execute(
            select(GPSData)
            .where(GPSData.bus_id == bus_id, GPSData.route_id == route_id)
            .order_by(GPSData.last_updated.desc())
        )
        gps = result.scalars().first()
        if not gps:
            return {"status": "no_gps"}

        current_point = (gps.latitude, gps.longitude)

        result = await db.execute(
            select(RouteStops, StopData)
            .join(StopData, StopData.id == RouteStops.stop_id)
            .where(RouteStops.route_id == route_id, RouteStops.bus_id == bus_id)
        )
        stops = result.all()
        if not stops:
            return {"status": "no_stops"}

        nearest_stop, nearest_distance = None, float("inf")
        for route_stop, stop in stops:
            distance_km = geodesic(current_point, (stop.latitude, stop.longitude)).km
            if distance_km < nearest_distance:
                nearest_distance, nearest_stop = distance_km, stop

        if not nearest_stop:
            return {"status": "no_nearest_stop"}

        payload = {
            "bus_id": bus_id,
            "route_id": route_id,
            "stop_id": nearest_stop.id,
            "stop_name": nearest_stop.stop_name,
            "distance_km": round(nearest_distance, 3),
            "timestamp": datetime.utcnow().isoformat(),
        }

        key = f"current_stop:{bus_id}"
        redis_client.set(key, json.dumps(payload), ex=60)
        logger.info(f"[CurrentStop] Pushed: {payload}")

        return {"status": "pushed", "stop": nearest_stop.stop_name}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=5)
def push_current_stop(self, bus_id: str, route_id: str):
    try:
        return asyncio.run(_push_current_stop(bus_id, route_id))
    except Exception as e:
        logger.exception(f"[CurrentStop] Error bus={bus_id}: {e}")
        raise self.retry(exc=e, countdown=10)
