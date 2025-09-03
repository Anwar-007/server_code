CREATE EXTENSION IF NOT EXISTS postgis;

-- Raw GPS points table (fast inserts)
CREATE TABLE IF NOT EXISTS gps_data (
  id BIGSERIAL PRIMARY KEY,
  imei TEXT NOT NULL,
  "timestamp" TIMESTAMP NOT NULL,
  lat DOUBLE PRECISION NOT NULL,
  lon DOUBLE PRECISION NOT NULL,
  speed DOUBLE PRECISION,
  geom GEOGRAPHY(Point,4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gps_data_imei_ts ON gps_data (imei, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_gps_data_geom ON gps_data USING GIST (geom);

-- Routes
CREATE TABLE IF NOT EXISTS bus_routes (
  id SERIAL PRIMARY KEY,
  bus_number TEXT UNIQUE NOT NULL,
  route_name TEXT NOT NULL
);

-- Stops (deduplicated by name+coordinates)
CREATE TABLE IF NOT EXISTS bus_stops (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  lat DOUBLE PRECISION NOT NULL,
  lon DOUBLE PRECISION NOT NULL,
  geom GEOGRAPHY(Point,4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon,lat),4326)::geography) STORED
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_bus_stops_name_coords ON bus_stops(name, lat, lon);
CREATE INDEX IF NOT EXISTS idx_bus_stops_geom ON bus_stops USING GIST (geom);

-- Route ↔ Stop (sequence & timediff)
CREATE TABLE IF NOT EXISTS bus_services (
  id SERIAL PRIMARY KEY,
  route_id INTEGER NOT NULL REFERENCES bus_routes(id) ON DELETE CASCADE,
  stop_id  INTEGER NOT NULL REFERENCES bus_stops(id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL,
  timedifference INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_bus_services_route_stop ON bus_services(route_id, stop_id);
CREATE INDEX IF NOT EXISTS idx_bus_services_route_seq ON bus_services(route_id, sequence);

-- IMEI ↔ Bus
CREATE TABLE IF NOT EXISTS bus_devices (
  id SERIAL PRIMARY KEY,
  imei TEXT UNIQUE NOT NULL,
  bus_number TEXT NOT NULL REFERENCES bus_routes(bus_number) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bus_devices_bus_number ON bus_devices(bus_number);

-- History snapshots (Redis → Postgres)
CREATE TABLE IF NOT EXISTS bus_history (
  id BIGSERIAL PRIMARY KEY,
  bus_number TEXT NOT NULL,
  stop_name TEXT NOT NULL,
  lat DOUBLE PRECISION NOT NULL,
  lon DOUBLE PRECISION NOT NULL,
  distance_km DOUBLE PRECISION NOT NULL,
  "timestamp" TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bus_history_bus_ts ON bus_history(bus_number, "timestamp" DESC);
