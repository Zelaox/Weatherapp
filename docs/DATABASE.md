# Database, parameter registry & related flows

Single entry point for **SQLite schema**, **`parameter_registry` metadata**, **math-layer contracts** (normalization, composites, CAPE, heatmap confidence tables/keys), and **wind-speed handling**. For **map runtime behaviour** (Leaflet sequencing, payload field meanings), see [ANALYTICAL_MAP.md](ANALYTICAL_MAP.md). For the settings dialog, see [SETTINGS.md](SETTINGS.md).

---

## 1. Database overview

- **Engine:** SQLite (local file, e.g. `weather.db`).
- **Core tables:** `cities`, `weather_data`, `daily_stats`, `sensor`-related tables, `calibration_parameters`, `parameter_registry`, `normalization_profile`, `composite_index_definition`, `cape_piecewise_segment`, `variable_family`, `variable_family_member`, etc.
- **Raw pollutants:** PM2.5, PM10, NO₂, O₃ in µg/m³ where applicable.
- **Extended `weather_data` columns (nullable REAL):** `wind_direction`, `pressure`, `precipitation`, `cloud_cover`, `visibility`, `dew_point`, `feels_like`, `heat_index`, `wind_chill`, `co`, `so2`, `nh3`, `bc` — added by migration when `cloud_cover` is missing; Open-Meteo `current=` requests include `weather`, `solar`, and `air_quality` registry rows with `provider_mappings.openmeteo`. Values are merged into the provider result dict, converted via `utils/unit_conversion.py` (e.g. visibility m→km). If Open-Meteo returns HTTP 400 for an unknown variable, adjust or remove that parameter’s `openmeteo` mapping in `parameter_registry`.
- **Deduplication:** Uses measurement timestamps from providers where available.
- **Migrations:** Applied from `database/migration_*.sql` and logic in `database/db_manager.py` (`_run_migration_if_needed`).

---

## 2. Parameter registry (source of truth)

### Context

- `parameter_registry` (plus `variable_family` / `variable_family_member` and validated `backfill_support` JSON) is the **source of truth** for which parameters exist, how they map to providers, and how Open-Meteo hourly variables are **grouped** per endpoint profile.
- `weather_data` is a **projection** (storage columns). Migrations should add columns in line with registry metadata.
- `_auto_discover_parameters_from_schema` in `database/db_manager.py` is **REPAIR MODE** only: it inserts minimal rows when a `weather_data` column exists without a registry row. It does not define the system.

### Decisions

- `backfill_support` is validated against `database/schemas/backfill_support.schema.json` (strict JSON, `additionalProperties: false`). Helpers: `utils/backfill_support_validation.py`.
- Hourly Open-Meteo requests are built from the DB (`variable_family_member` + `parameter_registry.variable_family_key`), not hardcoded comma-lists in Python. Shared logic: `providers/openmeteo_hourly_groups.py`.
- `DatabaseManager.validate_registry_schema_sync()` reports drift between `weather_data` columns and registry rows (see also `tests/test_parameter_registry_sync.py`).

### Consequences

- Provider and backfill code must read grouping from the DB; changes to compatible hourly bundles are done via migrations/seeds.
- Invalid `backfill_support` in the DB is rejected or logged; fix data instead of adding silent fallbacks in code.

### Key files

| Area | Path |
|------|------|
| Migrations / init | `database/db_manager.py`, `database/migration_add_parameter_registry*.sql`, `migration_add_parameter_registry_metadata_v2.sql` |
| JSON Schema | `database/schemas/backfill_support.schema.json` |
| Hourly grouping | `providers/openmeteo_hourly_groups.py`, `providers/openmeteo_provider.py`, `tools/backfill_history.py` |
| ADR (this section supersedes the old standalone ADR file) | *was* `docs/ADR_parameter_registry.md` |

---

## 2b. Math layer (normalization, composites, CAPE, heatmap confidence)

