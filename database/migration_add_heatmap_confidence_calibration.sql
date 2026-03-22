-- Heatmap / IDW confidence thresholds (DB-driven; no literals in Python).

INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    ('heatmap_confidence_low_min_stations',          3.0, 'count', 'Below this station count: heatmap_confidence level at least low', 'migration_add_heatmap_confidence_calibration.sql'),
    ('heatmap_confidence_unreliable_min_stations',   2.0, 'count', 'Below this station count: heatmap_confidence level unreliable', 'migration_add_heatmap_confidence_calibration.sql'),
    ('heatmap_confidence_low_max_coverage_fraction', 0.35, 'fraction', 'Below this grid coverage fraction: at least low confidence (0-1)', 'migration_add_heatmap_confidence_calibration.sql'),
    ('heatmap_confidence_unreliable_max_coverage_fraction', 0.12, 'fraction', 'Below this grid coverage fraction: unreliable (0-1)', 'migration_add_heatmap_confidence_calibration.sql');
