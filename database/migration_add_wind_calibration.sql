-- Wind unit and validation calibration (no hardcoded thresholds in code).
-- See docs/DATABASE.md (section 3) for end-to-end wind flow.

INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    ('wind_speed_warning_threshold_mps', 15.0, 'm/s', 'Threshold above which analytics logs "orimligt höga vindhastigheter"', 'migration_add_wind_calibration.sql'),
    ('wind_speed_migration_threshold_mps', 20.0, 'm/s', 'Threshold for fix_wind_units.py: rows with wind_speed above this may be km/h stored as m/s', 'migration_add_wind_calibration.sql');
