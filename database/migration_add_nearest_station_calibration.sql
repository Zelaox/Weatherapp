-- Nearest-station spatial fallback: max radius and weighted-average flag.
-- Read at runtime; if key is missing, nearest-station fallback is not applied.

INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    ('nearest_station_max_radius_km', 50.0, 'km', 'Max distance to use a station as fallback for a city without data', 'migration_add_nearest_station_calibration.sql'),
    ('nearest_station_use_weighted_avg', 0, 'bool', '0=use single nearest station; 1=inverse-distance weighted average of stations within radius', 'migration_add_nearest_station_calibration.sql');
