-- Migration: Add OpenAQ location cache and API usage tracking tables
-- No hardcoding beyond schema itself; behaviour is controlled from application code.

-- Table for caching OpenAQ location ids per city
CREATE TABLE IF NOT EXISTS openaq_locations (
    city_id INTEGER PRIMARY KEY,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    location_id INTEGER NOT NULL,
    last_verified DATETIME NOT NULL,
    FOREIGN KEY (city_id) REFERENCES cities(id) ON DELETE CASCADE
);

-- Table for tracking API usage (generic, per API name)
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api TEXT NOT NULL,
    timestamp DATETIME NOT NULL
);

-- Optional table for DB-driven rate limits per API
CREATE TABLE IF NOT EXISTS api_limits (
    api TEXT PRIMARY KEY,
    max_per_minute INTEGER,
    max_per_hour INTEGER
);

CREATE INDEX IF NOT EXISTS idx_api_usage_api_timestamp ON api_usage(api, timestamp);

