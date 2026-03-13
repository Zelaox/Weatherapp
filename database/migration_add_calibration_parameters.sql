-- Migration: Create calibration_parameters table
-- This table stores configuration parameters for calculations and UI

CREATE TABLE IF NOT EXISTS calibration_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    description TEXT,
    source TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Index for performance
CREATE INDEX IF NOT EXISTS idx_calibration_parameters_key ON calibration_parameters(key);
