# app/tcp_server.py
"""
Production-ready GT06 TCP ingestion server.

Features:
- Full GT06 frame parsing (headers 0x7878 / 0x7979)
- CRC (ITU) validation
- Login (0x01), Location (0x12), Heartbeat (0x13), Status (0x15), Alarm (0x16)
- Async DB lookup for IMEI -> bus_id mapping
- Writes latest GPS snapshot to Redis (fast API reads)
- Enqueues raw GPS payload into Redis list 'analytics:gps' for downstream ingestion
- Optionally triggers Celery analytics tasks (analyze_gps_data, push_current_stop)
"""

import asyncio
import socket
import logging
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import aioredis
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import async_session_maker
from app.models import BusUser
from app.tasks.analytics import analyze_gps_data   # Celery task (analytics)
from app.tasks.current_stop import push_current_stop  # Celery task (current stop push)

# Configure module logger
logger = logging.getLogger("tcp_server")
logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Globals
TIME_TOLERANCE = 5  # seconds
_active_connections: Dict[str, str] = {}            # peer_str -> imei
_logged_in_devices: Dict[str, bool] = {}            # peer_str -> bool
_last_save_timestamps: Dict[str, datetime] = {}     # imei -> last timestamp saved

_redis: Optional[aioredis.Redis] = None


# ---------------------------
# GT06 helpers
# ---------------------------
def crc_itu(data: bytes) -> int:
    """ITU CRC-16 (used by many GT06 implementations)."""
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
    """Decode 8-byte BCD IMEI to string, preserving leading zeros."""
    out = []
    for b in bcd:
        out.append(str((b >> 4) & 0x0F))
        out.append(str(b & 0x0F))
    imei = "".join(out).lstrip("0")
    # If lstrip removed all digits (rare), return raw digits
    return imei or "".join(out)


def decode_timestamp(b: bytes) -> datetime:
    """
    Decode 6-byte GT06-like timestamp (YY MM DD hh mm ss).
    Returns timezone-aware UTC datetime.
    """
    if len(b) != 6:
        return datetime.now(timezone.utc)
    year = 2000 + int(b[0])
    month = int(b[1])
    day = int(b[2])
    hour = int(b[3])
    minute = int(b[4])
    second = int(b[5])
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def bytes_to_coord(coord_bytes: bytes) -> float:
    """
    Convert 4-byte coordinate to degrees.
    Many GT06 devices send coordinates as integer value = degrees*1800000
    """
    if len(coord_bytes) != 4:
        raise ValueError("coord_bytes must be 4 bytes")
    raw = int.from_bytes(coord_bytes, "big", signed=False)
    return raw / 1800000.0


# ---------------------------
# Redis helpers
# ---------------------------
async def init_redis() -> None:
    global _redis
    if _redis is not None:
        return
    _redis = await aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    logger.info("Connected to Redis")


async def set_current_snapshot(bus_id: str, payload: Dict[str, Any], expire: int = 120) -> None:
    """
    Store latest GPS snapshot for fast API access.
    Key: gps_current:{bus_id}
    """
    if _redis is None:
        await init_redis()
    key = f"gps_current:{bus_id}"
    await _redis.set(key, json.dumps(payload), ex=expire)


async def enqueue_analytics_payload(payload: Dict[str, Any]) -> None:
    """
    Push raw GPS payload into analytics queue (Redis list).
    Worker/celery should consume from 'analytics:gps'.
    """
    if _redis is None:
        await init_redis()
    await _redis.lpush("analytics:gps", json.dumps(payload))


# ---------------------------
# DB helper: lookup bus by IMEI
# ---------------------------
async def lookup_bus_by_imei(imei: str) -> Optional[Dict[str, str]]:
    """
    Async DB lookup to get bus id and bus_number for given IMEI.
    Returns dict {'id': str, 'bus_number': str} or None.
    """
    async with async_session_maker() as session:  # type: AsyncSession
        try:
            q = await session.execute(select(BusUser).where(BusUser.IMEI == imei))
            bus = q.scalars().first()
            if not bus:
                return None
            return {"id": str(bus.id), "bus_number": bus.bus_number}
        except Exception:
            logger.exception("DB error in lookup_bus_by_imei")
            return None


