-- Migration: Create lightning_events table
-- This table stores lightning strike events with location, intensity, and timing

CREATE TABLE IF NOT EXISTS lightning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    intensity REAL,
    distance_km REAL,
    city_id INTEGER,
    source TEXT,
    FOREIGN KEY (city_id) REFERENCES cities(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_lightning_events_timestamp ON lightning_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_lightning_events_city ON lightning_events(city_id);
CREATE INDEX IF NOT EXISTS idx_lightning_events_location ON lightning_events(latitude, longitude);
