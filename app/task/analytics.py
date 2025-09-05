# app/tasks/analytics.py

import logging
import asyncio
from datetime import timedelta
from sqlalchemy import select
from app.celery_worker import celery_app
from app.database import async_session
from app.models import GPSData, RouteStops, StopData
from geopy.distance import geodesic

logger = logging.getLogger(__name__)


async def _analyze_gps_data(bus_id: str, route_id: str):
    async with async_session() as db:  # AsyncSession
        # Get latest GPS
        result = await db.execute(
            select(GPSData)
            .where(GPSData.bus_id == bus_id, GPSData.route_id == route_id)
            .order_by(GPSData.last_updated.desc())
        )
        latest_gps = result.scalars().first()
        if not latest_gps:
            return {"status": "no_gps"}

        current_point = (latest_gps.latitude, latest_gps.longitude)

        # Fetch stops
        result = await db.execute(
            select(RouteStops, StopData)
            .join(StopData, StopData.id == RouteStops.stop_id)
            .where(RouteStops.route_id == route_id, RouteStops.bus_id == bus_id)
        )
        stops = result.all()
        if not stops:
            return {"status": "no_stops"}

        nearest_stop, nearest_distance = None, float("inf")
        results = []

        for route_stop, stop in stops:
            stop_point = (stop.latitude, stop.longitude)
            distance_km = geodesic(current_point, stop_point).km
            if distance_km < nearest_distance:
                nearest_distance = distance_km
                nearest_stop = stop

            eta_time = None
            if latest_gps.speed and latest_gps.speed > 0:
                eta_minutes = distance_km / (latest_gps.speed / 60)
                eta_time = latest_gps.last_updated + timedelta(minutes=eta_minutes)
                route_stop.approx_time = eta_time
                db.add(route_stop)

            results.append({
                "stop_id": stop.id,
                "stop_name": stop.stop_name,
                "distance_km": round(distance_km, 3),
                "eta_time": eta_time.isoformat() if eta_time else None,
            })

        await db.commit()

        return {
            "status": "success",
            "bus_id": bus_id,
            "route_id": route_id,
            "nearest_stop": nearest_stop.stop_name if nearest_stop else None,
            "stops": results,
        }


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def analyze_gps_data(self, bus_id: str, route_id: str):
    """Celery entrypoint → runs async analysis."""
    try:
        return asyncio.run(_analyze_gps_data(bus_id, route_id))
    except Exception as e:
        logger.exception(f"[Analytics] Error for bus={bus_id}: {e}")
        raise self.retry(exc=e)
