from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import BusRoute, BusDevice
from database import SessionLocal
from pydantic import BaseModel

app = FastAPI()

class RegisterBus(BaseModel):
    bus_number: str
    imei: str
    route_name: str

async def get_db():
    async with SessionLocal() as session:
        yield session

@app.post("/register_device")
async def register_device(bus: RegisterBus, db: AsyncSession = Depends(get_db)):
    # Check if route exists
    result = await db.execute(select(BusRoute).where(BusRoute.route_name == bus.route_name))
    route = result.scalars().first()
    if not route:
        return {"error": f"Route {bus.route_name} not found"}

    # Add or update device
    device = BusDevice(imei=bus.imei, bus_number=bus.bus_number)
    db.add(device)
    await db.commit()

    return {"message": f"Bus {bus.bus_number} with IMEI {bus.imei} registered to route {bus.route_name}"}
