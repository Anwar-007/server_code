import asyncio
import datetime
from redis_client import get_all_current_stops
from database import SessionLocal
from models import BusHistory

async def history_writer():
    while True:
        try:
            stops = await get_all_current_stops()
            async with SessionLocal() as db:
                for bus_number, stop in stops.items():
                    entry = BusHistory(
                        bus_number=bus_number,
                        stop_name=stop["stop"],
                        lat=stop["lat"],
                        lng=stop["lng"],
                        distance_km=stop["distance_km"],
                        timestamp=datetime.datetime.utcnow()
                    )
                    db.add(entry)
                await db.commit()
        except Exception as e:
            print("History task error:", e)
        await asyncio.sleep(60)  # run every 1 min
