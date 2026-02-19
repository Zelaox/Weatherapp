-- Migration: Add pollutant columns to weather_data table
-- Run this migration for existing databases

-- Add new pollutant columns (SQLite allows adding columns that can be NULL)
ALTER TABLE weather_data ADD COLUMN pm25 REAL;
ALTER TABLE weather_data ADD COLUMN pm10 REAL;
ALTER TABLE weather_data ADD COLUMN no2 REAL;
ALTER TABLE weather_data ADD COLUMN o3 REAL;
