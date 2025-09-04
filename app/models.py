# app/models.py

from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class BusUser(Base):
    __tablename__ = "bus_user"

    id = Column(String, primary_key=True, index=True)
    bus_number = Column(String, nullable=False, index=True)
    IMEI = Column(String, unique=True, index=True, nullable=True)

    routes = relationship(
        "Routes", back_populates="bus", cascade="all, delete-orphan"
    )
    gps_records = relationship(
        "GPSData", back_populates="bus", cascade="all, delete-orphan"
    )
    route_stops = relationship(
        "RouteStops", back_populates="bus", cascade="all, delete-orphan"
    )


class Routes(Base):
    __tablename__ = "routes"

    id = Column(String, primary_key=True, index=True)
    bus_id = Column(String, ForeignKey("bus_user.id", ondelete="CASCADE"), nullable=False)
    start_point = Column(String, nullable=False)
    end_point = Column(String, nullable=False)
    start_time_approx = Column(String, nullable=True)  # ISO string or JSON
    end_time_approx = Column(String, nullable=True)    # ISO string or JSON

    bus = relationship("BusUser", back_populates="routes")
    gps_records = relationship(
        "GPSData", back_populates="route", cascade="all, delete-orphan"
    )
    route_stops = relationship(
        "RouteStops", back_populates="route", cascade="all, delete-orphan"
    )


class GPSData(Base):
    __tablename__ = "gps_data"

    id = Column(String, primary_key=True, index=True)
    bus_id = Column(String, ForeignKey("bus_user.id", ondelete="CASCADE"), nullable=False)
    route_id = Column(String, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    speed = Column(Integer, nullable=True)
    last_updated = Column(DateTime, nullable=False)

    bus = relationship("BusUser", back_populates="gps_records")
    route = relationship("Routes", back_populates="gps_records")


class StopData(Base):
    __tablename__ = "stop_data"

    id = Column(String, primary_key=True, index=True)
    stop_name = Column(String, nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    route_stops = relationship(
        "RouteStops", back_populates="stop", cascade="all, delete-orphan"
    )


class RouteStops(Base):
    __tablename__ = "route_stops"

    id = Column(String, primary_key=True, index=True)
    stop_id = Column(String, ForeignKey("stop_data.id", ondelete="CASCADE"), nullable=False)
    route_id = Column(String, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False)
    bus_id = Column(String, ForeignKey("bus_user.id", ondelete="CASCADE"), nullable=False)
    approx_time = Column(String, nullable=True)  # ISO string or JSON

    stop = relationship("StopData", back_populates="route_stops")
    route = relationship("Routes", back_populates="route_stops")
    bus = relationship("BusUser", back_populates="route_stops")
