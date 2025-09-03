import math
from sqlalchemy.future import select
from models import BusRoute

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

async def find_nearest_stop(bus_number: str, lat: float, lon: float, db):
    result = await db.execute(select(BusRoute).where(BusRoute.bus_number == bus_number))
    route = result.scalars().first()
    if not route:
        return None

    nearest = None
    min_dist = float("inf")
    for service in route.services:
        stop = service.stop
        dist = haversine(lat, lon, stop.lat, stop.lng)
        if dist < min_dist:
            min_dist = dist
            nearest = stop

    if nearest:
        return {
            "stop": nearest.name,
            "lat": nearest.lat,
            "lng": nearest.lng,
            "distance_km": round(min_dist, 3)
        }
    return None