### `normalization_profile` + `parameter_registry.normalization_profile_id`

- One row per named profile (e.g. `winsor_p5_p95_default`). Modes: `winsorized_percentile`, `fixed_domain`, `identity`.
- Each `parameter_registry` row references a profile via `normalization_profile_id` (seeded to default winsor 5/95 to match prior call-site literals).
- Runtime normalization uses `analytics/normalization_engine.py` (`NormalizationEngine`) — **no** implicit 5/95 in analytics code; missing FK fails loud.
- **Profile-by-key:** `NormalizationEngine.normalize_by_profile_key(profile_key, value)` loads a row by `normalization_profile.profile_key` (no `parameter_registry` row). Used for heatmap confidence components: `heatmap_conf_station_count`, `heatmap_conf_coverage_fraction`, `heatmap_conf_mean_distance_km` (seeded in `migration_map_init_and_data_quality.sql`).

### Normalization coverage diagnostics

- `DatabaseManager.get_normalization_readiness_report()` returns per-parameter `usable` | `unstable` | `unusable` with explicit `reasons` (e.g. `missing_normalization_profile`, `insufficient_samples_for_winsor`, `constant_winsor_bounds`, `low_sample_count`). Parameters in `parameter_registry` that are **not** columns on `weather_data` are reported as `unusable` with `no_weather_data_column` (winsor path skipped — avoids invalid SQL and log spam).
- Minimum winsor sample gate for diagnostics aligns with `normalization_winsor_min_samples` in `calibration_parameters` (default 20), consistent with `get_parameter_winsorized_bounds`.
- The map payload exposes a slim summary as `normalization_readiness`; the full structure is included under `map_debug.normalization_readiness_full` when app `debug_mode` is on.

### `composite_index_definition`

- `index_key` (e.g. `solar_index`) + `config_json` validated against `database/schemas/composite_index_v1.schema.json` (whitelist `combine`, `inputs`, `transforms`; `additionalProperties: false`).
- Helpers: `utils/composite_index_validation.py`, `analytics/solar_composite.py`.

### `cape_piecewise_segment`

- Ordered segments: `lower_bound_jkg`, `upper_bound_jkg` (NULL = unbounded above), `storm_risk_factor`, `display_suffix_sv`.
- `DatabaseManager.get_cape_storm_risk_factor` / `get_cape_display_suffix_sv` — single source for `analytics/storm_risk.py` and `gui/panels/storm_panel.py`.

### Heatmap confidence (calibration keys + visual mapping)

**Gating thresholds** (station count + coverage fraction): `migration_add_heatmap_confidence_calibration.sql`

- `heatmap_confidence_low_min_stations`, `heatmap_confidence_unreliable_min_stations`
- `heatmap_confidence_low_max_coverage_fraction`, `heatmap_confidence_unreliable_max_coverage_fraction`

**Weighted score model** (`migration_map_init_and_data_quality.sql`)

- `heatmap_confidence_w_station`, `heatmap_confidence_w_coverage`, `heatmap_confidence_w_distance` (must sum to 1.0 within tolerance)
- `heatmap_confidence_score_unreliable_below`, `heatmap_confidence_score_low_below` (score bands; must satisfy unreliable < low)
- `heatmap_confidence_formula_version` (numeric contract version in payload)
- `map_init_size_ready_timeout_ms` → injected as `map_init_timeout_ms` for Leaflet init contract
- `normalization_winsor_min_samples` → diagnostics gate for winsor readiness reporting

**Visual mapping table:** `heatmap_confidence_visual_mapping`

| Column | Role |
|--------|------|
| `confidence_level` | `ok` \| `low` \| `unreliable` (primary key) |
| `heatmap_opacity_multiplier` | Multiplies user heatmap base opacity in JS (dimming) |
| `badge_style_key` | Stable key for styling class |
| `badge_label_sv` | Swedish label for banner + badge |

