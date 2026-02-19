---
name: Add Averages Tab for All Cities
overview: Create a new tab that displays average (snitt) values across all cities - average temperature, wind speed, humidity, and AQI. The tab should dynamically calculate and display averages based on available data from all cities.
todos:
  - id: add-averages-method
    content: Add get_all_cities_averages() method to WeatherAnalyzer in analytics/analyzer.py
    status: pending
  - id: add-controller-method
    content: Add get_all_cities_averages() wrapper method to WeatherController
    status: pending
    dependencies:
      - add-averages-method
  - id: create-averages-tab
    content: Create new gui/averages_tab.py with UI for displaying averages
    status: pending
    dependencies:
      - add-controller-method
  - id: integrate-tab
    content: Integrate AveragesTab into MainWindow and add refresh support
    status: pending
    dependencies:
      - create-averages-tab
---

# Add Averages Tab for All Cities

## Overview

Create a new tab "Översikt" (Overview) that displays average values across all cities. This tab will show:

- Average temperature (°C)
- Average wind speed (m/s)
- Average humidity (%)
- Average AQI
- Number of cities included in calculation
- Last update time

## Implementation

### 1. Add Average Calculation Method

**File: `analytics/analyzer.py`**

Add a new method `get_all_cities_averages()` that:

- Gets latest weather data for all cities using `db.get_all_latest_weather()`
- Calculates averages for all available metrics
- Returns a dictionary with averages and metadata
```python
def get_all_cities_averages(self, timeframe: str = 'latest') -> Dict:
    """
    Get average values across all cities.
    
    Args:
        timeframe: 'latest' (current values) or '24h' (24h average)
        
    Returns:
        Dictionary with average values and metadata
    """
```


**Implementation details:**

- For 'latest': Use `get_all_latest_weather()` to get current values for all cities
- For '24h': Get 24h history for all cities and calculate averages
- Calculate: avg_temp, avg_humidity, avg_wind_speed, avg_aqi
- Include: city_count, data_points, last_update
- Handle missing values (None) gracefully - only include cities with data

### 2. Add Controller Method

**File: `controllers/weather_controller.py`**

Add method to expose averages to GUI:

```python
def get_all_cities_averages(self, timeframe: str = 'latest') -> Dict:
    """Get average values across all cities."""
    return self.analyzer.get_all_cities_averages(timeframe)
```

### 3. Create Averages Tab

**File: `gui/averages_tab.py`** (new file)

Create a new tab widget that:

- Displays average values in a clean layout
- Shows timeframe selector (Senaste värden / 24h snitt)
- Updates dynamically when data changes
- Shows number of cities included
- Handles empty data gracefully (no fallbacks, just show "Ingen data")

**UI Layout:**

- Timeframe selector at top
- GroupBox with averages:
  - Snitt temperatur: XX.X°C
  - Snitt fuktighet: XX.X%
  - Snitt vindhastighet: XX.X m/s
  - Snitt AQI: XX
- Metadata section:
  - Antal städer: X
  - Datapunkter: X
  - Senaste uppdatering: HH:MM:SS

### 4. Integrate Tab in Main Window

**File: `gui/main_window.py`**

- Import `AveragesTab`
- Create instance in `_init_ui()`
- Add to tabs: `self.tabs.addTab(self.averages_tab, "Översikt")`
- Add refresh call in `refresh_all()`

### 5. Data Flow

```
GUI (AveragesTab)
  ↓
Controller.get_all_cities_averages()
  ↓
Analyzer.get_all_cities_averages()
  ↓
Database.get_all_latest_weather() or get_weather_history()
  ↓
Calculate averages from all cities
  ↓
Return to GUI for display
```

## Files to Create/Modify

1. **`gui/averages_tab.py`** (NEW) - New tab widget
2. **`analytics/analyzer.py`** - Add `get_all_cities_averages()` method
3. **`controllers/weather_controller.py`** - Add wrapper method
4. **`gui/main_window.py`** - Integrate new tab

## Key Requirements

- **Dynamic**: Only show averages for cities with available data
- **No fallbacks**: If no data, show "Ingen data" - don't use placeholder values
- **Real-time**: Updates when refresh is triggered
- **Clean UI**: Clear labels, proper formatting (1 decimal for temps, 0 decimals for AQI)
- **Timeframe support**: Latest values or 24h average

## Calculation Logic

For 'latest' timeframe:

1. Get `get_all_latest_weather()` - returns latest weather for each city
2. Filter out None values for each metric
3. Calculate average: `sum(values) / len(values)` for each metric
4. Return averages with city count

For '24h' timeframe:

1. Get all cities
2. For each city, get `get_weather_history(city_id, hours=24)`
3. Calculate average for each city over 24h
4. Then calculate average across all cities
5. Return overall averages

## Expected Result

A new "Översikt" tab showing:

- Snitt temperatur: 15.3°C (from 6 cities)
- Snitt fuktighet: 65.2%
- Snitt vindhastighet: 8.5 m/s
- Snitt AQI: 45
- Antal städer: 6
- Senaste uppdatering: 14:30:25