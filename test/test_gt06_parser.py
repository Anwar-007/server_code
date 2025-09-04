import binascii
import datetime
import pytest

from app.tcp_server import crc_itu, decode_timestamp

# ✅ Sample GT06 login packet (hex string from real logs)
SAMPLE_LOGIN_PACKET = "78781101035889905143749800001f8d0d0a"

# ✅ Sample GT06 location packet
SAMPLE_LOCATION_PACKET = (
    "78781f12150a1f101020c7025a8f0c0527a5fb0079000467"
    "001f8e0d0a"
)

def hex_to_bytes(hex_str: str) -> bytes:
    return binascii.unhexlify(hex_str)

def test_crc_validation():
    """Ensure CRC check passes on a known GT06 packet"""
    data = hex_to_bytes(SAMPLE_LOGIN_PACKET)
    length = data[2]
    packet = data[3 : 3 + length]
    recv_crc = int.from_bytes(packet[-2:], "big")
    calc_crc = crc_itu(data[2 : -4])  # adjust if your code slices differently
    assert recv_crc == calc_crc, f"CRC mismatch: {recv_crc} != {calc_crc}"

def test_decode_timestamp():
    """Decode GT06 timestamp from sample location packet"""
    data = hex_to_bytes(SAMPLE_LOCATION_PACKET)
    # Skip start(2) + length(1) + proto(1), then take 6 bytes timestamp
    timestamp_bytes = data[4:10]
    ts = decode_timestamp(timestamp_bytes)
    assert isinstance(ts, datetime.datetime)
    assert 2000 <= ts.year <= 2100  # sanity check
    assert 1 <= ts.month <= 12

def test_parse_location_lat_lon():
    """Extract latitude/longitude from GT06 location packet"""
    data = hex_to_bytes(SAMPLE_LOCATION_PACKET)
    lat_bytes = data[11:15]
    lon_bytes = data[15:19]

    lat = int.from_bytes(lat_bytes, "big") / 1800000.0
    lon = int.from_bytes(lon_bytes, "big") / 1800000.0

    # sanity checks
    assert -90 <= lat <= 90
    assert -180 <= lon <= 180
