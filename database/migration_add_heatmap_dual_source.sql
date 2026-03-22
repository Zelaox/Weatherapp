-- Dual PM2.5 heatmap: data_source_priority, min_points_render (pre-IDW point count), data_quality_weights.
-- Recreate station_observation_latest with ROW_NUMBER() by measurement time (not MAX(id)).
-- Add heatmap_confidence_feature data_quality_type + renormalize weights; normalization_profile for identity pass-through.

ALTER TABLE heatmap_interpolation_config ADD COLUMN data_source_priority TEXT NOT NULL DEFAULT '["raw_latest","aggregated_24h"]';
ALTER TABLE heatmap_interpolation_config ADD COLUMN min_points_render INTEGER NOT NULL DEFAULT 3;
ALTER TABLE heatmap_interpolation_config ADD COLUMN data_quality_weights TEXT NOT NULL DEFAULT '{"raw_latest":0.85,"aggregated_24h":1.0}';

UPDATE heatmap_interpolation_config
SET
    data_source_priority = '["raw_latest","aggregated_24h"]',
    min_points_render = 3,
    data_quality_weights = '{"raw_latest":0.85,"aggregated_24h":1.0}'
WHERE context_key = 'pm25_heatmap';

DROP VIEW IF EXISTS station_observation_latest;
CREATE VIEW station_observation_latest AS
SELECT
    ranked.observation_id AS observation_id,
    ranked.city_id AS city_id,
    ranked.latitude AS latitude,
    ranked.longitude AS longitude,
    ranked.parameter_name AS parameter_name,
    ranked.value AS value,
    ranked.measurement_timestamp AS measurement_timestamp,
    ranked.collector_timestamp AS collector_timestamp
FROM (
    SELECT
        w.id AS observation_id,
        c.id AS city_id,
        c.latitude AS latitude,
        c.longitude AS longitude,
        'pm25' AS parameter_name,
        w.pm25 AS value,
        COALESCE(w.measurement_timestamp, w.timestamp) AS measurement_timestamp,
        w.timestamp AS collector_timestamp,
        ROW_NUMBER() OVER (
            PARTITION BY w.city_id
            ORDER BY datetime(COALESCE(w.measurement_timestamp, w.timestamp)) DESC, w.id DESC
        ) AS rn
    FROM weather_data w
    JOIN cities c ON c.id = w.city_id
    WHERE w.pm25 IS NOT NULL
) ranked
WHERE ranked.rn = 1;

INSERT OR IGNORE INTO normalization_profile (profile_key, mode, p_low, p_high, history_days, fixed_min, fixed_max)
VALUES ('heatmap_conf_data_quality', 'identity', NULL, NULL, NULL, NULL, NULL);

UPDATE heatmap_confidence_feature SET weight = 0.2625
WHERE context_key = 'pm25_heatmap' AND feature_key = 'cell_n_points';
UPDATE heatmap_confidence_feature SET weight = 0.2625
WHERE context_key = 'pm25_heatmap' AND feature_key = 'cell_mean_distance_km';
UPDATE heatmap_confidence_feature SET weight = 0.2625
WHERE context_key = 'pm25_heatmap' AND feature_key = 'cell_spatial_density';

INSERT OR IGNORE INTO heatmap_confidence_feature
    (context_key, feature_key, weight, profile_key, enabled, sort_order)
VALUES
    ('pm25_heatmap', 'data_quality_type', 0.2125, 'heatmap_conf_data_quality', 1, 4);
