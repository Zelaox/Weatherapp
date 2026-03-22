-- variable_family: Open-Meteo hourly groups per endpoint_profile (DB-driven).
-- parameter_registry.variable_family_key is added via ALTER in db_manager (logical key, same for forecast/archive).

CREATE TABLE IF NOT EXISTS variable_family (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_profile TEXT NOT NULL CHECK (endpoint_profile IN ('forecast-api', 'archive-api')),
    family_key TEXT NOT NULL,
    description TEXT,
    UNIQUE (endpoint_profile, family_key)
);

CREATE TABLE IF NOT EXISTS variable_family_member (
    family_id INTEGER NOT NULL REFERENCES variable_family (id) ON DELETE CASCADE,
    hourly_api_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    PRIMARY KEY (family_id, hourly_api_name)
);

CREATE INDEX IF NOT EXISTS idx_variable_family_endpoint ON variable_family (endpoint_profile);

-- One Open-Meteo hourly variable per family avoids invalid combined hourly= strings (400 from API).
INSERT OR IGNORE INTO variable_family (endpoint_profile, family_key, description) VALUES
('forecast-api', 'storm_cape', 'CAPE only — single hourly variable per request'),
('forecast-api', 'storm_precipitation_probability', 'precipitation_probability only'),
('forecast-api', 'storm_convective_precipitation', 'convective_precipitation only'),
('archive-api', 'storm_cape', 'CAPE only — archive hourly'),
('archive-api', 'storm_precipitation_probability', 'precipitation_probability only — archive'),
('archive-api', 'storm_convective_precipitation', 'convective_precipitation only — archive');

INSERT OR IGNORE INTO variable_family_member (family_id, hourly_api_name, sort_order)
SELECT vf.id, 'cape', 0 FROM variable_family vf WHERE vf.endpoint_profile = 'forecast-api' AND vf.family_key = 'storm_cape';
INSERT OR IGNORE INTO variable_family_member (family_id, hourly_api_name, sort_order)
SELECT vf.id, 'precipitation_probability', 0 FROM variable_family vf WHERE vf.endpoint_profile = 'forecast-api' AND vf.family_key = 'storm_precipitation_probability';
INSERT OR IGNORE INTO variable_family_member (family_id, hourly_api_name, sort_order)
SELECT vf.id, 'convective_precipitation', 0 FROM variable_family vf WHERE vf.endpoint_profile = 'forecast-api' AND vf.family_key = 'storm_convective_precipitation';

INSERT OR IGNORE INTO variable_family_member (family_id, hourly_api_name, sort_order)
SELECT vf.id, 'cape', 0 FROM variable_family vf WHERE vf.endpoint_profile = 'archive-api' AND vf.family_key = 'storm_cape';
INSERT OR IGNORE INTO variable_family_member (family_id, hourly_api_name, sort_order)
SELECT vf.id, 'precipitation_probability', 0 FROM variable_family vf WHERE vf.endpoint_profile = 'archive-api' AND vf.family_key = 'storm_precipitation_probability';
INSERT OR IGNORE INTO variable_family_member (family_id, hourly_api_name, sort_order)
SELECT vf.id, 'convective_precipitation', 0 FROM variable_family vf WHERE vf.endpoint_profile = 'archive-api' AND vf.family_key = 'storm_convective_precipitation';
