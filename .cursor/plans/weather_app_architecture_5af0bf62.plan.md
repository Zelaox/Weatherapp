---
name: Weather App Architecture
overview: Bygger en produktionsklar väderapplikation med PyQt5 GUI, flera API-providers (Open-Meteo, OpenWeatherMap, OpenAQ), SQLite-databas, analysmotor och automatisk insamling var 10:e minut eller manuell uppdatering.
todos:
  - id: db_schema
    content: Skapa SQLite databasschema (cities, weather_data, daily_stats) med indexes och foreign keys
    status: completed
  - id: db_manager
    content: Implementera db_manager.py med CRUD operations för städer och väderdata
    status: completed
    dependencies:
      - db_schema
  - id: config_loader
    content: Skapa config_loader.py för dynamisk läsning av config.json (API keys, settings). Skapar default config.json med OpenWeather och OpenAQ API-nycklar om filen saknas
    status: completed
  - id: base_provider
    content: Implementera base_provider.py med abstract WeatherProvider interface
    status: completed
  - id: api_providers
    content: Implementera alla tre API providers (Open-Meteo, OpenWeatherMap, OpenAQ) med standardiserad data-struktur
    status: completed
    dependencies:
      - base_provider
      - config_loader
  - id: geocoding
    content: Implementera geocoding.py för att konvertera stadnamn till lat/lon
    status: completed
  - id: analytics
    content: Bygg analytics engine (analyzer.py, statistics.py) med SQL queries för rankings och trender
    status: completed
    dependencies:
      - db_manager
  - id: main_window
    content: Skapa PyQt5 huvudfönster med layout (vänsterpanel, huvudpanel, tabs)
    status: completed
  - id: city_panel
    content: Implementera city_panel.py med lista, lägg till/ta bort städer (geocoding + manuell)
    status: completed
    dependencies:
      - main_window
      - geocoding
      - db_manager
  - id: weather_panel
    content: Implementera weather_panel.py för att visa aktuell väderdata med AQI färgkodning
    status: completed
    dependencies:
      - main_window
  - id: tabs
    content: Skapa alla tabs (history_tab.py med pyqtgraph, stats_tab.py, api_status_tab.py, logs_tab.py)
    status: completed
    dependencies:
      - main_window
      - analytics
  - id: controller
    content: Implementera weather_controller.py som kopplar GUI, providers, database och analytics
    status: completed
    dependencies:
      - api_providers
      - db_manager
      - analytics
      - main_window
  - id: scheduler
    content: Implementera update_scheduler.py med QTimer för auto-update (10 min) och manual trigger
    status: completed
    dependencies:
      - controller
  - id: logger
    content: Skapa logger.py för strukturerad logging till fil och GUI logs-tab
    status: completed
  - id: requirements
    content: Skapa requirements.txt med alla dependencies (PyQt5, requests, pyqtgraph, etc.)
    status: completed
  - id: main_entry
    content: Skapa main.py som entry point och initialiserar applikationen
    status: completed
    dependencies:
      - controller
      - scheduler
      - logger
---

# Väderapplikation - Produktionsklar Arkitektur

## Arkitekturöversikt

```
GUI Layer (PyQt5)
    ↓
Controller Layer (MVC)
    ↓
API Abstraction Layer (Provider Pattern)
    ↓
Database Layer (SQLite)
    ↓
Analytics Engine
```

## Filstruktur

```
weather_app/
├── main.py                 # Entry point
├── config.json             # API keys, settings (dynamisk)
├── requirements.txt        # Dependencies
├── README.md               # Dokumentation
├── gui/
│   ├── __init__.py
│   ├── main_window.py      # Huvudfönster (PyQt5)
│   ├── city_panel.py       # Vänsterpanel (stadlista)
│   ├── weather_panel.py    # Huvudpanel (aktuell väder)
│   ├── history_tab.py      # Historik-flik (grafer)
│   ├── stats_tab.py        # Statistik-flik
│   ├── api_status_tab.py   # API Status-flik
│   └── logs_tab.py         # Loggar-flik
├── controllers/
│   ├── __init__.py
│   ├── weather_controller.py  # Huvudcontroller (MVC)
│   └── update_scheduler.py    # Timer-hantering
├── providers/
│   ├── __init__.py
│   ├── base_provider.py       # Abstract base class
│   ├── openmeteo_provider.py  # Open-Meteo API
│   ├── openweather_provider.py # OpenWeatherMap API
│   └── openaq_provider.py     # OpenAQ API
├── database/
│   ├── __init__.py
│   ├── db_manager.py          # SQLite operations
│   └── schema.sql             # Database schema
├── analytics/
│   ├── __init__.py
│   ├── analyzer.py            # Analysmotor (kallast, varmast, AQI)
│   └── statistics.py          # Statistikkalkulationer
└── utils/
    ├── __init__.py
    ├── config_loader.py       # Läser config.json dynamiskt
    ├── geocoding.py           # Geocoding för städer
    └── logger.py              # Logging system
```

## Databasschema (SQLite)

**Tabell: cities**

- id (INTEGER PRIMARY KEY)
- name (TEXT UNIQUE)
- latitude (REAL)
- longitude (REAL)
- created_at (DATETIME)

**Tabell: weather_data**

- id (INTEGER PRIMARY KEY)
- city_id (INTEGER, FOREIGN KEY)
- temperature (REAL)
- humidity (REAL)
- wind_speed (REAL)
- aqi (REAL, nullable)
- timestamp (DATETIME)
- source (TEXT) -- 'openmeteo', 'openweather', 'openaq'
- INDEX på (city_id, timestamp) för prestanda

**Tabell: daily_stats**

