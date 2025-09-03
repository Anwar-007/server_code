from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from database import SessionLocal
from models import BusRoute, BusStop, BusService, BusDevice
from schemas import RouteUpload, RegisterBus
from redis_client import get_current_stop, init_redis
import asyncio
from history_task import history_writer

app = FastAPI()

async def get_db():
    async with SessionLocal() as session:
        yield session


@app.on_event("startup")
async def startup_event():
    await init_redis()
    asyncio.create_task(history_writer())


@app.post("/upload_route")
async def upload_route(route: RouteUpload, db: AsyncSession = Depends(get_db)):
    # delete if exists
    result = await db.execute(select(BusRoute).where(BusRoute.bus_number == route.bus_number))
    existing = result.scalars().first()
    if existing:
        await db.delete(existing)
        await db.commit()

    new_route = BusRoute(bus_number=route.bus_number, route_name=route.route_name)
    db.add(new_route)
    await db.flush()

    for s in route.stops:
        result = await db.execute(
            select(BusStop).where(BusStop.name == s.name, BusStop.lat == s.lat, BusStop.lng == s.lng)
        )
        stop = result.scalars().first()
        if not stop:
            stop = BusStop(name=s.name, lat=s.lat, lng=s.lng)
            db.add(stop)
            await db.flush()

        service = BusService(
            route_id=new_route.id,
            stop_id=stop.id,
            sequence=s.sequence,
            timedifference=s.timedifference
        )
        db.add(service)

    await db.commit()
    return {"message": f"Route {route.route_name} uploaded with {len(route.stops)} stops"}


@app.post("/register_device")
async def register_device(bus: RegisterBus, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BusRoute).where(BusRoute.bus_number == bus.bus_number))
    route = result.scalars().first()
    if not route:
        return {"error": "Bus route not found"}

    device = BusDevice(imei=bus.imei, bus_number=bus.bus_number)
    db.add(device)
    await db.commit()
    return {"message": f"Bus {bus.bus_number} with IMEI {bus.imei} registered"}


@app.get("/stops/{bus_number}")
async def get_stops(bus_number: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BusRoute).where(BusRoute.bus_number == bus_number))
    route = result.scalars().first()
    if not route:
        return {"error": "Route not found"}

    stops = [
        {
            "sequence": s.sequence,
            "name": s.stop.name,
            "lat": s.stop.lat,
            "lng": s.stop.lng,
            "timedifference": s.timedifference
        }
        for s in sorted(route.services, key=lambda x: x.sequence)
    ]
    return {"bus_number": route.bus_number, "route_name": route.route_name, "stops": stops}


@app.get("/current_stop/{bus_number}")
async def current_stop(bus_number: str):
    stop = await get_current_stop(bus_number)
    if not stop:
        return {"error": "No stop info available"}
    return {"bus_number": bus_number, "current_stop": stop}
