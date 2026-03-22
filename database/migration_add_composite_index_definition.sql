-- Composite index definitions (validated in app against composite_index_v1.schema.json).

CREATE TABLE IF NOT EXISTS composite_index_definition (
    index_key TEXT PRIMARY KEY NOT NULL,
    config_json TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- solar_index: weighted_linear; weights match prior calibration defaults (must be present in DB, not code).
INSERT OR REPLACE INTO composite_index_definition (index_key, config_json) VALUES (
    'solar_index',
    '{"schema_version":"composite_index_v1","combine":"weighted_linear","inputs":[{"parameter_name":"solar_radiation","temporal_class":"instantaneous","weight":0.5},{"parameter_name":"uv_index","temporal_class":"instantaneous","weight":0.3},{"parameter_name":"sunshine_duration","temporal_class":"accumulated_interval","weight":0.2}],"transforms":{"solar_radiation":"none","uv_index":"none","sunshine_duration":"none"}}'
);
