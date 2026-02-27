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
│  Analytical popups (sparkline SVG + inversion gauge)         │
│  Cluster alert banner                                        │
│  Layer toggle toolbar                                        │
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
  └── get_all_sensors()                   → raw sensor marker layer
           │
           ▼
    MapDataBuilder.build()
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
    }
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
    map.invalidateSize();   // force Qt layout recalculation
    if (heatPoints.length > 0) {
        heatLayer = L.heatLayer(...).addTo(map);
    }
}, 300);
```

`map.invalidateSize()` forces Leaflet to re-query the container dimensions from the Qt layout engine before `leaflet.heat` touches the canvas. The 300 ms delay is the safe margin for Qt's layout pass to complete.

### Popup components

Each city marker opens a popup containing:

1. **City name + AQI badge** — colour from `aqi_color`, label from `aqi_level_name`
2. **Current values** — PM2.5 (24h), temperature, humidity, wind speed, NO₂, O₃
3. **24h PM2.5 sparkline** — inline SVG path, no external charting library
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

## Configuration Constants

The following four named constants are the **complete and exhaustive set** of non-derived constants in the analytical map system. They are configuration values (sensitivity/tolerance parameters), not physical thresholds.

| Constant | Value | Role |
|---|---|---|
| `INVERSION_P_LOW` | `5` | Lower winsorization percentile — outlier cutoff |
| `INVERSION_P_HIGH` | `95` | Upper winsorization percentile — outlier cutoff |
| `INVERSION_WIND_WEIGHT` | `0.6` | Wind speed contribution to inversion score |
| `INVERSION_HUMIDITY_WEIGHT` | `0.4` | Humidity contribution to inversion score |

`INVERSION_WIND_WEIGHT + INVERSION_HUMIDITY_WEIGHT` = `1.0` always.

All other values used in computations are either:
- Fetched from `weather_data` (bounds, means, counts)
- Derived from `WarningDetector.THRESHOLDS` (deviation factor, AQI levels, colours)
- Computed from the data itself (median latitude, region means, density counts)

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
