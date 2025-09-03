from pydantic import BaseModel
from typing import List


class StopWithMeta(BaseModel):
    name: str
    lat: float
    lng: float
    sequence: int
    timedifference: int


class RouteUpload(BaseModel):
    bus_number: str
    route_name: str
    stops: List[StopWithMeta]


class RegisterBus(BaseModel):
    bus_number: str
    imei: str
