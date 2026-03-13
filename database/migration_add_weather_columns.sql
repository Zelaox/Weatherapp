-- Migration: Add additional weather columns to weather_data table
-- These columns are used by Open-Meteo and other providers

-- Add measurement_timestamp column (for pollutant measurement times)
ALTER TABLE weather_data ADD COLUMN measurement_timestamp DATETIME;

-- Add solar/radiation columns (from Open-Meteo)
ALTER TABLE weather_data ADD COLUMN uv_index REAL;
ALTER TABLE weather_data ADD COLUMN solar_radiation REAL;
ALTER TABLE weather_data ADD COLUMN direct_radiation REAL;
ALTER TABLE weather_data ADD COLUMN diffuse_radiation REAL;
ALTER TABLE weather_data ADD COLUMN sunshine_duration REAL;

-- Add weather prediction columns (from Open-Meteo)
ALTER TABLE weather_data ADD COLUMN cape REAL;
ALTER TABLE weather_data ADD COLUMN precipitation_probability REAL;
ALTER TABLE weather_data ADD COLUMN convective_precipitation REAL;
