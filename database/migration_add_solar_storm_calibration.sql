-- Migration: Add inversion and IDW calibration parameters
-- Defaults documented in docs/ANALYTICAL_MAP.md

INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    -- Inversion model parameters
    ('inversion_p_low',          5.0,   'percentile',  'Lower winsorization percentile for inversion model',                        'migration_add_solar_storm_calibration.sql'),
    ('inversion_p_high',        95.0,   'percentile',  'Upper winsorization percentile for inversion model',                        'migration_add_solar_storm_calibration.sql'),
    ('inversion_wind_weight',    0.6,   'dimensionless','Wind speed contribution to inversion score (0.0–1.0)',                     'migration_add_solar_storm_calibration.sql'),
    ('inversion_humidity_weight',0.4,   'dimensionless','Humidity contribution to inversion score (0.0–1.0)',                        'migration_add_solar_storm_calibration.sql'),

    -- IDW heatmap parameters
    ('idw_power',                2.3,   'dimensionless','IDW decay exponent — higher values create tighter local hotspots',          'migration_add_solar_storm_calibration.sql'),
    ('idw_max_r_factor',         1.3,   'dimensionless','Factor limiting max radius to prevent distant stations dominating',         'migration_add_solar_storm_calibration.sql'),
    ('idw_scale_percentile',    95.0,   'percentile',  'Colour-scale anchor percentile for IDW heatmap (outlier-robust)',           'migration_add_solar_storm_calibration.sql');
