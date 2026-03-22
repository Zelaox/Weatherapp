-- Map init contract, heatmap confidence model weights/score bands, normalization profiles for confidence components,
-- and DB-driven visual mapping (no hardcoded UI opacity paths).

-- Timeout for map container size-ready (ms). Runtime fails loud in JS if exceeded (logged explicitly).
INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    ('map_init_size_ready_timeout_ms', 8000.0, 'ms', 'Max wait for #map non-zero client size before heatmap attach aborts with explicit error', 'migration_map_init_and_data_quality.sql'),
    ('normalization_winsor_min_samples', 20.0, 'count', 'Minimum samples required for winsor bounds; diagnostics use same gate as get_parameter_winsorized_bounds', 'migration_map_init_and_data_quality.sql');

-- Weighted confidence score: w_station*s_station + w_coverage*s_coverage + w_distance*s_distance (each s_* in [0,1] via normalization_profile).
INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    ('heatmap_confidence_w_station',  (1.0/3.0), 'weight', 'Weight for station-count component (must sum with w_coverage + w_distance ≈ 1)', 'migration_map_init_and_data_quality.sql'),
    ('heatmap_confidence_w_coverage', (1.0/3.0), 'weight', 'Weight for grid coverage fraction component', 'migration_map_init_and_data_quality.sql'),
    ('heatmap_confidence_w_distance', (1.0/3.0), 'weight', 'Weight for mean interpolation distance component (inverted: closer stations → higher score)', 'migration_map_init_and_data_quality.sql');

-- Score bands (after gating): below unreliable threshold → unreliable; below low threshold → low; else ok (unless gate already worse).
INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    ('heatmap_confidence_score_unreliable_below', 0.35, 'score', 'Composite score strictly below this → at least unreliable (combined with gate rules)', 'migration_map_init_and_data_quality.sql'),
    ('heatmap_confidence_score_low_below',          0.60, 'score', 'Composite score below this (and above unreliable band) → at least low', 'migration_map_init_and_data_quality.sql'),
    ('heatmap_confidence_formula_version',          1.0, 'version', 'DB contract version for heatmap confidence component model (numeric)', 'migration_map_init_and_data_quality.sql');

-- Normalization profiles for heatmap confidence components (NormalizationEngine.normalize_by_profile_key).
INSERT OR IGNORE INTO normalization_profile (profile_key, mode, p_low, p_high, history_days, fixed_min, fixed_max)
VALUES
    ('heatmap_conf_station_count', 'fixed_domain', NULL, NULL, NULL, 0.0, 30.0),
    ('heatmap_conf_coverage_fraction', 'fixed_domain', NULL, NULL, NULL, 0.0, 1.0),
    ('heatmap_conf_mean_distance_km', 'fixed_domain', NULL, NULL, NULL, 0.0, 250.0);

-- Visual mapping: consumed by Leaflet payload (no literals in JS for opacity multipliers).
CREATE TABLE IF NOT EXISTS heatmap_confidence_visual_mapping (
    confidence_level TEXT NOT NULL PRIMARY KEY CHECK (confidence_level IN ('ok', 'low', 'unreliable')),
    heatmap_opacity_multiplier REAL NOT NULL CHECK (heatmap_opacity_multiplier >= 0.0 AND heatmap_opacity_multiplier <= 1.0),
    badge_style_key TEXT NOT NULL,
    badge_label_sv TEXT NOT NULL DEFAULT ''
);

INSERT OR IGNORE INTO heatmap_confidence_visual_mapping
    (confidence_level, heatmap_opacity_multiplier, badge_style_key, badge_label_sv)
VALUES
    ('ok',         1.0,  'ok',         'Heatmap: god tillförlitlighet'),
    ('low',        0.72, 'low',        'Heatmap: begränsad tillförlitlighet'),
    ('unreliable', 0.48, 'unreliable', 'Heatmap: låg tillförlitlighet');