Map payload includes `heatmap_confidence`, `heatmap_confidence_visual`, and `normalization_readiness`; optional `map_debug` when app `debug_mode` is on — **no** per-row trace persisted in `analytical_indices` by default.

### Heatmap interpolation engine (DB-driven PM2.5 grid + per-cell confidence)

Migration: `database/migration_add_heatmap_interpolation_engine.sql` (runs after `calibration_parameters` exists). JSON columns are validated at startup via `DatabaseManager.validate_heatmap_engine_config()` (fail loud when `heatmap_interpolation_config` exists but JSON is invalid).

**Dual PM2.5 source (raw latest vs 24h own-city aggregate):** `database/migration_add_heatmap_dual_source.sql` (runs when `heatmap_interpolation_config` exists but `data_source_priority` is missing). Adds:

| Column | Role |
|--------|------|
| `data_source_priority` | JSON array, validated by `heatmap_data_source_priority.schema.json`: tokens `raw_latest`, `aggregated_24h` only — **order = priority** (first match wins; no silent fallback). |
| `min_points_render` | Minimum **count of heatmap input points before IDW** (`len(heatmap_input_points)`); not grid cells. Below threshold: no IDW grid, `warning_codes` includes `insufficient_data_density`. |
| `data_quality_weights` | JSON object, validated by `heatmap_data_quality_weights.schema.json`: numeric weights per source for per-cell `data_quality_type` confidence feature. |

**Policy A (heatmap):** `aggregated_24h` uses **only** own-city 24h rolling mean (`get_rolling_average`); spatial nearest from `get_parameter_for_city_or_nearest` is **not** used for heatmap aggregation. Map markers/UI may still use nearest for `pm25_24h` display.

| Object | Role |
|--------|------|
| `heatmap_interpolation_config` | One row per `context_key` (e.g. `pm25_heatmap`): grid bounds (`grid_resolution_min/max`, `bbox_padding_fraction`), IDW/radius, `spatial_index_rules`, `method_selection_rules`, `float_precision_mode`, `global_score_clipping`, optional `radius_shrink_spec`, plus dual-source columns above. |
| `heatmap_confidence_feature` | Per-cell feature weights + `profile_key` for `NormalizationEngine` (includes optional `data_quality_type` → `heatmap_conf_data_quality` identity profile after dual migration). |
| `heatmap_confidence_aggregate` | Global combine weights (`global_combine_w_*`), `cell_score_aggregation_method`, `low_cell_score_threshold`. |
| `heatmap_confidence_threshold` | `score_unreliable_below`, `score_low_below` (overrides calibration score bands when present). |
| `heatmap_render_debug` | Optional sampled cells when `heatmap_debug_sample_cells` > 0 and `debug_mode`; TTL via `heatmap_debug_retention_days`. |
| `station_observation_latest` | VIEW: **one row per city** — latest `pm25` by `COALESCE(measurement_timestamp, timestamp)` (window `ROW_NUMBER`), plus `collector_timestamp` (`weather_data.timestamp`). |

Schemas: `database/schemas/heatmap_method_selection_rules.schema.json`, `heatmap_spatial_index_rules.schema.json`, `heatmap_radius_shrink_spec.schema.json`, `heatmap_global_score_clip.schema.json`, `heatmap_data_source_priority.schema.json`, `heatmap_data_quality_weights.schema.json`.

Runtime: `analytics/heatmap_interpolation.py` (`compute_pm25_heatmap` takes `heatmap_input_points` = list of `selected_pm25` dicts) — built in `MapDataBuilder.build()`.

### `map_tile_provider` (basemap / OSM policy)

Single row (`id = 1`) keeps **URL template and attribution as one logical record** (must match provider ToS).

