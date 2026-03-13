-- Migration: Lägg till provider-specifik metadata för parametrar
-- Detta gör det möjligt att dynamiskt mappa parametrar till API-fält
-- Ingen hardcoding - allt kommer från databas

-- Lägg till provider_mappings kolumn om den inte finns
-- JSON sträng med mappings: {"openmeteo": "shortwave_radiation", "openweather": "uvi", ...}

-- Check if column exists, if not add it
-- SQLite doesn't support IF NOT EXISTS for ALTER TABLE ADD COLUMN, so we use a workaround
-- We'll check in Python code instead

-- Uppdatera befintliga parametrar med mappings (dynamiskt baserat på vad som finns)
-- Solar parameters
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "shortwave_radiation"}' WHERE parameter_name = 'solar_radiation' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "uv_index", "openweather": "uvi"}' WHERE parameter_name = 'uv_index' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "direct_radiation"}' WHERE parameter_name = 'direct_radiation' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "diffuse_radiation"}' WHERE parameter_name = 'diffuse_radiation' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "sunshine_duration"}' WHERE parameter_name = 'sunshine_duration' AND (provider_mappings IS NULL OR provider_mappings = '');

-- Storm parameters
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "cape"}' WHERE parameter_name = 'cape' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "precipitation_probability"}' WHERE parameter_name = 'precipitation_probability' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "convective_precipitation"}' WHERE parameter_name = 'convective_precipitation' AND (provider_mappings IS NULL OR provider_mappings = '');

-- Weather parameters
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "temperature_2m", "openweather": "temp"}' WHERE parameter_name = 'temperature' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "relative_humidity_2m", "openweather": "humidity"}' WHERE parameter_name = 'humidity' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openmeteo": "wind_speed_10m", "openweather": "wind_speed"}' WHERE parameter_name = 'wind_speed' AND (provider_mappings IS NULL OR provider_mappings = '');

-- Pollutant parameters
UPDATE parameter_registry SET provider_mappings = '{"openaq": "pm25", "openweather": "pm2_5"}' WHERE parameter_name = 'pm25' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openaq": "pm10", "openweather": "pm10"}' WHERE parameter_name = 'pm10' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openaq": "no2", "openweather": "no2"}' WHERE parameter_name = 'no2' AND (provider_mappings IS NULL OR provider_mappings = '');
UPDATE parameter_registry SET provider_mappings = '{"openaq": "o3", "openweather": "o3"}' WHERE parameter_name = 'o3' AND (provider_mappings IS NULL OR provider_mappings = '');
