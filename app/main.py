import logging
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db, Base, engine
from app.models import BusUser, Routes, StopData, RouteStops, GPSData
from app.schemas import RegisterBus, RouteUpload, GPSIngest, CurrentStopOut
from app.tasks.analytics import process_gps_point
from app.tasks.current_stop import push_current_stop, redis_client

app = FastAPI(title="Bus Tracker API", version="1.0")

logger = logging.getLogger(__name__)


# -----------------------
# Startup Event
# -----------------------
@app.on_event("startup")
async def startup_event():
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized")


# -----------------------
# Bus Registration
# -----------------------
@app.post("/register_bus")
async def register_bus(bus: RegisterBus, db: AsyncSession = Depends(get_db)):
    # Check if bus already exists
    result = await db.execute(select(BusUser).where(BusUser.bus_number == bus.bus_number))
    existing = result.scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="Bus already registered")

    new_bus = BusUser(bus_number=bus.bus_number, IMEI=bus.IMEI)
    db.add(new_bus)
    await db.commit()
    await db.refresh(new_bus)
    return {"message": f"Bus {bus.bus_number} registered", "id": new_bus.id}


# -----------------------
# Route Upload
# -----------------------
@app.post("/upload_route")
async def upload_route(route: RouteUpload, db: AsyncSession = Depends(get_db)):
    # Ensure bus exists
    result = await db.execute(select(BusUser).where(BusUser.id == route.bus_id))
    bus = result.scalars().first()
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")

    # Create new route
    new_route = Routes(
        bus_id=route.bus_id,
        start_point=route.start_point,
        end_point=route.end_point,
        start_time_approx=route.start_time_approx,
        end_time_approx=route.end_time_approx,
    )
    db.add(new_route)
    await db.flush()

    # Add stops
    for s in route.stops:
        stop = StopData(stop_name=s.stop_name, latitude=s.latitude, longitude=s.longitude)
        db.add(stop)
        await db.flush()

        route_stop = RouteStops(
            stop_id=stop.id,
            route_id=new_route.id,
            bus_id=route.bus_id,
            approx_time=s.scheduled_time,
        )
        db.add(route_stop)

    await db.commit()
    return {"message": f"Route {route.start_point} → {route.end_point} uploaded"}


# -----------------------
# GPS Ingest
# -----------------------
@app.post("/gps")
async def gps_ingest(payload: GPSIngest, db: AsyncSession = Depends(get_db)):
    # Match bus by IMEI
    result = await db.execute(select(BusUser).where(BusUser.IMEI == payload.imei))
    bus = result.scalars().first()
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not registered")

    # Find latest route for this bus
    result = await db.execute(select(Routes).where(Routes.bus_id == bus.id))
    route = result.scalars().first()

    gps_entry = GPSData(
        bus_id=bus.id,
        route_id=route.id if route else None,
        latitude=payload.latitude,
        longitude=payload.longitude,
        speed=payload.speed,
        last_updated=payload.timestamp,
    )
    db.add(gps_entry)
    await db.commit()

    # Send to Celery for analytics
    process_gps_point.delay(
        bus_id=bus.id,
        route_id=route.id if route else None,
        latitude=payload.latitude,
        longitude=payload.longitude,
        speed=payload.speed,
        timestamp=payload.timestamp.isoformat(),
    )

    # Send to current stop detection
    if route:
        push_current_stop.delay(bus.id, route.id)

    return {"status": "gps_ingested"}


# -----------------------
# Get Current Stop (from Redis)
# -----------------------
@app.get("/current_stop/{bus_id}", response_model=CurrentStopOut)
async def get_current_stop(bus_id: str):
    key = f"current_stop:{bus_id}"
    data = redis_client.get(key)
    if not data:
        raise HTTPException(status_code=404, detail="No stop info available")

    import json
    payload = json.loads(data)
    return CurrentStopOut(**payload)


# -----------------------
# Acknowledge Stop
# -----------------------
@app.post("/ack/{bus_id}/{stop_id}")
async def ack_stop(bus_id: str, stop_id: str):
    key = f"ack:{bus_id}:{stop_id}"
    redis_client.set(key, "1", ex=60)  # expire ACK after 60s
    return {"status": "ack_sent"}
