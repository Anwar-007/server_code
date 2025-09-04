# app/schemas.py

from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field, condecimal, constr
from datetime import datetime

# -----------------------
# Constrained Types
# -----------------------
Latitude = condecimal(gt=-90, lt=90, decimal_places=8)
Longitude = condecimal(gt=-180, lt=180, decimal_places=8)
UUIDStr = constr(min_length=1)


# -----------------------
# Stop Data
# -----------------------
class StopBase(BaseModel):
    stop_name: str = Field(..., min_length=1)
    latitude: Latitude
    longitude: Longitude


class StopCreate(StopBase):
    id: Optional[UUIDStr] = None


class StopOut(StopBase):
    id: UUIDStr

    class Config:
        orm_mode = True


# -----------------------
# Bus User
# -----------------------
class BusUserBase(BaseModel):
    bus_number: str
    IMEI: Optional[str] = None


class BusUserCreate(BusUserBase):
    id: Optional[UUIDStr] = None


class BusUserOut(BusUserBase):
    id: UUIDStr

    class Config:
        orm_mode = True


# -----------------------
# Routes
# -----------------------
class RouteBase(BaseModel):
    start_point: str
    end_point: str
    start_time_approx: Optional[str] = None  # ISO string or JSON
    end_time_approx: Optional[str] = None


class RouteCreate(RouteBase):
    id: Optional[UUIDStr] = None
    bus_id: UUIDStr


class RouteOut(RouteBase):
    id: UUIDStr
    bus_id: UUIDStr

    class Config:
        orm_mode = True


# -----------------------
# GPS Data
# -----------------------
class GPSDataBase(BaseModel):
    latitude: Latitude
    longitude: Longitude
    speed: Optional[int] = None
    last_updated: datetime


class GPSDataCreate(GPSDataBase):
    id: Optional[UUIDStr] = None
    bus_id: UUIDStr
    route_id: UUIDStr


class GPSDataOut(GPSDataBase):
    id: UUIDStr
    bus_id: UUIDStr
    route_id: UUIDStr

    class Config:
        orm_mode = True


# -----------------------
# Route Stops
# -----------------------
class RouteStopBase(BaseModel):
    approx_time: Optional[str] = None  # ISO string or JSON


class RouteStopCreate(RouteStopBase):
    id: Optional[UUIDStr] = None
    stop_id: UUIDStr
    route_id: UUIDStr
    bus_id: UUIDStr


class RouteStopOut(RouteStopBase):
    id: UUIDStr
    stop_id: UUIDStr
    route_id: UUIDStr
    bus_id: UUIDStr

    class Config:
        orm_mode = True


# -----------------------
# Complex Schemas (API)
# -----------------------
class RegisterBus(BusUserBase):
    """Payload for /register_bus"""
    pass


class RouteStopUpload(StopBase):
    scheduled_time: Optional[str] = None  # when uploading routes


class RouteUpload(RouteBase):
    bus_id: UUIDStr
    stops: List[RouteStopUpload]


class GPSIngest(BaseModel):
    imei: str
    latitude: Latitude
    longitude: Longitude
    speed: Optional[int] = None
    timestamp: datetime


class CurrentStopOut(BaseModel):
    bus_id: UUIDStr
    route_id: UUIDStr
    stop_id: UUIDStr
    stop_name: str
    eta: Optional[str] = None
