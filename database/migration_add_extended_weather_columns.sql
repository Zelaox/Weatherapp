-- Extended optional columns on weather_data (nullable REAL).
-- Applied programmatically in DatabaseManager._migrate_extended_weather_columns_if_needed
-- when missing; this file documents the intended schema addition.

-- Columns: wind_direction, pressure, precipitation, cloud_cover, visibility,
-- dew_point, feels_like, heat_index, wind_chill, co, so2, nh3, bc
