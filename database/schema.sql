-- SQLite Database Schema for Weather Application

-- Cities table
CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Weather data table
CREATE TABLE IF NOT EXISTS weather_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL,
    temperature REAL NOT NULL,
    humidity REAL NOT NULL,
    wind_speed REAL NOT NULL,
    aqi REAL,
    pm25 REAL,
    pm10 REAL,
    no2 REAL,
    o3 REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL,
    FOREIGN KEY (city_id) REFERENCES cities(id) ON DELETE CASCADE
);

-- Index for performance on weather_data queries
CREATE INDEX IF NOT EXISTS idx_weather_city_timestamp ON weather_data(city_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_weather_timestamp ON weather_data(timestamp);

-- Daily statistics table
CREATE TABLE IF NOT EXISTS daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE UNIQUE NOT NULL,
    coldest_city_id INTEGER,
    warmest_city_id INTEGER,
    best_air_quality_city_id INTEGER,
    worst_air_quality_city_id INTEGER,
    FOREIGN KEY (coldest_city_id) REFERENCES cities(id),
    FOREIGN KEY (warmest_city_id) REFERENCES cities(id),
    FOREIGN KEY (best_air_quality_city_id) REFERENCES cities(id),
    FOREIGN KEY (worst_air_quality_city_id) REFERENCES cities(id)
);

-- Sensors table
CREATE TABLE IF NOT EXISTS sensors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL,
    sensor_id INTEGER,  -- NULL for custom markers
    parameter TEXT,    -- NULL for custom markers
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    last_value REAL,   -- NULL for custom markers
    last_updated DATETIME,
    is_custom INTEGER DEFAULT 0,
    custom_info TEXT,  -- JSON for custom markers, NULL for OpenAQ sensors
    FOREIGN KEY (city_id) REFERENCES cities(id) ON DELETE CASCADE
);

-- Indexes for sensors table
CREATE INDEX IF NOT EXISTS idx_sensors_city ON sensors(city_id);
CREATE INDEX IF NOT EXISTS idx_sensors_sensor_id ON sensors(sensor_id);