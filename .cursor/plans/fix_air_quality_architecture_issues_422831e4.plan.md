---
name: Fix Air Quality Architecture Issues
overview: "Fix multiple architecture issues: duplicate API calls, incorrect JSON paths for pollutant data, lost timestamps, three different AQI systems without normalization, and ensure auto-update is disabled by default. All fixes must be dynamic with no hardcoded values and no fallbacks."
todos:
  - id: add-debug-logging
    content: Add comprehensive logging to identify duplicate API calls and data flow issues
    status: completed
  - id: fix-openweather-components
    content: Extract raw pollutant data from OpenWeather components field
    status: completed
  - id: fix-openaq-timestamp
    content: Ensure OpenAQ measurement timestamp is preserved through data flow
    status: completed
  - id: fix-openmeteo-aqi-path
    content: Fix Open-Meteo european_aqi path or confirm structure
    status: completed
  - id: fix-duplicate-calls
    content: Identify and fix duplicate API calls (same provider called twice)
    status: completed
  - id: verify-aqi-calculation
    content: Ensure AQI is always calculated from raw PM2.5, not provider AQI values
    status: completed
  - id: verify-auto-update-disabled
    content: Verify auto-update is disabled by default
    status: completed
---

# Fix Air Quality Architecture Issues

## Overview

Fix multiple critical architecture problems in the air quality data collection system:

1. Duplicate API calls (same provider called twice)
2. OpenWeather not extracting raw pollutant data from `components`
3. OpenAQ losing measurement timestamp during data mapping
4. Open-Meteo not finding `european_aqi` in correct path
5. Three different AQI systems without normalization
6. Auto-update should be disabled by default

**Design Principles:**

- Dynamic: No hardcoded values, all from API responses
- No fallbacks: If data missing → skip, don't use defaults
- No data is better than mock data
- Auto-update disabled by default

## Problems Identified

### 1. Duplicate API Calls

**Root Cause:**

- `get_air_quality()` is called from `get_current_weather()` (line 110 in openweather_provider.py)
- May also be called separately from controller
- Same coordinates, same second = duplicate API call

**Investigation Needed:**

- Check if `_update_city_weather()` calls `get_air_quality()` separately
- Check if GUI triggers update twice (constructor + refresh button)
- Check if scheduler and manual update both trigger

### 2. OpenWeather Missing Raw Pollutant Data

**Current State:**

- `get_air_quality()` only reads `main.aqi` (categorical 1-5)
- Does NOT read `components` which contains raw values:
  ```json
  {
    "list": [{
      "components": {
        "pm2_5": 12.5,
        "pm10": 25.0,
        "no2": 30.0,
        "o3": 50.0
      }
    }]
  }
  ```


**Fix Required:**

- Extract `components` from response
- Map `pm2_5` → `pm25`, `pm10` → `pm10`, `no2` → `no2`, `o3` → `o3`
- Return in `pollutants` dict (not None)

### 3. OpenAQ Lost Measurement Timestamp

**Current State:**

- Timestamp extracted from `date.utc` or `date.local` in results
- But may be lost when mapping to internal structure
- Log shows "Ingen measurement timestamp hittades" even when date exists

**Fix Required:**

- Ensure timestamp is preserved through entire data flow
- Log full response structure to debug
- Ensure timestamp is passed to controller correctly

### 4. Open-Meteo european_aqi Path Issue

**Current State:**

- Logs show `has_european_aqi=True, value=None`
- Suggests path `data["current"]["european_aqi"]` is wrong or value is actually None

**Fix Required:**

- Log full response structure to see actual path
- Check if `european_aqi` is nested differently
- Verify response structure matches expectations

### 5. Three AQI Systems Without Normalization

**Current State:**

- OpenWeather: 1-5 scale (categorical)
- Open-Meteo: European AQI 0-100+ (numerical)
- OpenAQ: Raw pollutants only (no AQI)

**Issue:**

- Cannot compare AQI values across providers
- Need unified AQI calculation from raw pollutants

**Solution:**

- Calculate AQI from raw pollutants using US EPA standard (already implemented in analyzer)
- Don't use provider AQI values directly
- Always calculate AQI from PM2.5 raw value (24h rolling average)

### 6. Auto-Update Default

**Current State:**

- Code comment says "Auto-update is off by default"
- Need to verify this is actually the case

**Fix Required:**

- Ensure `UpdateScheduler` doesn't start automatically
- Ensure GUI checkbox is unchecked by default
- Verify no automatic start in constructor

## Implementation Tasks

### 1. Fix Duplicate API Calls

**File: `controllers/weather_controller.py`**

- **Add logging to `_update_city_weather()`:**
  - Log when function is called with city name and timestamp
  - Log when each provider is called
  - Track if `get_air_quality()` is called multiple times

- **Check for duplicate triggers:**
  - Verify `update_all_cities()` is only called once per trigger
  - Check if scheduler and manual update both fire
  - Add guard to prevent concurrent updates for same city

