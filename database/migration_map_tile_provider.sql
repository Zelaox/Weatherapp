-- Single-row basemap provider contract (URL + attribution + UA + zoom/subdomains).
-- Operator must replace user_agent contact placeholder before production OSM use.

CREATE TABLE IF NOT EXISTS map_tile_provider (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    url_template TEXT NOT NULL,
    attribution_html TEXT NOT NULL,
    subdomains TEXT,
    min_zoom INTEGER,
    max_zoom INTEGER,
    user_agent TEXT NOT NULL
);

INSERT OR REPLACE INTO map_tile_provider (
    id,
    url_template,
    attribution_html,
    subdomains,
    min_zoom,
    max_zoom,
    user_agent
) VALUES (
    1,
    'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    'abc',
    NULL,
    19,
    'WeatherApp/1.0 (replace-with-your-contact-email)'
);
