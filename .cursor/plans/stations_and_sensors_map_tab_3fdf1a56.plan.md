---
name: Stations and Sensors Map Tab
overview: Skapa en ny flik med interaktiv karta som visar alla OpenAQ-sensorer för städerna. Varje sensor visas som marker med popup (info + Google Maps-länk). Context menu för att lägga till custom markers. Inga hårdkodade värden, inga fallbacks, no data is better than mock data.
todos: []
---

# Stations and Sensors Map Tab

## Overview

Skapa en ny flik "Stationer" med interaktiv Leaflet-karta som visar alla OpenAQ-sensorer för städerna i databasen. Varje sensor visas som marker med popup som innehåller sensor-info och "Open in Google Maps"-länk. Context menu för att lägga till custom markers med egna sensorer.

**Design Principles:**

- Database-first: Spara sensorer i databas, läs från DB
- Dynamisk: Alla värden från API eller databas, inga hårdkodade IDs
- No fallbacks: Om data saknas → hoppa över, visa tom karta (no data is better than mock data)
- Minimal arkitektur: Database = source of truth, Provider = API only, GUI = display only
- No GUI-cache: Ingen smart refresh, ingen cache i GUI

## Architecture

### Data Flow (Database-First, No Cache)

```
User öppnar "Stationer" flik
    ↓
Hämtar alla städer från databas (dynamiskt)
    ↓
För varje stad: Läsa sensorer från databas (sensors tabell)
    ↓
Om sensorer finns i DB:
  - Generera JSON med sensor data (sensor_id, parameter, lat, lon, last_value)
  - Skicka JSON till HTML via setHtml()
  - Leaflet renderar markers på karta
Om inga sensorer finns i DB:
  - Visa tom karta (NO fallback, no mock data)
    ↓
Klicka på marker → visa popup med info + Google Maps-länk
Right-click på karta → context menu → lägg till custom marker
```

### Sensor Storage (Database Schema)

**New table: `sensors`**

- `id` INTEGER PRIMARY KEY
- `city_id` INTEGER (FOREIGN KEY to cities)
- `sensor_id` INTEGER (OpenAQ sensor ID)
- `parameter` TEXT (PM2.5, NO2, O3, etc.)
- `latitude` REAL
- `longitude` REAL
- `last_value` REAL (senaste mätvärdet)
- `last_updated` DATETIME
- `is_custom` INTEGER DEFAULT 0 (0 = OpenAQ sensor, 1 = custom marker)
- `custom_info` TEXT (JSON för custom markers, NULL för OpenAQ sensors)

## Implementation Tasks

### 1. Database Schema for Sensors

**File: `database/schema.sql`**

- **Add new table `sensors`:**
```sql
CREATE TABLE IF NOT EXISTS sensors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL,
    sensor_id INTEGER,  -- NULL for custom markers
    parameter TEXT,    -- NULL for custom markers
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    last_value REAL,   -- NULL for custom markers
    last_updated DATETIME,
    is_custom INTEGER DEFAULT 0,
    custom_info TEXT,  -- JSON for custom markers, NULL for OpenAQ sensors
    FOREIGN KEY (city_id) REFERENCES cities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sensors_city ON sensors(city_id);
CREATE INDEX IF NOT EXISTS idx_sensors_sensor_id ON sensors(sensor_id);
```


**File: `database/migration_add_sensors_table.sql` (NEW)**

- Idempotent migration: Check if table exists before creating
- Migration Safety:
                                - Check if `sensors` table exists (query sqlite_master)
                                - Run migration only once per database
                                - Handle migration errors gracefully (log and continue, NO fallback)

**File: `database/db_manager.py`**

- **Add method `has_sensors_table() -> bool`:**
                                - Check if `sensors` table exists (query sqlite_master)
                                - Returnera True om tabell finns, False annars

- **Update `_run_migration_if_needed()`:**
                                - Check `has_sensors_table()`
                                - Om False → kör migration script
                                - Handle migration errors gracefully (log and continue, NO fallback)

- **Add method `add_sensor(city_id, sensor_id, parameter, lat, lon, last_value, is_custom=0, custom_info=None) -> int`:**
                                - Lägg till sensor i databas
                                - Returnera sensor ID
                                - Om sensor_id redan finns för city_id → uppdatera istället (NO duplicate)

- **Add method `get_sensors_for_city(city_id) -> List[Dict]`:**
                                - Hämta alla sensorer för en stad
                                - Returnera lista med sensor-dicts
                                - Om inga sensorer → returnera tom lista (NO fallback)

- **Add method `get_all_sensors() -> List[Dict]`:**
                                - Hämta alla sensorer från alla städer
                                - Returnera lista med sensor-dicts inklusive city_name
                                - Om inga sensorer → returnera tom lista (NO fallback)