- **Fix duplicate calls:**
  - If `get_air_quality()` is called from `get_current_weather()`, don't call it again in controller
  - Or: Don't call `get_air_quality()` from `get_current_weather()`, only from controller
  - Choose one approach and be consistent

### 2. Fix OpenWeather Raw Pollutant Extraction

**File: `providers/openweather_provider.py`**

- **Update `get_air_quality()` method:**
  - After getting `aqi_data = data["list"][0]`
  - Check if `"components"` exists in `aqi_data`
  - Extract raw values:
    ```python
    components = aqi_data.get("components", {})
    pollutants = {
        "pm25": components.get("pm2_5"),  # Note: API uses pm2_5, we use pm25
        "pm10": components.get("pm10"),
        "no2": components.get("no2"),
        "o3": components.get("o3")
    }
    ```

  - Return pollutants dict (not None) if components exist
  - Log extracted values for debugging

- **Update return structure:**
  - Return `{"pollutants": {...}, "measurement_timestamp": ...}` with actual values
  - Only return None if no data at all (NO fallback values)

### 3. Fix OpenAQ Timestamp Preservation

**File: `providers/openaq_provider.py`**

- **Ensure timestamp is preserved:**
  - After extracting `measurement_timestamp` from `date.utc` or `date.local`
  - Ensure it's included in return value
  - Log timestamp extraction for debugging

- **Add detailed logging:**
  - Log full response structure when timestamp is missing
  - Log each step of timestamp extraction
  - Help identify where timestamp is lost

- **Verify return structure:**
  - Ensure `measurement_timestamp` is in returned dict
  - Check controller receives it correctly

### 4. Fix Open-Meteo european_aqi Path

**File: `providers/openmeteo_provider.py`**

- **Add detailed logging:**
  - Log full `data["current"]` structure
  - Log all keys in current dict
  - Identify correct path for `european_aqi`

- **Fix path if needed:**
  - If `european_aqi` is in different location, update path
  - If value is actually None, log why (API may not return it)
  - Don't use fallback values (NO fallback)

- **Note:** Open-Meteo may not provide raw pollutants, only AQI
  - This is acceptable - return None for pollutants
  - Don't try to convert AQI back to pollutants (NO fallback)

### 5. Unified AQI Calculation

**File: `analytics/analyzer.py`**

- **Verify AQI calculation:**
  - Ensure AQI is always calculated from PM2.5 raw value
  - Use 24h rolling average (already implemented)
  - Don't use provider AQI values directly

- **Update controller:**
  - Don't store provider AQI values in database
  - Always calculate AQI from raw PM2.5 value
  - Use analyzer's AQI calculation method

### 6. Ensure Auto-Update is Disabled by Default

**File: `controllers/update_scheduler.py`**

- **Verify constructor:**
  - Ensure `timer` is created but NOT started
  - No `timer.start()` in `__init__`

**File: `gui/main_window.py`**

- **Verify toolbar:**
  - Ensure `auto_update_action.setChecked(False)` (already done)
  - Verify checkbox is unchecked on startup

**File: `main.py`**

- **Verify:**
  - No automatic start of scheduler
  - Comment confirms "Auto-update is off by default"

### 7. Add Debug Logging

**Add comprehensive logging to identify issues:**

- Log when `_update_city_weather()` is called (with city name and timestamp)
- Log when each provider method is called
- Log full API response structure (first time, then summary)
- Log extracted values before returning
- Log when data is saved to database

## Critical Fixes

**No Hardcoded Values:**

- All pollutant names from API response (dynamic mapping)
- All JSON paths verified from actual responses
- No assumptions about response structure

**No Fallbacks:**

- If `components` missing → return None for pollutants (NO default values)
- If `european_aqi` missing → return None (NO default AQI)
- If timestamp missing → return None (NO default timestamp)
- No data is better than mock data

**Dynamic Response Handling:**

- Log full response structure to understand actual format
- Extract values based on actual response structure
- Handle missing fields gracefully (return None, don't crash)

## Files to Modify

1. `providers/openweather_provider.py` - Extract `components` for raw pollutants
2. `providers/openaq_provider.py` - Ensure timestamp preservation, add logging
3. `providers/openmeteo_provider.py` - Fix european_aqi path, add logging
4. `controllers/weather_controller.py` - Add logging, fix duplicate calls, ensure AQI calculated from raw data
5. `controllers/update_scheduler.py` - Verify auto-update disabled by default
6. `gui/main_window.py` - Verify auto-update checkbox unchecked by default

## Testing Strategy

1. **Test duplicate calls:**

   - Run update and check logs for duplicate API calls
   - Verify each provider called once per city per update

2. **Test OpenWeather:**

   - Verify `components` are extracted
   - Verify raw pollutant values are returned
   - Check logs for extracted values

3. **Test OpenAQ:**

   - Verify timestamp is preserved
   - Check logs show timestamp extraction
   - Verify timestamp in database

4. **Test Open-Meteo:**

   - Log full response to see actual structure
   - Verify european_aqi path (or confirm it's not available)

5. **Test AQI calculation:**

   - Verify AQI is calculated from PM2.5, not provider AQI
   - Verify consistent AQI scale across all providers