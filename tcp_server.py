# app.py
import os
import asyncio
import logging
import datetime
import math
import json
from typing import Optional, List

from fastapi import FastAPI, HTTPException, UploadFile, File
import asyncpg
import aioredis
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)

# Config (env or defaults)
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://postgres:postgres@localhost:5432/busdb")
REDIS_DSN = os.getenv("REDIS_DSN", "redis://localhost:6379/0")
TCP_HOST = os.getenv("TCP_HOST", "0.0.0.0")
TCP_PORT = int(os.getenv("TCP_PORT", "5023"))
HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))

# Globals
db_pool: asyncpg.Pool = None
redis: aioredis.Redis = None

app = FastAPI(title="Bus Tracking API + TCP Ingest")

# -------------------------
# Utility: haversine
# -------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

# -------------------------
# Pydantic models
# -------------------------
class StopMeta(BaseModel):
    stop_id: Optional[int]
    stop_name: str
    latitude: float
    longitude: float
    stop_order: Optional[int] = 0
    scheduled_time: Optional[int] = None

class RouteUpload(BaseModel):
    route_name: str
    stops: List[StopMeta]

class RegisterBus(BaseModel):
    bus_number: str
    bus_name: Optional[str] = None
    imei: int

# -------------------------
# DB helpers
# -------------------------
async def get_bus_by_imei(conn: asyncpg.Connection, imei: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM bus_data WHERE imei=$1", imei)

async def get_routes_for_bus(conn: asyncpg.Connection, bus_id: int) -> List[asyncpg.Record]:
    return await conn.fetch("SELECT r.* FROM bus_routes br JOIN routes r ON br.route_id = r.route_id WHERE br.bus_id = $1", bus_id)

async def find_nearest_stop_for_bus(conn: asyncpg.Connection, bus_id: int, lat: float, lon: float):
    """
    Find nearest stop among routes assigned to this bus.
    Strategy:
      - get route_ids for bus_id
      - collect candidate stops from route_stops JOIN stop_data
      - compute distances in Python (Haversine), pick min
    """
    rows = await conn.fetch("""
        SELECT rs.stop_id, s.stop_name, s.latitude, s.longitude, rs.stop_order
        FROM bus_routes br
        JOIN route_stops rs ON rs.route_id = br.route_id
        JOIN stop_data s ON s.stop_id = rs.stop_id
        WHERE br.bus_id = $1
    """, bus_id)
    if not rows:
        return None
    min_d = None
    best = None
    for r in rows:
        s_lat = r["latitude"]
        s_lon = r["longitude"]
        d = haversine_km(lat, lon, s_lat, s_lon)
        if (min_d is None) or (d < min_d):
            min_d = d
            best = {
                "stop_id": r["stop_id"],
                "stop_name": r["stop_name"],
                "latitude": s_lat,
                "longitude": s_lon,
                "stop_order": r["stop_order"],
                "distance_km": round(d, 4)
            }
    return best

async def upsert_current_stop(conn: asyncpg.Connection, imei: int, bus_number: str, stop: dict):
    await conn.execute("""
        INSERT INTO current_stop (imei, stop_id, stop_name, bus_number, last_updated)
        VALUES ($1,$2,$3,$4,NOW())
        ON CONFLICT (imei) DO UPDATE SET
          stop_id = EXCLUDED.stop_id,
          stop_name = EXCLUDED.stop_name,
          bus_number = EXCLUDED.bus_number,
          last_updated = EXCLUDED.last_updated
    """, imei, stop["stop_id"], stop["stop_name"], bus_number)

async def insert_gps(conn: asyncpg.Connection, imei: int, lat: float, lon: float, speed: Optional[int], ts: datetime.datetime):
    await conn.execute("""
        INSERT INTO gps_data (imei, latitude, longitude, speed, last_updated)
        VALUES ($1,$2,$3,$4,$5)
    """, imei, lat, lon, speed, ts)

# -------------------------
# Redis helpers
# -------------------------
async def save_current_stop_redis(bus_number: str, stop: dict):
    if not redis:
        return
    key = f"bus:{bus_number}:current_stop"
    await redis.set(key, json.dumps(stop), ex=120)

async def get_current_stop_redis(bus_number: str):
    if not redis:
        return None
    raw = await redis.get(f"bus:{bus_number}:current_stop")
    if not raw:
        return None
    return json.loads(raw)

# -------------------------
# GT06 helpers (frame parsing) - UPDATED/ROBUST
# -------------------------
def crc_itu(data: bytes) -> int:
    """
    ITU CRC-16 used by many GT06 devices.
    """
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0x8408
            else:
                crc >>= 1
    crc ^= 0xFFFF
    return crc & 0xFFFF

def decode_imei(bcd: bytes) -> str:
    """
    Decode BCD-encoded IMEI bytes into string (preserves leading zeros).
    """
    return ''.join(f"{(b >> 4) & 0x0F}{b & 0x0F}" for b in bcd).lstrip("0")

def decode_time(data: bytes) -> datetime.datetime:
    """
    Decode GT06-like timestamp: YY MM DD hh mm ss -> UTC datetime.
    Fallback to UTC now if invalid.
    """
    if len(data) != 6:
        return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    try:
        year = 2000 + int(data[0])
        month = int(data[1])
        day = int(data[2])
        hour = int(data[3])
        minute = int(data[4])
        second = int(data[5])
        return datetime.datetime(year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc)
    except Exception:
        return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

# -------------------------
# TCP handler (per-connection) - UPDATED GT06 logic
# -------------------------
active_connections = {}  # addr -> imei
logged_in_devices = {}   # addr -> True

async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    logging.info("TCP connected: %s", addr)
    client_imei = None
    try:
        while True:
            # read frame start (with timeout to avoid stuck connections)
            try:
                start = await asyncio.wait_for(reader.readexactly(2), timeout=60)
            except asyncio.TimeoutError:
                logging.debug("[%s] read timeout, keeping connection alive", addr)
                continue
            except asyncio.IncompleteReadError:
                logging.info("[%s] connection closed by peer", addr)
                break

            if start != b"\x78\x78":
                logging.warning("[%s] invalid start bytes: %s", addr, start.hex())
                # attempt to resync by continuing loop
                continue

            # read length byte
            try:
                length_b = await reader.readexactly(1)
            except asyncio.IncompleteReadError:
                logging.info("[%s] incomplete read for length", addr)
                break
            length = length_b[0]
            if length <= 0 or length > 255:
                logging.warning("[%s] suspicious length %s - skipping", addr, length)
                # try to read and discard length bytes if reasonable
                try:
                    if length > 0:
                        await reader.readexactly(length)
                        await reader.readexactly(2)
                except Exception:
                    pass
                continue

            # read packet (length bytes) and trailing CRLF
            try:
                packet = await reader.readexactly(length)
                tail = await reader.readexactly(2)
            except asyncio.IncompleteReadError:
                logging.info("[%s] incomplete packet read", addr)
                break

            if tail != b"\x0d\x0a":
                logging.warning("[%s] invalid tail %s", addr, tail.hex())
                continue

            # verify packet size and CRC
            if len(packet) < 4:
                logging.warning("[%s] packet too short: %s", addr, packet.hex())
                continue

            # recv CRC is last 2 bytes of packet
            recv_crc = int.from_bytes(packet[-2:], "big")
            # calculate CRC on (length byte + packet without CRC)
            calc_crc = crc_itu(length_b + packet[:-2])
            if calc_crc != recv_crc:
                logging.warning("[%s] CRC mismatch calc=%04X recv=%04X", addr, calc_crc, recv_crc)
                continue

            proto = packet[0]
            serial = packet[-4:-2] if len(packet) >= 4 else b'\x00\x00'
            data_content = packet[1:-4] if len(packet) >= 5 else b''

            logging.debug("[%s] proto=0x%02X serial=%s data_len=%d", addr, proto, serial.hex(), len(data_content))

            # --------- LOGIN (0x01) ----------
            if proto == 0x01:
                # login packet contains IMEI usually as BCD in first 8 bytes of data_content
                if client_imei is None and len(data_content) >= 8:
                    try:
                        imei_str = decode_imei(data_content[:8])
                        # prefer string IMEI to avoid losing leading zeros; cast to int only if desired
                        client_imei = int(imei_str) if imei_str.isdigit() else imei_str
                        active_connections[addr] = client_imei
                        logged_in_devices[addr] = True
                        logging.info("[%s] LOGIN imei=%s", addr, client_imei)
                    except Exception as e:
                        logging.exception("[%s] failed decode IMEI: %s", addr, e)

            # --------- LOCATION (0x12) ----------
            elif proto == 0x12:
                # many GT06 variants: first 6 bytes timestamp, then other fields; ensure length
                if len(data_content) >= 16:
                    imei = client_imei or active_connections.get(addr)
                    if not imei:
                        logging.warning("[%s] location frame but no imei associated", addr)
                    else:
                        try:
                            ts = decode_time(data_content[0:6])
                            # offsets for lat/lon in many GT06: 7:11 and 11:15
                            lat_raw = int.from_bytes(data_content[7:11], "big", signed=False)
                            lon_raw = int.from_bytes(data_content[11:15], "big", signed=False)
                            lat = lat_raw / 1800000.0
                            lon = lon_raw / 1800000.0
                            speed = int(data_content[15]) if len(data_content) > 15 else None
                        except Exception as e:
                            logging.exception("[%s] failed to parse location payload: %s", addr, e)
                            continue

                        logging.info("[%s] LOCATION imei=%s time=%s lat=%.6f lon=%.6f speed=%s",
                                     addr, imei, ts.isoformat(), lat, lon, speed)

                        # persist GPS & find nearest stop
                        try:
                            async with db_pool.acquire() as conn:
                                await insert_gps(conn, imei, lat, lon, speed, ts)

                                bus = await get_bus_by_imei(conn, imei)
                                if not bus:
                                    logging.debug("[%s] imei %s not registered to a bus", addr, imei)
                                else:
                                    bus_id = bus["id"]
                                    bus_number = bus["bus_number"]
                                    nearest = await find_nearest_stop_for_bus(conn, bus_id, lat, lon)
                                    if nearest:
                                        await save_current_stop_redis(bus_number, nearest)
                                        await upsert_current_stop(conn, imei, bus_number, nearest)
                        except Exception as e:
                            logging.exception("[%s] DB/nearest-stop error: %s", addr, e)

            # --------- HEARTBEAT (0x13) ----------
            elif proto == 0x13:
                if len(data_content) >= 5:
                    try:
                        flags = data_content[0]
                        battery = data_content[1]
                        gsm = data_content[2]
                        alarm = int.from_bytes(data_content[3:5], "big")
                        logging.info("[%s] HEARTBEAT imei=%s flags=0x%02X batt=%s gsm=%s alarm=0x%04X",
                                     addr, client_imei, flags, battery, gsm, alarm)
                    except Exception:
                        logging.debug("[%s] malformed heartbeat payload", addr)

            else:
                logging.debug("[%s] unhandled proto 0x%02X", addr, proto)

            # ---------- send ACK ----------
            try:
                ack = bytearray(b"\x78\x78")
                ack.append(0x05)         # length for ACK packet body
                ack.append(proto)        # protocol type to acknowledge
                ack += serial            # serial number from packet
                ack_crc = crc_itu(ack[2:])   # CRC calculation excludes initial 0x7878
                ack += ack_crc.to_bytes(2, "big")
                ack += b"\x0d\x0a"
                writer.write(ack)
                await writer.drain()
            except Exception:
                logging.exception("[%s] failed to send ACK", addr)

    except asyncio.IncompleteReadError:
        logging.info("[%s] TCP disconnected", addr)
    except Exception as e:
        logging.exception("[%s] TCP handler error: %s", addr, e)
    finally:
        active_connections.pop(addr, None)
        logged_in_devices.pop(addr, None)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logging.info("[%s] connection cleanup done", addr)

# -------------------------
# Background: history writer snapshots current_stop -> bus_history
# -------------------------
async def history_snapshot_task():
    while True:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch("SELECT imei, stop_id, stop_name, bus_number FROM current_stop")
                for r in rows:
                    await conn.execute("""
                        INSERT INTO bus_history (imei, bus_number, stop_id, stop_name, lat, lon, distance_km, captured_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
                    """, r["imei"], r["bus_number"], r["stop_id"], r["stop_name"],
                         None, None, None)  # lat/lon/distance_KM can be filled if stored in current_stop
        except Exception as e:
            logging.exception("history task error: %s", e)
        await asyncio.sleep(60)

# -------------------------
# REST endpoints (unchanged)
# -------------------------
@app.post("/register_bus")
async def register_bus(r: RegisterBus):
    async with db_pool.acquire() as conn:
        # upsert bus_data
        await conn.execute("""
            INSERT INTO bus_data (bus_number, bus_name, imei)
            VALUES ($1,$2,$3)
            ON CONFLICT (imei) DO UPDATE SET bus_number = EXCLUDED.bus_number, bus_name = EXCLUDED.bus_name
        """, r.bus_number, r.bus_name, r.imei)
    return {"ok": True}

@app.post("/upload_route")
async def upload_route(route: RouteUpload):
    async with db_pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            # insert route
            rec = await conn.fetchrow("INSERT INTO routes (route_name) VALUES ($1) RETURNING route_id", route.route_name)
            route_id = rec["route_id"]
            # insert stops (deduplicate)
            for s in route.stops:
                stop = await conn.fetchrow("""
                    INSERT INTO stop_data (stop_name, latitude, longitude)
                    VALUES ($1,$2,$3)
                    ON CONFLICT (stop_name, latitude, longitude) DO NOTHING
                    RETURNING stop_id
                """, s.stop_name, s.latitude, s.longitude)
                if stop:
                    stop_id = stop["stop_id"]
                else:
                    # find existing
                    ex = await conn.fetchrow("SELECT stop_id FROM stop_data WHERE stop_name=$1 AND latitude=$2 AND longitude=$3", s.stop_name, s.latitude, s.longitude)
                    stop_id = ex["stop_id"]
                await conn.execute("""
                    INSERT INTO route_stops (route_id, stop_id, stop_order, scheduled_time)
                    VALUES ($1,$2,$3,$4)
                """, route_id, stop_id, s.stop_order or 0, s.scheduled_time)
            await tx.commit()
            return {"ok": True, "route_id": route_id}
        except Exception as e:
            await tx.rollback()
            logging.exception("upload_route failed")
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/stops/route/{route_id}")
async def get_stops_for_route(route_id: int):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.stop_id, s.stop_name, s.latitude, s.longitude, rs.stop_order, rs.scheduled_time
            FROM route_stops rs JOIN stop_data s ON s.stop_id = rs.stop_id
            WHERE rs.route_id = $1 ORDER BY rs.stop_order
        """, route_id)
        return [dict(r) for r in rows]

@app.get("/current_stop/by_bus/{bus_number}")
async def get_current_by_bus(bus_number: str):
    # try redis first
    r = await get_current_stop_redis(bus_number)
    if r:
        return {"bus_number": bus_number, "current_stop": r}
    # fallback to DB
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM current_stop WHERE bus_number = $1", bus_number)
        if not row:
            raise HTTPException(status_code=404, detail="No data")
        return dict(row)

# -------------------------
# Startup/shutdown (unchanged)
# -------------------------
@app.on_event("startup")
async def startup():
    global db_pool, redis
    db_pool = await asyncpg.create_pool(dsn=POSTGRES_DSN, min_size=2, max_size=10)
    redis = await aioredis.from_url(REDIS_DSN, decode_responses=True)
    # start TCP server and history task
    # start_server returns a Server object; we wrap in a task
    asyncio.create_task(asyncio.start_server(handle_connection, TCP_HOST, TCP_PORT))
    asyncio.create_task(history_snapshot_task())
    logging.info("Started TCP server and background tasks")

@app.on_event("shutdown")
async def shutdown():
    global db_pool, redis
    await db_pool.close()
    await redis.close()