# ---------------------------
# Main connection handler
# ---------------------------
async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    sock = writer.get_extra_info("socket")
    peer_str = f"{peer[0]}:{peer[1]}" if peer else "unknown"
    client_imei: Optional[str] = None

    # socket keepalive
    if sock:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            logger.debug("Could not set keepalive on socket")

    logger.info(f"[{peer_str}] Connected")

    try:
        # ensure redis initialized
        await init_redis()

        while True:
            # Read start bytes (2)
            try:
                start = await asyncio.wait_for(reader.readexactly(2), timeout=60)
            except asyncio.TimeoutError:
                logger.debug(f"[{peer_str}] read timeout - keepalive")
                continue
            except asyncio.IncompleteReadError:
                logger.info(f"[{peer_str}] connection closed by peer")
                break

            # Accept 0x78 0x78 and 0x79 0x79 (variants)
            if start not in (b"\x78\x78", b"\x79\x79"):
                logger.warning(f"[{peer_str}] invalid start bytes: {start.hex()} - discarding")
                # try to resync by continuing
                continue

            # read length
            try:
                length_b = await reader.readexactly(1)
            except asyncio.IncompleteReadError:
                logger.info(f"[{peer_str}] incomplete read for length")
                break
            length = length_b[0]
            if length == 0 or length > 255:
                logger.warning(f"[{peer_str}] suspicious length {length}")
                # try to drain and continue
                try:
                    if length > 0:
                        await reader.readexactly(length)
                        await reader.readexactly(2)
                except Exception:
                    pass
                continue

            # read packet + tail
            try:
                packet = await reader.readexactly(length)
                tail = await reader.readexactly(2)
            except asyncio.IncompleteReadError:
                logger.info(f"[{peer_str}] incomplete packet read")
                break

            if tail != b"\x0d\x0a":
                logger.warning(f"[{peer_str}] invalid tail bytes: {tail.hex()}")
                continue

            # minimal packet size check
            if len(packet) < 4:
                logger.warning(f"[{peer_str}] packet too short: {packet.hex()}")
                continue

            # CRC verification
            try:
                recv_crc = int.from_bytes(packet[-2:], "big")
                calc_crc = crc_itu(length_b + packet[:-2])
                if calc_crc != recv_crc:
                    logger.warning(f"[{peer_str}] CRC mismatch calc={calc_crc:04X} recv={recv_crc:04X}")
                    continue
            except Exception:
                logger.exception(f"[{peer_str}] CRC check failure")
                continue

            proto = packet[0]
            serial = packet[-4:-2]
            serial_num = int.from_bytes(serial, "big")
            data_content = packet[1:-4]  # excludes proto and serial+crc

            logger.debug(f"[{peer_str}] proto=0x{proto:02X} serial={serial_num:04X} data_len={len(data_content)}")

            # -----------------
            # LOGIN (0x01)
            # -----------------
            if proto == 0x01:
                if len(data_content) >= 8:
                    try:
                        imei_raw = decode_imei(data_content[:8])
                        client_imei = imei_raw
                        _active_connections[peer_str] = client_imei
                        _logged_in_devices[peer_str] = True
                        logger.info(f"[{peer_str}] LOGIN imei={client_imei}")
                    except Exception:
                        logger.exception(f"[{peer_str}] failed to decode IMEI")

            # -----------------
            # LOCATION (0x12)
            # -----------------
            elif proto == 0x12:
                if len(data_content) >= 16:
                    imei = client_imei or _active_connections.get(peer_str)
                    if not imei:
                        logger.warning(f"[{peer_str}] Location packet with no IMEI associated")
                    else:
                        try:
                            ts = decode_timestamp(data_content[0:6])  # timezone-aware UTC
                            # coordinate offsets: many GT06 send lat at 7:11, lon at 11:15
                            if len(data_content) >= 15:
                                lat = bytes_to_coord(data_content[7:11])
                                lon = bytes_to_coord(data_content[11:15])
                            else:
                                logger.warning(f"[{peer_str}] location payload too short for coordinates")
                                continue

                            speed = int(data_content[15]) if len(data_content) > 15 else None

                            # Deduplicate by timestamp tolerance
                            last_ts = _last_save_timestamps.get(imei)
                            if last_ts and abs((ts - last_ts).total_seconds()) < TIME_TOLERANCE:
                                logger.debug(f"[{peer_str}] duplicate GPS skipped (imei={imei})")
                            else:
                                _last_save_timestamps[imei] = ts

                                # async DB lookup for bus by IMEI
                                bus_row = await lookup_bus_by_imei(imei)
                                if not bus_row:
                                    logger.warning(f"[{peer_str}] IMEI {imei} not found in DB (register device first)")
                                else:
                                    bus_id = bus_row["id"]

                                    # Find active route_id is left to downstream workers; set None here if unknown
                                    route_id = None

                                    gps_payload = {
                                        "imei": imei,
                                        "bus_id": bus_id,
                                        "route_id": route_id,
                                        "latitude": lat,
                                        "longitude": lon,
                                        "speed": speed,
                                        "timestamp": ts.isoformat(),
                                        "peer": peer_str,
                                    }

                                    # store lightweight snapshot in Redis for fast API reads
                                    try:
                                        await set_current_snapshot(bus_id, gps_payload, expire=120)
                                    except Exception:
                                        logger.exception(f"[{peer_str}] failed to set snapshot in Redis")

                                    # enqueue raw gps for analytics ingestion
                                    try:
                                        await enqueue_analytics_payload(gps_payload)
                                    except Exception:
                                        logger.exception(f"[{peer_str}] failed to enqueue analytics payload into Redis")

                                    # Optionally trigger celery analytics tasks immediately (non-blocking)
                                    try:
                                        # analyze_gps_data expects (bus_id, route_id)
                                        analyze_gps_data.delay(bus_id, route_id)
                                        push_current_stop.delay(bus_id, route_id)
                                    except Exception:
                                        # Celery might be temporarily unavailable — it's OK, the Redis queue still has the payload
                                        logger.exception(f"[{peer_str}] failed to enqueue Celery tasks; relying on Redis queue")

                                    logger.info(
                                        f"[{peer_str}] LOCATION imei={imei} time={ts.isoformat()} lat={lat:.6f} lon={lon:.6f} speed={speed}"
                                    )

                        except Exception:
                            logger.exception(f"[{peer_str}] failed to parse location payload")

            # -----------------
            # HEARTBEAT (0x13)
            # -----------------
            elif proto == 0x13:
                if len(data_content) >= 5:
                    try:
                        flags = data_content[0]
                        battery = data_content[1]
                        gsm = data_content[2]
                        alarm = int.from_bytes(data_content[3:5], "big")
                        logger.info(
                            f"[{peer_str}] HEARTBEAT imei={client_imei or _active_connections.get(peer_str)} flags=0x{flags:02X} batt={battery} gsm={gsm} alarm=0x{alarm:04X}"
                        )
                    except Exception:
                        logger.debug(f"[{peer_str}] malformed heartbeat payload")

            # -----------------
            # STATUS / ALARM
            # -----------------
            elif proto == 0x15:
                logger.info(f"[{peer_str}] STATUS payload: {data_content.hex()}")
            elif proto == 0x16:
                logger.warning(f"[{peer_str}] ALARM payload: {data_content.hex()}")

            else:
                logger.debug(f"[{peer_str}] Unhandled proto=0x{proto:02X} payload={data_content.hex()}")

            # -----------------
            # Send ACK
            # -----------------
            try:
                ack = bytearray(b"\x78\x78")
                ack.append(0x05)
                ack.append(proto)
                ack += serial
                ack_crc = crc_itu(ack[2:])  # CRC over length+body
                ack += ack_crc.to_bytes(2, "big")
                ack += b"\x0d\x0a"
                writer.write(ack)
                await writer.drain()
            except Exception:
                logger.exception(f"[{peer_str}] failed to send ACK")

    except asyncio.IncompleteReadError:
        logger.info(f"[{peer_str}] connection closed")
    except Exception:
        logger.exception(f"[{peer_str}] unexpected error in client handler")
    finally:
        _active_connections.pop(peer_str, None)
        _logged_in_devices.pop(peer_str, None)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info(f"[{peer_str}] disconnected")


# ---------------------------
# Server Entrypoint
# ---------------------------
async def start_server(host: str = None, port: int = None) -> None:
    host = host or settings.TCP_HOST
    port = port or settings.TCP_PORT
    logger.info(f"Starting GT06 TCP server on {host}:{port}")
    server = await asyncio.start_server(handle_client, host, port)
    async with server:
        await server.serve_forever()


# Allow running as script
if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.info("TCP server stopped by KeyboardInterrupt")
