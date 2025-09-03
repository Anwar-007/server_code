-- create_tables.sql
BEGIN;

-- gps_data
CREATE TABLE IF NOT EXISTS gps_data (
  id SERIAL PRIMARY KEY,
  imei BIGINT NOT NULL,
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL,
  speed INTEGER,
  last_updated TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gps_data_imei_ts ON gps_data(imei, last_updated DESC);
CREATE INDEX IF NOT EXISTS idx_gps_data_latlon ON gps_data(latitude, longitude);

-- bus_data
CREATE TABLE IF NOT EXISTS bus_data (
  id SERIAL PRIMARY KEY,
  bus_number TEXT UNIQUE NOT NULL,
  bus_name TEXT,
  imei BIGINT UNIQUE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bus_data_imei ON bus_data(imei);
CREATE INDEX IF NOT EXISTS idx_bus_data_bus_number ON bus_data(bus_number);

-- stop_data
CREATE TABLE IF NOT EXISTS stop_data (
  stop_id SERIAL PRIMARY KEY,
  stop_name TEXT NOT NULL,
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_stop_name_coords ON stop_data(stop_name, latitude, longitude);

-- routes
CREATE TABLE IF NOT EXISTS routes (
  route_id SERIAL PRIMARY KEY,
  route_name TEXT NOT NULL
);

-- route_stops
CREATE TABLE IF NOT EXISTS route_stops (
  id SERIAL PRIMARY KEY,
  route_id INTEGER NOT NULL REFERENCES routes(route_id) ON DELETE CASCADE,
  stop_id INTEGER NOT NULL REFERENCES stop_data(stop_id) ON DELETE CASCADE,
  stop_order INTEGER NOT NULL,
  scheduled_time INTEGER
);
CREATE INDEX IF NOT EXISTS idx_route_stops_route_order ON route_stops(route_id, stop_order);

-- bus_routes
CREATE TABLE IF NOT EXISTS bus_routes (
  id SERIAL PRIMARY KEY,
  bus_id INTEGER NOT NULL REFERENCES bus_data(id) ON DELETE CASCADE,
  route_id INTEGER NOT NULL REFERENCES routes(route_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bus_routes_bus ON bus_routes(bus_id);
CREATE INDEX IF NOT EXISTS idx_bus_routes_route ON bus_routes(route_id);

-- current_stop
CREATE TABLE IF NOT EXISTS current_stop (
  imei BIGINT PRIMARY KEY,
  stop_id INTEGER REFERENCES stop_data(stop_id),
  stop_name TEXT,
  bus_number TEXT,
  last_updated TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_current_stop_bus_number ON current_stop(bus_number);

-- history snapshot (optional)
CREATE TABLE IF NOT EXISTS bus_history (
  id SERIAL PRIMARY KEY,
  imei BIGINT,
  bus_number TEXT,
  stop_id INTEGER,
  stop_name TEXT,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  distance_km DOUBLE PRECISION,
  captured_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bus_history_bus_at ON bus_history(imei, captured_at DESC);

COMMIT;
