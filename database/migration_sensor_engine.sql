-- Migration: Extend sensors table and create sensor_readings table
-- Idempotent: Check if columns/tables exist before creating

-- Check and add columns to sensors table
-- Note: SQLite doesn't support IF NOT EXISTS for ALTER TABLE ADD COLUMN
-- We'll check in Python code before running these

-- Extend sensors table with new columns
-- These will be checked in Python before execution
ALTER TABLE sensors ADD COLUMN provider_type TEXT;
ALTER TABLE sensors ADD COLUMN config_json TEXT;  -- JSON config for provider
ALTER TABLE sensors ADD COLUMN visibility_mode TEXT DEFAULT 'marker';  -- 'marker' or 'heatmap'
ALTER TABLE sensors ADD COLUMN enabled INTEGER DEFAULT 1;
ALTER TABLE sensors ADD COLUMN interval_seconds INTEGER DEFAULT 600;  -- Per-sensor interval in seconds
ALTER TABLE sensors ADD COLUMN last_error TEXT;  -- Last error message if failed
ALTER TABLE sensors ADD COLUMN error_count INTEGER DEFAULT 0;
ALTER TABLE sensors ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP;

-- Create sensor_readings table for historical data
CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id INTEGER NOT NULL,
    value REAL NOT NULL,
    parameter TEXT,  -- Parameter name from config
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sensor_id) REFERENCES sensors(id) ON DELETE CASCADE
);

-- Create indexes for sensor_readings table
CREATE INDEX IF NOT EXISTS idx_sensor_readings_sensor_timestamp ON sensor_readings(sensor_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_timestamp ON sensor_readings(timestamp);
