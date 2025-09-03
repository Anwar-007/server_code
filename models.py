from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from database import Base
import datetime


class BusRoute(Base):
    __tablename__ = "bus_routes"

    id = Column(Integer, primary_key=True, index=True)
    bus_number = Column(String, index=True, unique=True)
    route_name = Column(String)

    services = relationship("BusService", back_populates="route")
    devices = relationship("BusDevice", back_populates="route")


class BusStop(Base):
    __tablename__ = "bus_stops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    lat = Column(Float)
    lng = Column(Float)

    services = relationship("BusService", back_populates="stop")


class BusService(Base):
    __tablename__ = "bus_services"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("bus_routes.id"))
    stop_id = Column(Integer, ForeignKey("bus_stops.id"))
    sequence = Column(Integer)
    timedifference = Column(Integer)

    route = relationship("BusRoute", back_populates="services")
    stop = relationship("BusStop", back_populates="services")


class BusDevice(Base):
    __tablename__ = "bus_devices"

    id = Column(Integer, primary_key=True, index=True)
    imei = Column(String, unique=True, index=True)
    bus_number = Column(String, ForeignKey("bus_routes.bus_number"))

    route = relationship("BusRoute", back_populates="devices")


class BusHistory(Base):
    __tablename__ = "bus_history"

    id = Column(Integer, primary_key=True, index=True)
    bus_number = Column(String, index=True)
    stop_name = Column(String)
    lat = Column(Float)
    lng = Column(Float)
    distance_km = Column(Float)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
