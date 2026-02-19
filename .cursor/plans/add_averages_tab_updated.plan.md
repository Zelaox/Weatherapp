# Add 6x More Cities and Averages Tab

## Overview

1. **Add 6x more cities**: If user has N cities, add 6*N more cities (popular Swedish cities)
2. **Create Averages Tab**: New "Översikt" tab showing average values across ALL cities

## Implementation

### 1. Add Cities Functionality

**File: `controllers/weather_controller.py`**

Add method to add multiple cities at once:

```python
def add_multiple_cities(self, cities: List[Dict[str, float]]) -> int:
    """
    Add multiple cities at once.
    
    Args:
        cities: List of dicts with 'name', 'latitude', 'longitude'
        
    Returns:
        Number of cities successfully added
    """
```

**File: `utils/city_loader.py`** (NEW)

Create utility to:

- Get current city count from database
- Calculate how many cities to add (6x current count)
- Provide list of popular Swedish cities with coordinates
- Return list of cities to add

**Popular Swedish cities to use:**

- Stockholm, Göteborg, Malmö, Uppsala, Västerås, Örebro, Linköping, Helsingborg, Jönköping, Norrköping, Lund, Umeå, Gävle, Borås, Eskilstuna, Södertälje, Karlstad, Halmstad, Växjö, Sundsvall, etc.

### 2. Add Cities on Startup or via Command

**Option A: Add on first startup**

- Check if cities exist
- If < 6 cities, add 6 popular cities automatically

**Option B: Add via script/function**

- Create a function that adds 6x current count
- Can be called manually or on startup

**Implementation:**

- Get current city count: `len(controller.get_all_cities())`
- Calculate cities to add: `6 * current_count`
- If current_count = 0, add 6 cities
- If current_count = 1, add 6 more cities (total 7)
- Use geocoding for city names → coordinates

### 3. Add Average Calculation Method

**File: `analytics/analyzer.py`**

Add method `get_all_cities_averages()`:

- Gets latest weather for all cities using `db.get_all_latest_weather()`
- Calculates averages: temp, humidity, wind_speed, aqi
- Returns dict with averages and metadata (city_count, last_update)

### 4. Add Controller Method

**File: `controllers/weather_controller.py`**

Add `get_all_cities_averages()` wrapper method.

### 5. Create Averages Tab

**File: `gui/averages_tab.py`** (NEW)

Create tab showing:

- Snitt temperatur: XX.X°C
- Snitt fuktighet: XX.X%
- Snitt vindhastighet: XX.X m/s
- Snitt AQI: XX
- Antal städer: X
- Senaste uppdatering: HH:MM:SS

### 6. Integrate Tab

**File: `gui/main_window.py`**

- Import and add AveragesTab
- Add to refresh_all()

## Files to Create/Modify

1. **`utils/city_loader.py`** (NEW) - Utility for adding multiple cities
2. **`gui/averages_tab.py`** (NEW) - Averages display tab
3. **`analytics/analyzer.py`** - Add `get_all_cities_averages()` method
4. **`controllers/weather_controller.py`** - Add `add_multiple_cities()` and `get_all_cities_averages()` methods
5. **`gui/main_window.py`** - Integrate AveragesTab
6. **`main.py`** (optional) - Add cities on startup if needed

## City Addition Strategy

**Dynamic approach:**

1. Get current cities: `cities = controller.get_all_cities()`
2. Current count: `current_count = len(cities)`
3. Cities to add: `to_add = 6 * current_count` (if current_count = 0, add 6)
4. Use predefined list of Swedish cities
5. Filter out cities that already exist
6. Add cities using geocoding for coordinates

**City list (Swedish cities with approximate coordinates):**

```python
SWEDISH_CITIES = [
    {"name": "Stockholm", "lat": 59.3293, "lon": 18.0686},
    {"name": "Göteborg", "lat": 57.7089, "lon": 11.9746},
    {"name": "Malmö", "lat": 55.6059, "lon": 13.0007},
    {"name": "Uppsala", "lat": 59.8586, "lon": 17.6389},
    {"name": "Västerås", "lat": 59.6099, "lon": 16.5448},
    {"name": "Örebro", "lat": 59.2741, "lon": 15.2066},
    {"name": "Linköping", "lat": 58.4108, "lon": 15.6214},
    {"name": "Helsingborg", "lat": 56.0467, "lon": 12.6944},
    {"name": "Jönköping", "lat": 57.7815, "lon": 14.1562},
    {"name": "Norrköping", "lat": 58.5877, "lon": 16.1924},
    {"name": "Lund", "lat": 55.7047, "lon": 13.1910},
    {"name": "Umeå", "lat": 63.8258, "lon": 20.2630},
    {"name": "Gävle", "lat": 60.6749, "lon": 17.1413},
    {"name": "Borås", "lat": 57.7210, "lon": 12.9401},
    {"name": "Eskilstuna", "lat": 59.3666, "lon": 16.5077},
    {"name": "Södertälje", "lat": 59.1955, "lon": 17.6252},
    {"name": "Karlstad", "lat": 59.3793, "lon": 13.5036},
    {"name": "Halmstad", "lat": 56.6744, "lon": 12.8578},
    {"name": "Växjö", "lat": 56.8777, "lon": 14.8094},
    {"name": "Sundsvall", "lat": 62.3908, "lon": 17.3069},
    # Add more as needed
]
```

## Implementation Steps

1. Create `utils/city_loader.py` with city list and addition logic
2. Add `add_multiple_cities()` to controller
3. Add method to add 6x cities (can be called from main.py or GUI)
4. Create `get_all_cities_averages()` in analyzer
5. Create AveragesTab GUI
6. Integrate tab in main window

## Expected Result

- If user has 1 city → add 6 more = 7 total cities
- If user has 2 cities → add 12 more = 14 total cities
- New "Översikt" tab showing averages across all cities
- Dynamic averages that update when data refreshes