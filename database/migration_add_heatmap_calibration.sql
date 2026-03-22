-- Migration: Add heatmap (PM2.5) interpolation and visualization calibration
-- All numeric defaults are DB-driven and can be tuned without code changes.
-- See docs/ANALYTICAL_MAP.md and heatmap smoothing plan for semantics.

INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    -- Core IDW / influence shape (PM2.5 heatmap)
    ('heatmap_idw_power',               2.3,   'dimensionless', 'IDW decay exponent for PM2.5 heatmap (overrides idw_power when set)',                      'migration_add_heatmap_calibration.sql'),
    ('heatmap_idw_min_points',          3.0,   'count',         'Minimum number of stations within influence radius required for a valid grid cell',        'migration_add_heatmap_calibration.sql'),
    ('heatmap_max_influence_radius_km', 220.0, 'km',            'Maximum radius (km) where stations contribute to a PM2.5 grid cell; beyond this weight→0', 'migration_add_heatmap_calibration.sql'),

    -- Radial decay and smoothing of the grid
    ('heatmap_radial_decay_type',       1.0,   'enum',          'Radial decay type for PM2.5 heatmap: 0=none, 1=linear, 2=gaussian_like',                  'migration_add_heatmap_calibration.sql'),
    ('heatmap_smoothing_kernel_size',   3.0,   'cells',         'Odd kernel size (grid cells) for NaN-aware smoothing of IDW grid (>=1 = enabled)',       'migration_add_heatmap_calibration.sql'),

    -- Value domain / clipping (PM2.5, µg/m³)
    ('heatmap_clip_min',                0.0,   'µg/m³',         'Lower clip for PM2.5 heatmap values before colour mapping',                               'migration_add_heatmap_calibration.sql'),
    ('heatmap_clip_max',               80.0,   'µg/m³',         'Upper clip for PM2.5 heatmap values before colour mapping',                               'migration_add_heatmap_calibration.sql'),

    -- Optional contour overlay
    ('heatmap_contours_enabled',        0.0,   'bool',          'Enable isoline contours over PM2.5 heatmap (0=off, 1=on)',                                'migration_add_heatmap_calibration.sql'),
    ('heatmap_contours_levels',        50.0,   'string',        'Comma-separated PM2.5 contour levels (µg/m³), e.g. \"5,10,15,25,35,50\"',                 'migration_add_heatmap_calibration.sql'),
    ('heatmap_contours_color',          1.0,   'string',        'Stroke colour for PM2.5 contours (CSS colour, e.g. \"#000000\")',                        'migration_add_heatmap_calibration.sql'),
    ('heatmap_contours_opacity',        0.6,   'fraction',      'Opacity (0–1) for PM2.5 contour lines',                                                   'migration_add_heatmap_calibration.sql');