| Column | Role |
|--------|------|
| `url_template` | Leaflet tile URL template (e.g. OSM or third-party) |
| `attribution_html` | Leaflet `attribution` HTML — **must match** the tile provider |
| `subdomains` | Optional `{s}` subdomains (e.g. `abc`) |
| `min_zoom` / `max_zoom` | Optional INTEGER Leaflet zoom bounds |
| `user_agent` | Full HTTP User-Agent for `QWebEngineProfile` (OSM requires identifiable UA) |

- Migration: `database/migration_map_tile_provider.sql`.
- `DatabaseManager.validate_map_tile_contract()` runs after migration: if `url_template` points at OSM hosts, `attribution_html` must reference OpenStreetMap (fail loud).
- `get_map_tile_provider_for_payload()` supplies `PAYLOAD.map_tile` for Leaflet (JSON-escaped with the rest of the payload).

### Key files

| Area | Path |
|------|------|
| Migrations | `database/migration_add_normalization_profile.sql`, `migration_add_composite_index_definition.sql`, `migration_add_cape_piecewise.sql`, `migration_add_heatmap_confidence_calibration.sql`, `migration_map_init_and_data_quality.sql`, `migration_add_heatmap_interpolation_engine.sql`, `migration_map_tile_provider.sql` |
| Schemas | `database/schemas/normalization_profile.schema.json`, `database/schemas/composite_index_v1.schema.json`, `heatmap_*` rules/shrink/clip schemas |
| Local map HTTP | `utils/local_map_server.py` (singleton `127.0.0.1` document server for Referer) |
| Tests | `tests/test_math_layer.py`, `tests/test_map_init_and_confidence.py`, `tests/test_map_tile_provider.py`, `tests/test_heatmap_interpolation_unit.py` |

---

## 3. Wind speed flow (end-to-end)

This section replaces the former `docs/TECH_NOTE_WIND_FLOW.md`. It documents how wind speed is handled so unit invariants (storage and display in **m/s**) are preserved.

### Data path

1. **Provider**  
   - **Open-Meteo:** `wind_speed_10m` from `current` (km/h by API default).  
   - **OpenWeather:** `wind.speed` (m/s).

2. **Conversion**  
   - `utils/unit_conversion.py`: `convert_parameter_unit(db, "wind_speed", raw_value, provider_name)`.  
   - Target unit from `parameter_registry.unit` (m/s).  
   - Source: Open-Meteo = km/h → m/s (÷3.6); OpenWeather = m/s → no conversion.

3. **Storage**  
   - Provider sets `result["wind_speed"]` to the converted value.  
   - `DatabaseManager.add_weather_data(wind_speed=...)` expects m/s; validation (e.g. 0–50 m/s) and logging if high.

4. **GUI**  
   - “Vind (medel)” comes from the **latest row** per city (`get_latest_weather` / `get_all_latest_weather`). No time averaging.

5. **Analytics**  
   - `get_all_cities_averages('latest')` uses the same latest row per city.  
   - High-wind warning uses `calibration_parameters.wind_speed_warning_threshold_mps` (default 15 m/s).

6. **Historical fix**  
   - `tools/fix_wind_units.py`: for rows with `wind_speed > wind_speed_migration_threshold_mps` (from calibration, default 20), re-interprets value as provider source unit and overwrites with converted m/s.  
   - Run only when old data was stored in the wrong unit.

### GUI vs external source (e.g. SMHI)

- We use Open-Meteo **mean** wind at 10 m, not gusts.  
- **Units:** km/h → m/s once; no double conversion.  
- **GUI:** latest row per city, not a time average.  
- Grid model values can differ from station observations; use `tools/wind_snapshot.py` / `tools/debug_wind_speed.py` to compare DB vs expectations.

### Calibration parameters

| Key | Default | Purpose |
|-----|--------|---------|
| `wind_speed_warning_threshold_mps` | 15 | Analytics warning when any city’s latest wind exceeds this (m/s). |
| `wind_speed_migration_threshold_mps` | 20 | Migration script only adjusts rows above this (assumed wrong unit). |

Thresholds live in `calibration_parameters`, not hardcoded per city.
