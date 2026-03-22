-- DB-driven heatmap interpolation + per-cell confidence (see docs/ANALYTICAL_MAP.md).
-- Fail-loud: application validates JSON columns at startup.

CREATE TABLE IF NOT EXISTS heatmap_interpolation_config (
    context_key TEXT NOT NULL PRIMARY KEY,
    interpolation_method TEXT NOT NULL DEFAULT 'idw',
    adaptive_radius_enabled INTEGER NOT NULL DEFAULT 0 CHECK (adaptive_radius_enabled IN (0, 1)),
    min_points INTEGER NOT NULL DEFAULT 3,
    radius_min_km REAL NOT NULL DEFAULT 20.0,
    radius_max_km REAL,
    radius_step_km REAL NOT NULL DEFAULT 15.0,
    density_scaling_factor REAL NOT NULL DEFAULT 1.0,
    idw_power REAL,
    grid_resolution_min INTEGER NOT NULL DEFAULT 80,
    grid_resolution_max INTEGER NOT NULL DEFAULT 150,
    bbox_padding_fraction REAL NOT NULL DEFAULT 0.05,
    heatmap_engine_config_version INTEGER NOT NULL DEFAULT 1,
    config_schema_version INTEGER NOT NULL DEFAULT 1,
    scoring_reference_mode TEXT NOT NULL DEFAULT 'relative_to_render'
        CHECK (scoring_reference_mode IN ('relative_to_render', 'absolute_stable')),
    density_mode TEXT NOT NULL DEFAULT 'radius_based'
        CHECK (density_mode IN ('cell_based', 'radius_based')),
    cell_area_method TEXT DEFAULT 'haversine'
        CHECK (cell_area_method IN ('haversine', 'planar_approx')),
    temporal_freshness_time_basis TEXT NOT NULL DEFAULT 'measurement_time'
        CHECK (temporal_freshness_time_basis IN ('measurement_time', 'collector_time')),
    spatial_index_mode TEXT NOT NULL DEFAULT 'brute_force'
        CHECK (spatial_index_mode IN ('brute_force', 'kd_tree', 'grid_bucket')),
    spatial_index_rules TEXT,
    method_selection_rules TEXT,
    global_aggregation_method TEXT NOT NULL DEFAULT 'mean'
        CHECK (global_aggregation_method IN ('mean', 'median', 'p50', 'p75')),
    global_score_clipping TEXT,
    float_precision_mode TEXT NOT NULL DEFAULT 'raw'
        CHECK (float_precision_mode IN ('raw', 'rounded_6dp')),
    radius_shrink_spec TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS heatmap_confidence_feature (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_key TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    weight REAL NOT NULL,
    profile_key TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE (context_key, feature_key),
    FOREIGN KEY (context_key) REFERENCES heatmap_interpolation_config(context_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS heatmap_confidence_aggregate (
    context_key TEXT NOT NULL PRIMARY KEY,
    cell_score_aggregation_method TEXT NOT NULL DEFAULT 'mean'
        CHECK (cell_score_aggregation_method IN ('mean', 'median', 'p50', 'p75')),
    global_combine_w_mean_cell REAL NOT NULL DEFAULT 0.5,
    global_combine_w_coverage REAL NOT NULL DEFAULT 0.3,
    global_combine_w_low_cell_ratio REAL NOT NULL DEFAULT 0.2,
    low_cell_score_threshold REAL NOT NULL DEFAULT 0.35,
    clip_cell_scores_before_aggregate INTEGER NOT NULL DEFAULT 0 CHECK (clip_cell_scores_before_aggregate IN (0, 1)),
    clip_spec TEXT,
    FOREIGN KEY (context_key) REFERENCES heatmap_interpolation_config(context_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS heatmap_confidence_threshold (
    context_key TEXT NOT NULL PRIMARY KEY,
    score_unreliable_below REAL NOT NULL,
    score_low_below REAL NOT NULL,
    FOREIGN KEY (context_key) REFERENCES heatmap_interpolation_config(context_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS heatmap_render_debug (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    render_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    cell_i INTEGER NOT NULL,
    cell_j INTEGER NOT NULL,
    json_features TEXT NOT NULL,
    cell_score REAL,
    context_key TEXT NOT NULL DEFAULT 'pm25_heatmap'
);

CREATE INDEX IF NOT EXISTS idx_heatmap_render_debug_render ON heatmap_render_debug(render_id);

-- Latest PM2.5 observation per city (for documentation / optional consumers).
CREATE VIEW IF NOT EXISTS station_observation_latest AS
SELECT
    w.id AS observation_id,
    c.id AS city_id,
    c.latitude AS lat,
    c.longitude AS lon,
    'pm25' AS parameter_name,
    w.pm25 AS value,
    COALESCE(w.measurement_timestamp, w.timestamp) AS measurement_timestamp
FROM weather_data w
JOIN cities c ON c.id = w.city_id
JOIN (
    SELECT city_id, MAX(id) AS max_id
    FROM weather_data
    WHERE pm25 IS NOT NULL
    GROUP BY city_id
) t ON t.max_id = w.id AND t.city_id = w.city_id
WHERE w.pm25 IS NOT NULL;

-- Default PM2.5 heatmap context: mirrors previous hardcoded grid [80,150], padding 5%, static max radius from calibration.
INSERT OR IGNORE INTO heatmap_interpolation_config (
    context_key,
    interpolation_method,
    adaptive_radius_enabled,
    min_points,
    radius_min_km,
    radius_max_km,
    radius_step_km,
    idw_power,
    grid_resolution_min,
    grid_resolution_max,
    bbox_padding_fraction,
    heatmap_engine_config_version,
    config_schema_version,
    scoring_reference_mode,
    density_mode,
    cell_area_method,
    temporal_freshness_time_basis,
    spatial_index_mode,
    spatial_index_rules,
    method_selection_rules,
    global_aggregation_method,
    global_score_clipping,
    float_precision_mode,
    radius_shrink_spec,
    enabled
) VALUES (
    'pm25_heatmap',
    'idw',
    0,
    3,
    20.0,
    NULL,
    15.0,
    NULL,
    80,
    150,
    0.05,
    1,
    1,
    'relative_to_render',
    'radius_based',
    'haversine',
    'measurement_time',
    'brute_force',
    '{"schema_version":1,"priority_order":"asc","evaluation_order":"top_down","first_match_wins":true,"rules":[{"rule_priority":0,"when":{},"then":{"mode":"brute_force"}}]}',
    '{"schema_version":1,"priority_order":"asc","evaluation_order":"top_down","first_match_wins":true,"rules":[{"rule_priority":0,"when":{},"then":{"method":"idw"}}]}',
    'mean',
    '{"min":null,"max":1.0}',
    'raw',
    NULL,
    1
);

INSERT OR IGNORE INTO heatmap_confidence_aggregate (
    context_key,
    cell_score_aggregation_method,
    global_combine_w_mean_cell,
    global_combine_w_coverage,
    global_combine_w_low_cell_ratio,
    low_cell_score_threshold,
    clip_cell_scores_before_aggregate,
    clip_spec
) VALUES (
    'pm25_heatmap',
    'mean',
    0.5,
    0.3,
    0.2,
    0.35,
    0,
    NULL
);

INSERT OR IGNORE INTO heatmap_confidence_threshold (
    context_key,
    score_unreliable_below,
    score_low_below
) VALUES (
    'pm25_heatmap',
    0.35,
    0.60
);

-- Normalization profile for spatial density (fixed domain; winsor optional later).
INSERT OR IGNORE INTO normalization_profile (profile_key, mode, p_low, p_high, history_days, fixed_min, fixed_max)
VALUES ('heatmap_cell_spatial_density', 'fixed_domain', NULL, NULL, NULL, 0.0, 5.0);

-- Per-cell feature model: n_points, mean distance, spatial density (see plan §2).
INSERT OR IGNORE INTO heatmap_confidence_feature
    (context_key, feature_key, weight, profile_key, enabled, sort_order)
VALUES
    ('pm25_heatmap', 'cell_n_points', (1.0/3.0), 'heatmap_conf_station_count', 1, 1),
    ('pm25_heatmap', 'cell_mean_distance_km', (1.0/3.0), 'heatmap_conf_mean_distance_km', 1, 2),
    ('pm25_heatmap', 'cell_spatial_density', (1.0/3.0), 'heatmap_cell_spatial_density', 1, 3);

INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    ('heatmap_debug_sample_cells', 0.0, 'count', 'When >0 and debug_mode: persist up to N sampled heatmap cells to heatmap_render_debug', 'migration_add_heatmap_interpolation_engine.sql'),
    ('heatmap_debug_retention_days', 7.0, 'days', 'Delete heatmap_render_debug rows older than this many days', 'migration_add_heatmap_interpolation_engine.sql');