- **Add method `update_sensor_value(sensor_id, last_value, last_updated) -> bool`:**
                                - Uppdatera senaste värde och timestamp för sensor
                                - Returnera True om uppdaterad, False om fel

- **Add method `add_custom_marker(city_id, lat, lon, custom_info) -> int`:**
                                - Lägg till custom marker (is_custom=1)
                                - custom_info är JSON string med marker info
                                - Returnera marker ID

- **Add method `delete_sensor(sensor_id) -> bool`:**
                                - Ta bort sensor från databas
                                - Returnera True om borttagen, False om fel

### 2. OpenAQ Provider - Extract Sensor Data

**File: `providers/openaq_provider.py`**

- **Update `get_air_quality()` to return sensor data:**
                                - Returnera även lista av sensorer med: `sensor_id`, `parameter`, `value`, `coordinates`
                                - Struktur: `{"pollutants": {...}, "measurement_timestamp": ..., "sensors": [{"sensor_id": ..., "parameter": ..., "value": ..., "coordinates": {...}}]}`
                                - Extrahera sensor data från `/latest` response
                                - Om inga sensorer → returnera tom lista (NO fallback)

### 3. WeatherController - Save Sensors to Database

**File: `controllers/weather_controller.py`**

- **Update `_update_city_weather()`:**
                                - När OpenAQ returnerar sensor data:
                                                                - För varje sensor i response:
                                                                                                - Check om sensor redan finns i DB: `db.get_sensors_for_city(city_id)` med sensor_id
                                                                                                - Om sensor finns → uppdatera: `db.update_sensor_value(sensor_id, value, timestamp)`
                                                                                                - Om sensor saknas → lägg till: `db.add_sensor(city_id, sensor_id, parameter, lat, lon, value)`
                                                                - **CRITICAL**: Spara alla sensorer, inte bara location_id
                                                                - Om sensor data saknas → hoppa över (NO fallback, no mock data)

### 4. Stations Tab with Leaflet Map

**File: `gui/stations_tab.py`**

- **Create `StationsTab(QWidget)` class:**
                                - Layout: Full-screen map with optional sidebar for city selection
                                - **Map Implementation: QWebEngineView + Leaflet**
                                                                - Check if `PyQt5.QtWebEngineWidgets` is available at runtime
                                                                - If not available → show error message (NO fallback, no map)
                                                                - Generate HTML with Leaflet.js
                                                                - Load sensors from database, generate JSON
                                                                - Send JSON to HTML via `setHtml()` or `runJavaScript()`

- **Map Features:**
                                - **Zoom Controls**: Add Leaflet zoom controls (zoom in/out buttons)
                                - **Scroll to Zoom**: Enable mouse wheel zoom (default Leaflet behavior)
                                - **Ctrl + Scroll**: Enable Ctrl + scroll for zoom (Leaflet default)
                                - **Context Menu**: Right-click on map → show context menu
                                                                - "Add Custom Marker" → dialog för att lägga till custom marker
                                                                - Custom marker dialog: lat, lon, name, description, value (optional)
                                                                - Save custom marker to database via `db.add_custom_marker()`
                                                                - Refresh map after adding custom marker

- **Methods:**
                                - `_init_ui()`: Skapa layout och QWebEngineView, check WebEngine availability
                                - `_load_sensors()`: Hämta sensorer från databas för alla städer
                                - `_generate_map_html(sensors_json) -> str`: Generera HTML med Leaflet.js
                                - `_add_markers_to_map(sensors)`: Lägg till markers via JavaScript
                                - `_show_sensor_popup(sensor)`: Visa popup med sensor info + Google Maps link
                                - `_on_map_right_click(lat, lon)`: Handle right-click → show context menu
                                - `_add_custom_marker_dialog()`: Dialog för att lägga till custom marker
                                - `_check_webengine_available() -> bool`: Check if WebEngine is available

- **Refresh Logic:**
                                - **No Auto Refresh**: Don't refresh on every `refresh_all()` call
                                - **Manual Refresh**: "Refresh Stations" button triggers reload from database
                                - **On Tab Open**: Load sensors from database when tab is first opened
                                - **No Cache**: Always read from database (database = source of truth)

### 5. Leaflet Map HTML Template

**HTML Structure (generated in `_generate_map_html()`):**

