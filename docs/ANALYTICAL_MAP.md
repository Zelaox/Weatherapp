# Analytical Map — Architecture & Model Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Data Flow](#data-flow)
4. [MapDataBuilder](#mapdatabuilder)
5. [Inversion Risk Model](#inversion-risk-model)
6. [Cluster Analysis](#cluster-analysis)
7. [Station Density Map](#station-density-map)
8. [Database Queries](#database-queries)
9. [JavaScript Layer](#javascript-layer)
10. [Configuration Constants](#configuration-constants)
11. [Null Handling Policy](#null-handling-policy)

---

## Overview

The Stations tab renders an analytical Leaflet map that goes beyond simple marker placement. Every visual element is driven by live data computed in Python and injected as a single structured JSON payload into the browser. The JavaScript layer is a pure renderer — it makes no analytical decisions.

**Key properties:**
- All thresholds come from `WarningDetector` — the single source of truth
- All normalization bounds are derived from historical data — no hardcoded physics constants
- All scores are null-safe — missing data produces `null`, never a substituted estimate
- The map is self-calibrating — bounds and regional boundaries update as data accumulates

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  StationsTab._load_map()                                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  MapDataBuilder.build()                                      │
│                                                              │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ get_cities_with  │  │ get_parameter_   │                 │
│  │ _weather_for_map │  │ winsorized_bounds│                 │
│  └────────┬─────────┘  └────────┬─────────┘                 │
│           │                     │                           │
│  ┌────────▼──────────────────────▼─────────────────────┐    │
│  │  Per-city enrichment (A)                             │    │
│  │  AQI colour · 24h trend · inversion score · region  │    │
│  └─────────────────────────┬────────────────────────────┘    │
│                             │                                │
│  ┌──────────────────────────▼───────────────────────────┐    │
│  │  Cluster analysis (B)                                 │    │
│  │  Median-lat split · deviation vs 7d national mean     │    │
│  └─────────────────────────┬────────────────────────────┘    │
│                             │                                │
│  ┌──────────────────────────▼───────────────────────────┐    │
│  │  Station density (D)                                  │    │
│  │  Neighbour count within 2° box · low_density flag     │    │
│  └─────────────────────────┬────────────────────────────┘    │
│                             │                                │
└─────────────────────────────┼────────────────────────────────┘
                              │
                              ▼ JSON payload
┌─────────────────────────────────────────────────────────────┐
│  _generate_map_html()  →  QWebEngineView                     │
│                                                              │
│  Leaflet markers (AQI colour + wind ring)                    │
│  Leaflet.heat heatmap (density-aware)                        │
│  Solar layer (heatmap from analytical_indices.solar_index)  │
│  Storm layer (heatmap from analytical_indices.storm_risk)   │
│  Lightning layer (markers from lightning_events)            │
│  Analytical popups (sparkline + inversion gauge)         │
│  Cluster alert banner                                        │
│  Layer toggle toolbar (Stationer, Heatmap, Sol, Åska, Blixtar, Sensorer) │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Flow

```
weather.db
  │
  ├── get_cities_with_weather_for_map()    → latest row per city (single JOIN)
  ├── get_24h_rolling_average(pm25)        → per-city PM2.5 average
  ├── get_weather_history(hours=24)        → per-city trend points
  ├── get_national_pm25_7day_average()     → national 7-day PM2.5 baseline
  ├── get_parameter_winsorized_bounds()    → p5/p95 from full history
  ├── get_all_sensors()                   → raw sensor marker layer
  ├── get_latest_analytical_indices()     → solar_index, storm_risk, smog_risk
  └── lightning_events table              → strike events for lightning layer
           │
           ▼
    MapDataBuilder.build()
           │
           ▼  adds: solar_layer, storm_layer, lightning_layer
           │
           ▼  single JSON object
    _generate_map_html()
           │
           ▼
    QWebEngineView (Leaflet + leaflet.heat)
```

---

## MapDataBuilder

**Location:** `gui/stations_tab.py` — class `MapDataBuilder`

Builds the complete payload consumed by Leaflet. Instantiated fresh on every map load/refresh, so the payload always reflects current database state.

### Payload structure

```python
{
    "cities": [
        {
            "city_id":        int,
            "city_name":      str,
            "latitude":       float,
            "longitude":      float,
            "pm25_24h":       float | None,   # 24h rolling average
            "aqi_level":      str,             # e.g. "good", "moderate"
            "aqi_color":      str,             # hex colour from WarningDetector
            "aqi_level_name": str,             # Swedish label
            "temperature":    float | None,
            "humidity":       float | None,
            "wind_speed":     float | None,
            "no2":            float | None,
            "o3":             float | None,
            "trend_24h":      [{"ts": str, "pm25": float}, ...],
            "inversion_score": float | None,   # 0–100, see model below
            "cluster_region": str | None,      # "norr" or "söder"
            "density_radius": int,             # neighbour count within 2°
            "low_density":    bool,
        },
        ...
    ],
    "sensors": [...],        # raw OpenAQ sensor markers
    "cluster_alerts": [
        {
            "region":            str,    # "norr" or "söder"
            "region_mean":       float,
            "national_baseline": float,
            "deviation_pct":     float,
            "city_count":        int,
        },
        ...
    ],
    "score_metadata": {
        "wind_bounds":      [float, float] | [None, None],
        "humidity_bounds":  [float, float] | [None, None],
        "percentile_range": [int, int],        # always [5, 95]
        "data_rows_used":   int,
        "bounds_available": bool,
    },
    "idw_grid":       [[lat, lon, value], ...],  # IDW interpolation grid for PM2.5 heatmap
    "idw_meta":       {...},                     # grid geometry metadata
    "idw_max":        float,                     # p95 colour-scale anchor
    "idw_true_max":   float,                     # actual grid maximum
    "solar_layer":    [{"lat": float, "lon": float, "solar_index": float}, ...],  # Solar index heatmap points
    "storm_layer":    [{"lat": float, "lon": float, "storm_risk": float}, ...],   # Storm risk heatmap points
    "lightning_layer": [{"lat": float, "lon": float, "timestamp": str, "intensity": float}, ...],  # Lightning strike markers
}
```

---

## Inversion Risk Model

### Purpose

Temperature inversion occurs when a warm air layer traps cold air near the surface. This prevents vertical mixing, causing pollutants to accumulate. The model estimates inversion risk from the two meteorological proxies available in `weather_data`: `wind_speed` and `humidity`.

- **Low wind speed** means weak turbulent mixing → stagnant air → higher risk
- **High humidity** is a proxy for stable, moist air masses associated with inversion conditions

### Design evolution

| Version | Normalization | Problem |
|---|---|---|
| v1 | Runtime snapshot min/max | Score shifts daily — not comparable across time |
| v2 | Full-history min/max | One bad sensor (e.g. 120 m/s) permanently corrupts MAX |
| **v3 (current)** | **Winsorized p5/p95 from full history** | **Outlier-robust and temporally stable** |

### Score formula

```
wind_lo, wind_hi = get_parameter_winsorized_bounds('wind_speed', 5, 95)
hum_lo,  hum_hi  = get_parameter_winsorized_bounds('humidity',   5, 95)

wind_norm = clamp((city.wind_speed - wind_lo) / (wind_hi - wind_lo), 0, 1)
hum_norm  = clamp((city.humidity   - hum_lo)  / (hum_hi  - hum_lo),  0, 1)

inversion_score = (
    (1 - wind_norm) * 0.6   # high wind → low risk
  +     hum_norm   * 0.4    # high humidity → higher risk
) * 100
```

Output range: `0` (no risk) to `100` (maximum observed risk).

### Why winsorization makes the score temporally stable

The bounds `wind_lo` and `wind_hi` are the 5th and 95th percentile of **all historical readings** in `weather_data`. They shift only when a genuinely new extreme value is recorded at the population level. This means:

- Score 70 computed today equals Score 70 computed next month, assuming the underlying atmospheric conditions are identical.
- A single faulty sensor emitting `wind_speed = 120 m/s` has no effect on the 95th percentile as long as it represents less than 5% of all readings — which any single sensor will once the system has real volume.

### Null conditions

The score is emitted as `null` (never substituted) in any of the following situations:

| Condition | Reason |
|---|---|
| Fewer than 20 historical rows for either parameter | Insufficient data to trust percentile positions |
| `wind_range == 0` after winsorization | All historical wind readings identical — data quality signal |
| `hum_range == 0` after winsorization | All historical humidity readings identical — data quality signal |
| `city.wind_speed` or `city.humidity` is `None` | Missing current observation |

### Score metadata in popup

Every popup that displays an inversion score also shows its calibration context:

```
Kalibrerad mot 4821 mätningar (p5–p95)
Vind: 0.2–9.1 m/s · Fuktighet: 52–94%
```

This allows the user to judge whether the bounds are mature (large N, wide range) or still settling (small N, narrow range).

---

## Cluster Analysis

### Purpose

Identify when a geographic region of Sweden shows elevated PM2.5 relative to the national trend — not just relative to an absolute threshold. An alert that fires only when one region exceeds the national 7-day baseline by a statistically meaningful margin avoids false alarms when the entire country is uniformly elevated.

### Algorithm

```
1.  national_7day_mean = get_national_pm25_7day_average()
    (mean PM2.5 across all cities, last 168 hours)

2.  median_lat = median latitude of all cities with valid pm25_24h
    (computed from data — not hardcoded)

3.  north = cities with latitude >= median_lat
    south = cities with latitude <  median_lat

4.  For each region:
        region_mean = mean(pm25_24h for valid cities in region)

        deviation_factor = THRESHOLDS['moderate'] / THRESHOLDS['good']
        (ratio of two existing WarningDetector values — not a new constant)

        if region_mean > national_7day_mean * deviation_factor:
            emit cluster_alert {
                region, region_mean, national_baseline, deviation_pct, city_count
            }
```

### Why deviation_factor is derived, not hardcoded

`THRESHOLDS['moderate'] / THRESHOLDS['good']` = `35.4 / 12.0` ≈ `2.95`. This ratio encodes the question: "is this region more than ~3× the good-air threshold above the national baseline?" If WHO/EPA ever revise their thresholds, the deviation factor updates automatically.

### Alert payload

```python
{
    "region":            "söder",
    "region_mean":       28.4,         # µg/m³
    "national_baseline": 8.1,          # µg/m³ (7-day mean)
    "deviation_pct":     250.6,        # %
    "city_count":        12,
}
```

The banner renders: *"⚠ Regional påverkan: Södra Sverige — PM2.5 snitt 28.4 µg/m³ (+250.6% mot nationellt 7d-snitt 8.1 µg/m³, 12 stationer)"*

Cities with `pm25_24h = None` are excluded from both region means and the median-latitude split.

---

## Station Density Map

### Purpose

Heatmap interpolation is misleading when station coverage is uneven. Northern Sweden has significantly fewer measurement stations than the south. The density map communicates interpolation reliability directly to the user.

### Algorithm

```python
for each city:
    density_radius = count of other cities where:
        |other.latitude  - city.latitude|  <= 2.0
        |other.longitude - city.longitude| <= 2.0

    low_density = (density_radius < 2)
```

This is an O(N²) loop over the city list. No external geo library is required.

### Visual output

| Field | Value | Map effect |
|---|---|---|
| `density_radius` | int ≥ 0 | Displayed in popup |
| `low_density: false` | dense area | No warning |
| `low_density: true` | sparse area | Yellow warning in popup: "⚠ Gles stationstäckning — heatmap-interpolation osäker" |

The 2-degree bounding box is not a physics threshold — it is a spatial resolution parameter chosen to reflect the typical station spacing for meaningful interpolation over Sweden's geography.

---

## Database Queries

All three new queries live in `database/db_manager.py`.

### `get_cities_with_weather_for_map()`

```sql
SELECT c.id AS city_id,
       c.name AS city_name,
       c.latitude, c.longitude,
       wd.temperature, wd.humidity, wd.wind_speed,
       wd.pm25, wd.no2, wd.o3
FROM cities c
INNER JOIN weather_data wd ON wd.city_id = c.id
INNER JOIN (
    SELECT city_id, MAX(timestamp) AS max_ts
    FROM weather_data
    GROUP BY city_id
) latest ON wd.city_id = latest.city_id
        AND wd.timestamp = latest.max_ts
ORDER BY c.name
```

Replaces the previous N+1 pattern (`get_latest_weather()` called once per city). Returns one row per city.

### `get_national_pm25_7day_average()`

```sql
SELECT AVG(pm25) AS mean_pm25
FROM weather_data
WHERE pm25 IS NOT NULL
  AND timestamp > datetime('now', '-168 hours')
```

The 168-hour window (7 days) is the cluster analysis baseline. Returns `None` if no data exists.

### `get_parameter_winsorized_bounds(parameter, p_low, p_high)`

```python
# Step 1 — SQL: fetch full sorted history
SELECT {parameter} FROM weather_data
WHERE {parameter} IS NOT NULL
ORDER BY {parameter} ASC

# Step 2 — Python: compute percentile indices
n      = len(rows)
lo_idx = max(0,     int(round(p_low  / 100 * (n - 1))))
hi_idx = min(n - 1, int(round(p_high / 100 * (n - 1))))
return rows[lo_idx], rows[hi_idx]
```

**Security:** The `parameter` argument is validated against an explicit whitelist before being interpolated into the SQL string:

```python
ALLOWED_PARAMETERS = {
    "wind_speed", "humidity", "temperature",
    "pm25", "pm10", "no2", "o3", "aqi"
}
```

Returns `(None, None)` if fewer than 20 rows exist.

---

## JavaScript Layer

The JavaScript in `_generate_map_html()` is a pure renderer. It receives `PAYLOAD` (the JSON object from `MapDataBuilder`) and renders it. No analytical logic lives in JavaScript.

### Layer structure

| Layer | Leaflet type | Toggle button |
|---|---|---|
| City AQI markers | `L.circleMarker` (inner dot + outer wind ring) | Stationer |
| Heatmap | `L.heatLayer` (leaflet.heat CDN) | Heatmap |
| Raw sensor markers | `L.marker` | Sensorer |

### Heatmap timing fix

`leaflet.heat` calls `canvas.getImageData()` synchronously when `.addTo(map)` is called. Inside `QWebEngineView`, the Qt layout engine has not yet assigned pixel dimensions to the canvas at the time `map.whenReady()` fires. The heatmap creation is therefore deferred with:

```javascript
setTimeout(function() {
    if (typeof L.heatLayer !== "function") {
        console.error("[Heatmap] leaflet.heat not loaded — heatLayer skipped");
        return;
    }
    map.invalidateSize();   // force Qt layout recalculation
    if (heatPoints.length > 0) {
        heatLayer = L.heatLayer(heatPoints, { max: heatMax, ... }).addTo(map);
    }
}, 800);
```

`map.invalidateSize()` forces Leaflet to re-query the container dimensions from the Qt layout engine before `leaflet.heat` touches the canvas. The 800 ms delay is the safe margin for Qt's layout pass to complete. 300 ms was insufficient on slower systems.

### Heatmap `max` is data-driven

`leaflet.heat` normalizes each point's intensity as `value / max`. A hardcoded `max` (e.g. 150 µg/m³) makes the heatmap invisible when ambient PM2.5 values are low (typical Swedish clean-air readings of 1–10 µg/m³ would render at < 7% intensity).

`heatMax` is computed dynamically before the `setTimeout`:

```javascript
var heatMax = heatPoints.length > 0
    ? Math.max.apply(null, heatPoints.map(function(p) { return p[2]; }))
    : 1.0;
```

The full gradient always maps to the actual observed data range. No physics constant or threshold is introduced.

### leaflet-heat bundled locally

`leaflet-heat.js` is served as an inline `<script>` block — the file content is read from `ui/static/leaflet-heat.js` at HTML generation time. No CDN request is made at runtime. QWebEngine frequently blocks external CDN requests silently; inlining eliminates that failure mode entirely.

### Popup components

Each city marker opens a popup containing:

1. **City name + AQI badge** — colour from `aqi_color`, label from `aqi_level_name`
2. **Current values** — PM2.5 (24h), temperature, humidity, wind speed, NO₂, O₃
3. **24h PM2.5 sparkline** — inline path, no external charting library
4. **Inversion risk gauge** — horizontal bar (0–100), colour-coded:
   - Green: score < 40
   - Orange: 40–69
   - Red: ≥ 70
5. **Calibration metadata** — N readings, p5–p95 range, wind and humidity bounds
6. **Low-density warning** — shown only when `low_density: true`
7. **Google Maps link**

### Cluster banner

Rendered at the bottom of the map from the `cluster_alerts` array. Only visible when at least one regional deviation alert is active. Each banner item is self-describing:

```
⚠ Regional påverkan: Södra Sverige — PM2.5 snitt 28.4 µg/m³ (+250.6% mot nationellt 7d-snitt 8.1 µg/m³, 12 stationer)
```

---

## Calibration Parameters (DB-driven)

All analytical model parameters are stored in the `calibration_parameters` table and read from the database at runtime. No hardcoded constants remain in the codebase.

### Inversion Model Parameters

| Key | Default Value | Unit | Role |
|---|---|---|---|
| `inversion_p_low` | `5.0` | percentile | Lower winsorization percentile — outlier cutoff |
| `inversion_p_high` | `95.0` | percentile | Upper winsorization percentile — outlier cutoff |
| `inversion_wind_weight` | `0.6` | dimensionless | Wind speed contribution to inversion score (0.0-1.0) |
| `inversion_humidity_weight` | `0.4` | dimensionless | Humidity contribution to inversion score (0.0-1.0) |

**Invariant:** `inversion_wind_weight + inversion_humidity_weight` = `1.0` always (enforced by normalization if needed).

### IDW Heatmap Parameters

| Key | Default Value | Unit | Role |
|---|---|---|---|
| `idw_power` | `2.3` | dimensionless | IDW decay exponent — higher values create tighter local hotspots |
| `idw_max_r_factor` | `1.3` | dimensionless | Factor dividing max_r to prevent distant stations from dominating interpolation |
| `idw_scale_percentile` | `95.0` | percentile | Colour scale anchor percentile for IDW heatmap (outlier-robust) |

### Map Extent (heatmap and view bounds)

The geographic extent of the map and of all heatmap layers (PM2.5, solar, storm) is **DB-driven**; no coordinates are hardcoded in application code.

| Key | Role |
|-----|------|
| `map_extent_lat_min`, `map_extent_lat_max` | Southern and northern latitude bounds |
| `map_extent_lon_min`, `map_extent_lon_max` | Western and eastern longitude bounds |

- **Source**: Read from `calibration_parameters` at runtime (migration sets a default Sweden bbox, e.g. lat 55.3–69.1, lon 11–24.2). Values can be changed in the DB for other regions.
- **Fallback**: If any of the four keys is missing or invalid, the extent is computed from the **bounding box of all cities** in the `cities` table (with 5% padding). Thus the map and heatmap always cover either the configured region or the full set of stations.
- **Usage**: `MapDataBuilder._get_map_extent()` returns `(lat_min, lat_max, lon_min, lon_max)`. This extent is passed to `_compute_idw_grid` and `_compute_layer_idw_grid` so all heatmap layers share the same geographic box. The payload includes `map_extent`; the Leaflet map uses `fitBounds()` so the full extent is visible on load.

### Solar, Storm, and Lightning Layers

The map supports multiple analytical layers that can be toggled independently:

**Solar Layer:**
- Data source: `analytical_indices.solar_index` (latest per city)
- Rendering: Canvas-based heatmap (similar to PM2.5 heatmap)
- Color gradient: Yellow to orange (represents solar intensity)
- Opacity: Configurable via `solar_layer_opacity` in `calibration_parameters` (default: 70%)

**Storm Layer:**
- Data source: `analytical_indices.storm_risk` (latest per city)
- Rendering: Canvas-based heatmap
- Color gradient: Purple to red (represents storm risk intensity)
- Opacity: Configurable via `storm_layer_opacity` in `calibration_parameters` (default: 70%)

**Lightning Layer:**
- Data source: `lightning_events` table (last 24h, configurable via `lightning_display_hours`)
- Rendering: Custom markers with lightning bolt (⚡)
- Popup: Shows timestamp, intensity, distance from city center
- Opacity: Configurable via `lightning_layer_opacity` in `calibration_parameters` (default: 100%)

**Layer Toggle Buttons:**
- Dynamically generated in map toolbar
- Buttons: "Stationer", "Heatmap", "Sol", "Åska", "Blixtar", "Sensorer"
- Each layer can be toggled independently
- Layer state persists during map session

### Analytical Indices

Analytical indices are computed after weather data is saved:

**Solar Index:**
- Formula: `w1*normalize(solar_radiation) + w2*normalize(uv_index) + w3*normalize(sunshine_duration)`
- Weights: `solar_index_radiation_weight`, `solar_index_uv_weight`, `solar_index_sunshine_weight` (from `calibration_parameters`)
- Range: [0, 1]

**Storm Risk:**
- Formula: `storm_risk = base_risk × cape_factor` where `cape_factor = _calculate_cape_factor(cape)`
- Base risk: `w1*normalize(convective_precipitation) + w2*normalize(precipitation_probability) + w3*normalize(humidity) - w4*normalize(wind_speed)`
- CAPE scaling: Piecewise linear scaling with meteorologically significant thresholds (0, 100, 1000, 2500 J/kg)
- Parameters: `storm_risk_cape_zero_threshold`, `storm_risk_cape_weak_threshold`, `storm_risk_cape_moderate_threshold`, `storm_risk_cape_strong_threshold`, `storm_risk_cape_weak_factor`, `storm_risk_cape_moderate_factor`, `storm_risk_cape_strong_factor`, `storm_risk_cape_extreme_factor`, `storm_risk_convective_weight`, etc. (from `calibration_parameters`)
- Range: [0, 1] (CAPE = 0 → storm_risk = 0, absolute gate - meteorologically correct)

**Smog Risk:**
- Formula: `w1*normalize(o3) + w2*normalize(solar_radiation) - w3*normalize(wind_speed)`
- Weights: `smog_risk_o3_weight`, `smog_risk_solar_weight`, `smog_risk_wind_weight` (from `calibration_parameters`)
- Range: [0, 1]

All indices are stored in `analytical_indices` table with timestamp for historical analysis.

### Time Windows

| Key | Default Value | Unit | Role |
|---|---|---|---|
| `time_window_trend_hours` | `24.0` | hours | Hours of history for trend sparklines and per-city statistics |
| `time_window_baseline_days` | `7.0` | days | Days for national baseline in cluster analysis |
| `time_window_rolling_avg_hours` | `24.0` | hours | Hours for rolling average calculations (PM2.5, etc.) |

### Wind Aggregation

| Key | Default Value | Unit | Role |
|---|---|---|---|
| `wind_aggregation_method` | `1.0` | code | Aggregation method: 0=mean, 1=median, 2=winsorized_mean (default: 1=median) |
| `wind_winsorize_p_low` | `5.0` | percentile | Lower percentile for winsorized mean (only used if method=2) |
| `wind_winsorize_p_high` | `95.0` | percentile | Upper percentile for winsorized mean (only used if method=2) |

**Wind aggregation methods:**
- **Mean (0)**: Arithmetic average — sensitive to outliers (e.g., a single 50 m/s station can skew the national average).
- **Median (1, default)**: Middle value — robust to outliers, recommended for national aggregates.
- **Winsorized mean (2)**: Mean after clamping extreme values to p5/p95 percentiles — balances robustness with sensitivity to distribution shape.

### Accessing Calibration Parameters

Parameters are accessed via `DatabaseManager.get_calibration_parameter(key)` or `get_all_calibration_parameters()`. If a required parameter is missing from the database, the system fails loudly with a clear error message — no silent fallbacks to code constants.

All other values used in computations are either:
- Fetched from `weather_data` (bounds, means, counts)
- Derived from `WarningDetector.get_threshold_metadata()` (deviation factor, AQI levels, colours)
- Computed from the data itself (median latitude, region means, density counts)

---

## WarningDetector.get_threshold_metadata()

This `@staticmethod` is the single stable public API for all consumers that need threshold/colour/label data.

```python
metadata = WarningDetector.get_threshold_metadata()
# Returns: List[Dict] — one entry per AQI level, ordered low → high

# Each entry:
{
    "level":      "good",          # internal key
    "name":       "Bra",           # display label (Swedish)
    "color":      "#00e400",       # hex colour string
    "min_pm25":   0.0,             # lower PM2.5 bound µg/m³
    "max_pm25":   12.0,            # upper PM2.5 bound µg/m³  (None for last level)
    "aqi_min":    0,               # AQI range low
    "aqi_max":    50               # AQI range high           (None for last level)
}
```

**Invariants:**
- No `DatabaseManager` instance required
- No runtime side effects
- Calling this before any DB connection is safe
- Order is stable and determined by `_LEVEL_ORDER`

**Consumers:** `HelpDialog`, `MapDataBuilder` (deviation_factor), JavaScript `PAYLOAD.gradient` (AQI colours for heatmap)

---

## Debug Mode

When `config.json` contains `"debug_mode": true` (set via **Inställningar → Debug**), each station popup exposes an additional panel:

| Field | Source |
|---|---|
| `wind_raw` | `city.wind_speed` (m/s, as-fetched) |
| `hum_raw` | `city.humidity` (%, as-fetched) |
| `wind_norm` | `(wind_raw - wind_lo) / wind_range` |
| `hum_norm` | `(hum_raw - hum_lo) / hum_range` |
| `national_baseline` | `national_7day_mean` (µg/m³) |
| `deviation_factor` | derived from `get_threshold_metadata()` |
| `inversion_model_version` | `config["settings"]["inversion_model_version"]` |

Debug mode never alters the computed values — it only reveals them. All fields are `null`-safe; if a value is `null` the label reads `"n/a"`.

---

## Null Handling Policy

A value is emitted as `null` when data is genuinely absent. No value is ever substituted, interpolated, or estimated.

| Situation | Affected output |
|---|---|
| City has no `pm25_24h` | Excluded from cluster analysis, national baseline, and density median-lat split. Marker renders grey (`#cccccc`). No popup analytics section. |
| Fewer than 20 rows for `wind_speed` or `humidity` | `inversion_score = null` for all cities. Popup shows: "Historik < 20 rader — kalibrering pågår" |
| `wind_range == 0` or `hum_range == 0` after winsorization | `inversion_score = null` for that city. Logged as data quality signal. |
| `city.wind_speed` or `city.humidity` is `None` | `inversion_score = null` for that city |
| `national_7day_mean` is `None` | No cluster alerts emitted |
| `heatPoints` empty | Heatmap layer not created (no empty canvas operations) |
