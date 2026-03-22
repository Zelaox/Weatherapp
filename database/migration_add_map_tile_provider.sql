-- Text calibration store + default map tile provider (schema map_tile_provider_v1).
-- Operator must set user_agent contact and may switch url_template/attribution per provider ToS.

CREATE TABLE IF NOT EXISTS calibration_text_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value_text TEXT NOT NULL,
    description TEXT,
    source TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_calibration_text_parameters_key ON calibration_text_parameters(key);

-- Valid JSON for map_tile_provider_v1.schema.json (single logical provider record).
INSERT OR IGNORE INTO calibration_text_parameters (key, value_text, description, source) VALUES (
    'map_tile_provider',
    '{"schema_version":"map_tile_provider_v1","url_template":"https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png","attribution":"&copy; OpenStreetMap contributors","user_agent":"WeatherApp/1.0 (map tiles; configure contact in DB per OSM tile policy)","subdomains":"abc","min_zoom":0,"max_zoom":19}',
    'Leaflet basemap: url_template + attribution + UA + zoom/subdomains (validated JSON)',
    'migration_add_map_tile_provider.sql'
);

-- Optional: fixed localhost port for map document server (0 = ephemeral bind, default).
INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    ('map_local_server_port', 0.0, 'port', '0 = bind ephemeral port on 127.0.0.1; set to fixed port if policy requires', 'migration_add_map_tile_provider.sql');
