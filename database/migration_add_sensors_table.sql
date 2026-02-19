-- Migration: Add sensors table
-- Idempotent: Check if table exists before creating

-- Check if sensors table exists
-- If it doesn't exist, create it
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

-- Create indexes if they don't exist
CREATE INDEX IF NOT EXISTS idx_sensors_city ON sensors(city_id);
CREATE INDEX IF NOT EXISTS idx_sensors_sensor_id ON sensors(sensor_id);