- id (INTEGER PRIMARY KEY)
- date (DATE UNIQUE)
- coldest_city_id (INTEGER)
- warmest_city_id (INTEGER)
- best_air_quality_city_id (INTEGER)
- worst_air_quality_city_id (INTEGER)

## API Provider Pattern

Varje provider implementerar `WeatherProvider` interface:

- `get_current_weather(lat, lon)` → dict med standardiserad struktur
- `get_air_quality(lat, lon)` → AQI data
- `is_available()` → health check

**Standardiserad data-struktur:**

```python
{
    'temperature': float,
    'humidity': float,
    'wind_speed': float,
    'aqi': float | None,
    'timestamp': datetime,
    'source': str
}
```

## GUI Layout (PyQt5)

**Huvudfönster:**

- Vänsterpanel: Stadlista med +/-, valbar lista
- Huvudpanel: Aktuell temperatur, AQI (färgkodad), uppdateringstid
- Toolbar: "Hämta nu"-knapp, Auto-update toggle
- Tabs: Historik, Statistik, API Status, Loggar

**Komponenter:**

- QListWidget för städer
- QLabel för väderdata (dynamiskt uppdaterad)
- QTabWidget för flikar
- QTimer för auto-update (10 min = 600000 ms)
- pyqtgraph för grafer (snabbare än matplotlib)

## Konfigurationshantering

**config.json struktur (skapas vid första körningen):**

```json
{
    "api_keys": {
        "openweather": "a7d54503575126c7c1c3e5c1a6d7e6dc",
        "openaq": "36daa4332a8376d8fef21e7e0c4ff4ec69dc559471c5dde6c0b5e882f16e94c4"
    },
    "settings": {
        "auto_update_interval_minutes": 10,
        "data_retention_days": 90,
        "default_cities": []
    }
}
```

**Viktigt:**

- API-nycklar laddas dynamiskt från config.json vid startup
- Ingen hardcoding av API-nycklar i koden
- config_loader.py skapar default config.json om den saknas (med angivna nycklar)
- Användare kan uppdatera API-nycklar direkt i config.json utan att ändra kod
- Open-Meteo kräver ingen API-nyckel (gratis utan autentisering)

## Dataflöde

1. **Stad tillägg:**

   - Användare anger namn → geocoding API → lat/lon → sparas i DB
   - Eller manuellt: namn + lat/lon → sparas direkt

2. **Väderinsamling:**

   - Controller itererar alla städer i DB
   - För varje stad: parallella API-calls till alla providers (Open-Meteo, OpenWeatherMap, OpenAQ)
   - API-nycklar laddas dynamiskt från config.json (OpenWeather: a7d54503575126c7c1c3e5c1a6d7e6dc, OpenAQ: 36daa4332a8376d8fef21e7e0c4ff4ec69dc559471c5dde6c0b5e882f16e94c4)
   - Aggregera data (prioritera Open-Meteo, fallback till andra)
   - Validera data → spara i weather_data
   - Uppdatera GUI

3. **Analys:**

   - SQL queries på weather_data
   - Kalkulera: kallast, varmast, bäst/sämst AQI
   - Uppdatera daily_stats
   - Visa i Statistik-flik

## Automatisk Uppdatering

- QTimer med konfigurerbart intervall (default 10 min)
- Kan pausas/aktiveras via GUI toggle
- Manual trigger via "Hämta nu"-knapp
- Statusindikator: "Senaste uppdatering: HH:MM:SS"

## Analysmotor

**Funktioner:**

- `find_coldest_city(timeframe)` → SQL MIN(temperature)
- `find_warmest_city(timeframe)` → SQL MAX(temperature)
- `find_best_air_quality(timeframe)` → SQL MIN(aqi)
- `find_worst_air_quality(timeframe)` → SQL MAX(aqi)
- `get_trend_24h(city_id)` → temperaturtrend senaste 24h

**Timeframes:** '1h', '24h', 'today', 'week'

## Felhantering

- API-fel: loggas, fortsätt med andra providers
- Databasfel: rollback, visa felmeddelande i GUI
- Nätverksfel: retry logic (3 försök med exponential backoff)
- Inga tysta fallbacks - allt loggas i Loggar-flik

## Prestanda

- Index på (city_id, timestamp) i weather_data
- Automatisk cleanup: radera data äldre än X dagar (konfigurerbart)
- Parallella API-calls med asyncio eller threading
- Lazy loading av grafer (laddas först när flik öppnas)

## Implementation Order

1. Database layer (schema + db_manager)
2. Config loader (dynamisk läsning + skapar default config.json med API-nycklar)
3. API providers (base + implementations med dynamisk API-key loading)
4. Controller (koppla ihop allt)
5. GUI (stegvis: huvudfönster → panels → tabs)
6. Analytics engine
7. Auto-update scheduler
8. Testing & polish

## API-nycklar (Dynamisk Hantering)

**OpenWeatherMap API Key:** `a7d54503575126c7c1c3e5c1a6d7e6dc`

- Används i openweather_provider.py
- Laddas från config.json["api_keys"]["openweather"]
- Valideras vid provider-initiering

**OpenAQ API Key:** `36daa4332a8376d8fef21e7e0c4ff4ec69dc559471c5dde6c0b5e882f16e94c4`

- Används i openaq_provider.py
- Laddas från config.json["api_keys"]["openaq"]
- Valideras vid provider-initiering

**Open-Meteo:** Ingen API-nyckel krävs (gratis utan autentisering)

**Säkerhet:**

- config.json ska läggas till .gitignore (om version control används)
- API-nycklar laddas endast vid runtime från config.json
- Inga API-nycklar hardkodas i Python-filer