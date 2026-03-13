-- Migration: Create analytical_indices table
-- This table stores computed analytical indices (solar_index, storm_risk, smog_risk) per city

CREATE TABLE IF NOT EXISTS analytical_indices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    solar_index REAL,
    storm_risk REAL,
    smog_risk REAL,
    FOREIGN KEY (city_id) REFERENCES cities(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_analytical_indices_city ON analytical_indices(city_id);
CREATE INDEX IF NOT EXISTS idx_analytical_indices_timestamp ON analytical_indices(timestamp);
CREATE INDEX IF NOT EXISTS idx_analytical_indices_city_timestamp ON analytical_indices(city_id, timestamp);