```html
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        #map { height: 100vh; width: 100%; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([62.0, 15.0], 5); // Center on Sweden
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
        
        // Zoom controls
        L.control.zoom({ position: 'topright' }).addTo(map);
        
        // Enable scroll to zoom (default)
        map.scrollWheelZoom.enable();
        
        // Sensors data from Python
        var sensors = {{SENSORS_JSON}};
        
        // Add markers
        sensors.forEach(function(sensor) {
            var marker = L.marker([sensor.latitude, sensor.longitude])
                .addTo(map)
                .bindPopup(`
                    <b>${sensor.parameter || 'Custom Marker'}</b><br>
                    ${sensor.last_value ? 'Value: ' + sensor.last_value + ' µg/m³<br>' : ''}
                    <a href="https://www.google.com/maps?q=${sensor.latitude},${sensor.longitude}" target="_blank">
                        Open in Google Maps
                    </a>
                `);
        });
        
        // Right-click context menu
        map.on('contextmenu', function(e) {
            // Send coordinates to Python via JavaScript bridge
            window.pyqt_bridge.onMapRightClick(e.latlng.lat, e.latlng.lng);
        });
    </script>
</body>
</html>
```

### 6. JavaScript Bridge for Context Menu

**File: `gui/stations_tab.py`**

- **Add JavaScript bridge:**
                                - Create `QWebChannel` for communication between Python and JavaScript
                                - Expose Python method `onMapRightClick(lat, lon)` to JavaScript
                                - When JavaScript calls `onMapRightClick()` → show context menu dialog in Python
                                - After adding custom marker → refresh map via `runJavaScript()`

### 7. Custom Marker Dialog

**File: `gui/stations_tab.py`**

- **Create `CustomMarkerDialog(QDialog)` class:**
                                - Fields: Latitude, Longitude, Name, Description, Value (optional)
                                - Buttons: OK, Cancel
                                - Validation: Check if lat/lon are valid numbers
                                - On OK: Save to database via `db.add_custom_marker()`
                                - After save: Refresh map to show new marker

### 8. Integrate Tab into Main Window

**File: `gui/main_window.py`**

- Import `StationsTab`
- Skapa instans: `self.stations_tab = StationsTab(self.controller)`
- Lägg till i tabs: `self.tabs.addTab(self.stations_tab, "Stationer")`
- **DO NOT add to `refresh_all()`**: Stations tab has its own refresh logic
- **Optional**: Add "Refresh Stations" button in toolbar or in tab itself

## Critical Invariants

**No Hardcoded Values:**

- Inga hårdkodade sensor IDs, koordinater, eller parametrar
- Alla värden kommer från API eller databas
- Karta zoom/center beräknas dynamiskt från sensor-koordinater

**No Fallbacks:**

- Om inga sensorer finns → visa tom karta (NO mock data, no fallback markers)
- Om sensor data saknas → hoppa över sensor (NO default values)
- Om WebEngine inte tillgänglig → visa felmeddelande (NO fallback map)
- Om karta inte kan laddas → visa felmeddelande (NO fallback)

**Database-First Approach:**

- Läs sensorer från databas (database = source of truth)
- Spara sensorer när OpenAQ returnerar data
- Ingen GUI-cache: Alltid läs från databas
- Ingen smart refresh: Manual refresh endast

**No Mock Data:**

- No data is better than mock data
- Om inga sensorer → tom karta
- Om sensor saknar värde → visa marker utan värde (NO default value)
- Om custom marker saknar info → visa marker med minimal info (NO default info)

**Dynamic Behavior:**

- Karta uppdateras dynamiskt baserat på sensorer i databasen
- Markers läggs till dynamiskt från databas-data
- Ingen hårdkodad lista av sensorer eller koordinater

## Edge Cases

**No WebEngine Available:**

- Om WebEngine inte är tillgänglig → visa felmeddelande "WebEngine krävs för karta"
- Inga fallbacks, ingen karta

**No Sensors Found:**

- Om inga sensorer finns i databas → visa tom karta med meddelande "Inga sensorer hittades"
- Inga fallbacks, no mock markers

**Partial Sensor Data:**

- Om sensor saknar lat/lon → hoppa över (NO fallback coordinates)
- Om sensor saknar parameter → visa som "Custom Marker" (NO default parameter)
- Om sensor saknar värde → visa marker utan värde (NO default value)

**Custom Marker Errors:**

- Om custom marker dialog avbryts → inget sparas (NO fallback)
- Om custom marker validation misslyckas → visa felmeddelande (NO auto-fix)
- Om custom marker save misslyckas → visa felmeddelande (NO retry)

**Map Loading Failure:**

- Om Leaflet inte kan laddas → visa felmeddelande (NO fallback)
- Om tile layer inte kan laddas → visa felmeddelande (NO fallback tiles)

**Migration Safety:**

- Check if `sensors` table exists before creating (idempotent migration)
- Run migration only once per database
- Handle migration errors gracefully (log and continue, NO fallback)

**JavaScript Bridge Errors:**

- Om JavaScript bridge misslyckas → context menu fungerar inte (NO fallback)
- Log error but don't crash app