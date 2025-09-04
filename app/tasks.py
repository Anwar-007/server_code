# app/tasks.py
from __future__ import annotations

import logging
from datetime import datetime

from celery import shared_task
from sqlalchemy.exc import SQLAlchemyError

from app.utils.db import get_session
from app.utils.nearest_stop import find_nearest_stop
from app.models import GPSData, BusUser, Route, StopData, RouteStops
from app.utils.redis_client import redis_client

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def save_gps_data(self, imei: str, timestamp: str, lat: float, lon: float, speed: int):
    """
    Celery task to save GPS data to Postgres and run analytics.
    - Finds bus_id from imei
    - Stores GPS point
    - Runs stop detection
    - Pushes result to Redis
    """
    session = get_session()

    try:
        # 1. Lookup bus by IMEI
        bus = session.query(BusUser).filter(BusUser.IMEI == imei).first()
        if not bus:
            logger.warning(f"Unknown bus IMEI={imei}, ignoring GPS point.")
            return

        # 2. Lookup active route for bus (latest route for today)
        route = (
            session.query(Route)
            .filter(Route.bus_id == bus.id)
            .order_by(Route.start_time_approx.desc())
            .first()
        )

        if not route:
            logger.warning(f"No active route for bus {bus.bus_number} (IMEI={imei}).")
            return

        # 3. Insert GPS record
        gps_record = GPSData(
            bus_id=bus.id,
            route_id=route.id,
            latitude=lat,
            longitude=lon,
            speed=speed,
            last_updated=datetime.fromisoformat(timestamp),
        )
        session.add(gps_record)
        session.commit()
        logger.info(f"Saved GPS for bus {bus.bus_number}: ({lat}, {lon})")

        # 4. Fetch route stops
        route_stops = (
            session.query(RouteStops, StopData)
            .join(StopData, RouteStops.stop_id == StopData.id)
            .filter(RouteStops.route_id == route.id)
            .all()
        )
        stops_list = [
            {
                "stop_id": stop.id,
                "stop_name": stop.stop_name,
                "latitude": stop.latitude,
                "longitude": stop.longitude,
            }
            for _, stop in route_stops
        ]

        # 5. Find nearest stop
        nearest = find_nearest_stop(
            {"latitude": lat, "longitude": lon}, stops_list, max_distance_km=0.5
        )
        if nearest:
            stop, distance = nearest
            stop_payload = {
                "bus_id": str(bus.id),
                "stop_id": str(stop["stop_id"]),
                "stop_name": stop["stop_name"],
                "distance_km": distance,
                "timestamp": timestamp,
            }

            # 6. Push to Redis
            redis_key = f"bus:{bus.id}:current_stop"
            redis_client.set(redis_key, str(stop_payload))
            logger.info(f"Bus {bus.bus_number} near stop {stop['stop_name']} ({distance:.2f} km)")

        else:
            logger.info(f"Bus {bus.bus_number} not near any stop (lat={lat}, lon={lon}).")

    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"DB error saving GPS data: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Unexpected error in save_gps_data: {e}")
        raise self.retry(exc=e)
    finally:
        session.close()
