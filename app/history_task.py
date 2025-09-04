import asyncio
import logging
from datetime import datetime

from app.database import SessionLocal
from app.models import GPSData
from app.redis_client import redis_async

logger = logging.getLogger(__name__)

# Redis list/stream key for history pipeline
HISTORY_QUEUE = "gps_history_queue"


async def history_writer():
    """
    Background task:
    - Runs inside FastAPI (startup_event in main.py)
    - Continuously consumes GPS entries from Redis queue
    - Persists them into Postgres
    """
    logger.info("🚀 History writer started")
    while True:
        try:
            if not redis_async:
                await asyncio.sleep(5)
                continue

            # Blocking pop with timeout
            item = await redis_async.blpop(HISTORY_QUEUE, timeout=5)
            if not item:
                continue

            _, raw = item
            if not raw:
                continue

            try:
                import json
                data = json.loads(raw)
            except Exception as e:
                logger.error(f"[HistoryWriter] Failed to decode JSON: {e}")
                continue

            bus_id = data.get("bus_id")
            route_id = data.get("route_id")
            lat = data.get("latitude")
            lon = data.get("longitude")
            speed = data.get("speed")
            ts = data.get("timestamp")

            if not bus_id or not lat or not lon:
                logger.warning(f"[HistoryWriter] Incomplete data skipped: {data}")
                continue

            db = SessionLocal()
            gps_row = GPSData(
                bus_id=bus_id,
                route_id=route_id,
                latitude=lat,
                longitude=lon,
                speed=speed,
                last_updated=datetime.fromisoformat(ts) if ts else datetime.utcnow(),
            )
            db.add(gps_row)
            db.commit()
            db.close()

            logger.info(f"[HistoryWriter] Saved GPS data for bus={bus_id} route={route_id}")

        except Exception as e:
            logger.exception(f"[HistoryWriter] Error: {e}")
            await asyncio.sleep(2)
