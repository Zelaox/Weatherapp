-- Migration: Create parameter_registry table and add all pollutants/parameters
-- This table stores metadata about all parameters that can be measured

-- Create parameter_registry table if it doesn't exist
CREATE TABLE IF NOT EXISTS parameter_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parameter_name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    unit TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    min_value REAL,
    max_value REAL,
    variation_threshold REAL,
    variation_mode TEXT DEFAULT 'none',  -- 'none', 'range', 'percentile', 'stddev'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Insert all pollutants and weather parameters
-- Air Quality Pollutants
INSERT OR IGNORE INTO parameter_registry (parameter_name, display_name, unit, category, description, variation_mode) VALUES
('pm25', 'PM2.5', 'µg/m³', 'air_quality', 'Particulate matter 2.5 micrometers or smaller', 'percentile'),
('pm10', 'PM10', 'µg/m³', 'air_quality', 'Particulate matter 10 micrometers or smaller', 'percentile'),
('no2', 'NO₂', 'µg/m³', 'air_quality', 'Nitrogen dioxide', 'percentile'),
('o3', 'O₃', 'µg/m³', 'air_quality', 'Ozone', 'percentile'),
('co', 'CO', 'µg/m³', 'air_quality', 'Carbon monoxide', 'percentile'),
('so2', 'SO₂', 'µg/m³', 'air_quality', 'Sulfur dioxide', 'percentile'),
('nh3', 'NH₃', 'µg/m³', 'air_quality', 'Ammonia', 'percentile'),
('bc', 'Black Carbon', 'µg/m³', 'air_quality', 'Black carbon (soot)', 'percentile');

-- Weather Parameters
INSERT OR IGNORE INTO parameter_registry (parameter_name, display_name, unit, category, description, variation_mode) VALUES
('temperature', 'Temperatur', '°C', 'weather', 'Air temperature', 'range'),
('humidity', 'Luftfuktighet', '%', 'weather', 'Relative humidity', 'range'),
('wind_speed', 'Vindhastighet', 'm/s', 'weather', 'Wind speed', 'range'),
('wind_direction', 'Vindriktning', '°', 'weather', 'Wind direction in degrees', 'range'),
('pressure', 'Lufttryck', 'hPa', 'weather', 'Atmospheric pressure', 'range'),
('precipitation', 'Nederbörd', 'mm', 'weather', 'Precipitation amount', 'range'),
('cloud_cover', 'Molnighet', '%', 'weather', 'Cloud cover percentage', 'range'),
('visibility', 'Sikt', 'km', 'weather', 'Visibility distance', 'range'),
('uv_index', 'UV-index', '', 'weather', 'Ultraviolet index', 'range'),
('dew_point', 'Daggpunkt', '°C', 'weather', 'Dew point temperature', 'range'),
('feels_like', 'Känns som', '°C', 'weather', 'Feels like temperature', 'range'),
('heat_index', 'Värmeindex', '°C', 'weather', 'Heat index', 'range'),
('wind_chill', 'Vindavkylning', '°C', 'weather', 'Wind chill temperature', 'range');

-- Air Quality Index
INSERT OR IGNORE INTO parameter_registry (parameter_name, display_name, unit, category, description, variation_mode) VALUES
('aqi', 'Luftkvalitetsindex', '', 'air_quality', 'Air Quality Index', 'range');

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_parameter_registry_name ON parameter_registry(parameter_name);
CREATE INDEX IF NOT EXISTS idx_parameter_registry_category ON parameter_registry(category);
