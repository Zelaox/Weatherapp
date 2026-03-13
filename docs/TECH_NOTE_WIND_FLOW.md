# Wind speed flow (end-to-end)

This note documents how wind speed is handled so future changes do not break the unit invariant (storage and display in m/s).

## Data path

1. **Provider**  
   - **Open-Meteo**: `wind_speed_10m` from `current` (km/h by API default).  
   - **OpenWeather**: `wind.speed` (m/s).

2. **Conversion**  
   - `utils/unit_conversion.py`: `convert_parameter_unit(db, "wind_speed", raw_value, provider_name)`.  
   - Target unit from `parameter_registry.unit` (m/s).  
   - Source: Open-Meteo = km/h → m/s (÷3.6); OpenWeather = m/s → no conversion.

3. **Storage**  
   - Provider sets `result["wind_speed"]` to the converted value.  
   - `DatabaseManager.add_weather_data(wind_speed=...)` expects m/s; no further conversion, only validation (0–50 m/s) and logging if >20 m/s.

4. **GUI**  
   - "Vind (medel)" comes from the **latest row** per city: `get_latest_weather(city_id)` / `get_all_latest_weather()`.  
   - No averaging over time; it is the single latest `weather_data.wind_speed` for that city.

5. **Analytics**  
   - `get_all_cities_averages('latest')` uses the same latest row per city.  
   - High-wind warning uses `calibration_parameters.wind_speed_warning_threshold_mps` (default 15 m/s).

6. **Historical fix**  
   - `tools/fix_wind_units.py`: for rows with `wind_speed > wind_speed_migration_threshold_mps` (from calibration, default 20), re-interprets value as provider source unit and overwrites with converted m/s.  
   - Only run when you know old data was stored in wrong unit; do not lower threshold so much that valid m/s (e.g. 18 m/s in storm) gets double-converted.

## Root cause (GUI vs external source)

If the GUI shows e.g. 18 m/s while an external source (e.g. SMHI/yr) shows ~6 m/s for the same city:

- **Provider field**: We use Open-Meteo `wind_speed_10m` (mean wind at 10 m), not gusts. Correct.
- **Units**: Open-Meteo returns km/h; we convert to m/s once and store. No double conversion.
- **Aggregation**: GUI shows the **latest row** per city, not a time average. No wrong aggregate.
- **Conclusion**: The stored value (e.g. 18.4 m/s) is the model output for that grid point (≈66 km/h). Model grid values often differ from station observations; no code bug. Use `tools/wind_snapshot.py` to compare DB vs external sources.

## Validation

- **Snapshot**: `python tools/wind_snapshot.py` prints latest wind_speed per city (same source as GUI). Compare with external sources (e.g. SMHI/yr).  
- **Debug**: `python tools/debug_wind_speed.py` for DB stats and high-wind samples.  
- Model (Open-Meteo) grid values can differ from station observations; differences of several m/s are possible.

## Calibration parameters

| Key | Default | Purpose |
|-----|--------|--------|
| `wind_speed_warning_threshold_mps` | 15 | Analytics warning when any city’s latest wind_speed exceeds this (m/s). |
| `wind_speed_migration_threshold_mps` | 20 | Migration script only adjusts rows with wind_speed above this (assumed wrongly stored unit). |

No per-city or hardcoded wind logic; all thresholds are in `calibration_parameters`.
