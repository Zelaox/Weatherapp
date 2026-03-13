-- Map and heatmap extent: DB-driven geographic bounds (no hardcoded coordinates in code).
-- Default: Sweden (approximate bbox). Can be changed in DB for other regions.

INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    ('map_extent_lat_min', 55.3,  'degrees', 'Map/heatmap southern latitude bound', 'migration_add_map_extent.sql'),
    ('map_extent_lat_max', 69.1,  'degrees', 'Map/heatmap northern latitude bound', 'migration_add_map_extent.sql'),
    ('map_extent_lon_min', 11.0,  'degrees', 'Map/heatmap western longitude bound',  'migration_add_map_extent.sql'),
    ('map_extent_lon_max', 24.2,  'degrees', 'Map/heatmap eastern longitude bound',  'migration_add_map_extent.sql');
