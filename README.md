# Väderapplikation

En produktionsklar väderapplikation byggd med PyQt5 som samlar väderdata och luftkvalitetsdata från flera gratis API-källor. Applikationen lagrar data lokalt i en SQLite-databas och ger användaren detaljerad statistik, varningar och historik.

## Funktioner

### 🌡️ Väderdata
- **Temperatur, luftfuktighet och vindhastighet** från flera städer
- **Automatisk eller manuell uppdatering** av väderdata
- **Historik och trender** för varje stad

### 🌫️ Luftkvalitet (PM2.5, PM10, NO₂, O₃)
- **Rådata för luftföroreningar** i µg/m³
- **Dynamisk AQI-beräkning** baserad på 24-timmars rullande medelvärde (US EPA-standard)
- **Inga fallback-värden** - visar endast verklig data eller "Ingen data"
- **Varningar** för farliga luftkvalitetsnivåer

### 📊 Statistik och Analys
- **Ranking**: Kallast/varmast stad, bäst/sämst luftkvalitet
- **Översikt**: Snittvärden över alla städer med totala datapunkter
- **Varningar**: Nationella och regionala varningar för farliga PM2.5-nivåer
- **Historik**: Grafisk visning av historiska data
- **Grafgenerering**: Exportera grafer i olika tidsperioder (Daglig, Veckovis, Månadsvis, Årlig)
- **Real-time GUI**: Automatisk uppdatering av GUI var 5:e sekund (oberoende av auto-update)

### 🏙️ Städer
- **Hantera flera städer** (stöd för 40+ städer)
- **Automatisk geokodning** av stadsnamn
- **Lägg till/ta bort städer** dynamiskt

### 📍 Analytisk Karta och Stationer
- **Interaktiv Leaflet-karta** med tre lager: Stationer, Heatmap, Sensorer
- **Färgkodade AQI-markörer**: Cirkelmarkörer färgas dynamiskt via `WarningDetector`, yttre grå ring = vindhastighet
- **Täthetsmedveten heatmap**: Interpoleringsradien anpassas per station; glesbebyggda områden märks med varningsbadge
- **Analytiska popups**: 24h PM2.5-sparkline (inline SVG), inversionsriskpoäng 0–100 med mätarbar, kalibrerings-metadata
- **Regional klusteranalys**: Identifierar regional PM2.5-påverkan relativt nationellt 7-dagarsmedelvärde; banner visas på kartan
- **Inversionsriskmodell v3**: Probabilistisk poäng, winsoriserade p5/p95-gränser, temporalt stabil, null-safe
- **Custom markers**: Högerklicka på kartan för att lägga till egna markörer (sparas i databasen)
- **Debug-läge**: Exponerar råvärden, normaliserade värden, `deviation_factor` och `inversion_model_version` i popupsen
- **PyQtWebEngine**: Krävs för kartan (`pip install PyQtWebEngine`)

## Teknisk Arkitektur

### API-källor
Applikationen använder tre gratis API-källor för redundans och komplett data:

1. **Open-Meteo** (Primär)
   - Väderdata (temperatur, luftfuktighet, vind)
   - Ingen API-nyckel krävs

2. **OpenWeatherMap** (Backup)
   - Väderdata och kategorisk AQI
   - Kräver gratis API-nyckel

3. **OpenAQ** (Luftkvalitet)
   - Rådata för PM2.5, PM10, NO₂, O₃
   - Kräver gratis API-nyckel
   - Rate limit-hantering: 60 requests/minut, 2000 requests/timme

### Databas
- **SQLite** för lokal lagring
- **Schema**: Städer, väderdata, daglig statistik, sensorer
- **Lagrar rådata**: PM2.5, PM10, NO₂, O₃ i µg/m³
- **24-timmars rullande medelvärden** för AQI-beräkning
- **Intelligent lagring**: Undviker duplicering baserat på measurement timestamps från API:er
- **Sensor-hantering**: Lagrar OpenAQ sensor-ID, koordinater och senaste värden

### GUI
- **PyQt5** för användargränssnitt
- **MVC-arkitektur** (Model-View-Controller)
- **Flikar**: Historik, Statistik, Översikt, Varningar, Stationer, API Status, Loggar
- **Real-time uppdatering**: GUI uppdateras automatiskt var 5:e sekund
- **Grafgenerering**: Mode-baserad grafgenerering via menubar (Daglig, Veckovis, Månadsvis, Årlig)
- **Thread-safety**: Grafgenerering körs i bakgrundstråd för att hålla GUI responsivt

### Rate Limiting
- **Automatisk rate limit-hantering** för OpenAQ och OpenWeatherMap
- **Proaktiv väntning** när gränser närmar sig
- **Automatisk retry** vid 429-fel
- **Sensor-caching** för att minska API-anrop

## Installation

### Krav
- Python 3.7 eller senare
- PyQt5
- requests
- sqlite3 (ingår i Python)

### Installera beroenden
```bash
pip install -r requirements.txt
```

Detta installerar:
- PyQt5 (GUI)
- PyQtWebEngine (för interaktiv karta i Stationer-fliken)
- requests (API-anrop)
- matplotlib (grafer)
- pandas (datahantering)
- python-dotenv (miljövariabler)
- numpy (numeriska beräkningar)
- zoneinfo (tidszoner)

**OBS:** PyQtWebEngine är nu ett krav för att kartan ska fungera. Om installationen misslyckas, se felsökningssektionen nedan.

### Konfiguration

#### Steg 1: Kopiera .env.example
```bash
cp .env.example .env
```

#### Steg 2: Fyll i dina API-nycklar
Öppna `.env` filen och ersätt placeholder-värdena med dina faktiska API-nycklar:

```env
OPENWEATHER_API_KEY=din_faktiska_openweather_nyckel
OPENAQ_API_KEY=din_faktiska_openaq_nyckel
```

**VIKTIGT:** `.env` filen är redan i `.gitignore` och kommer INTE att laddas upp till GitHub.

#### Steg 3: (Valfritt) config.json som fallback
Om du föredrar att använda `config.json` istället för `.env`, skapa en `config.json` fil.
API-nycklar kan också hanteras via **Hjälp → Inställningar → API-nycklar** direkt i GUI:t.

```json
{
  "api_keys": {
    "openweather": "din-openweather-api-nyckel",
    "openaq": "din-openaq-api-nyckel"
  },
  "settings": {
    "auto_update_interval_minutes": 10,
    "data_retention_days": 90,
    "dark_mode": false,
    "temperature_unit": "C",
    "map_default_layer": "stations",
    "heatmap_opacity": 70,
    "inversion_model_version": 3,
    "debug_mode": false
  }
}
```

**OBS:** Nya inställningsnycklar slås samman vid uppgradering utan att befintliga värden skrivs över (`setdefault`-merge).

**Prioritet:** API-nycklar läses i följande ordning:
1. `.env` fil (högsta prioritet)
2. `config.json` fil (fallback)
3. Ingen nyckel (applikationen fungerar men vissa API:er kan saknas)

### API-nycklar

#### OpenWeatherMap
1. Gå till https://openweathermap.org/api
2. Skapa ett gratis konto
3. Kopiera din API-nyckel
4. Lägg till i `.env` som `OPENWEATHER_API_KEY=din_nyckel`

#### OpenAQ
1. Gå till https://openaq.org/#/api
2. Skapa ett konto
3. Generera en API-nyckel
4. Lägg till i `.env` som `OPENAQ_API_KEY=din_nyckel`

**OBS:** Open-Meteo kräver ingen API-nyckel och fungerar direkt.

## Användning

### Starta applikationen
```bash
python main.py
```

### Funktioner i GUI

#### Verktygsfält
- **"Hämta nu"** (F5): Manuell uppdatering av all väderdata
- **"Auto-uppdatering"**: Toggle för automatisk uppdatering (på som standard, 10 minuters intervall)

#### Menubar
- **Generera**: Exportera grafer i olika tidsperioder
  - **Daglig**: Timme-för-timme graf för valt datum
  - **Veckovis**: Veckodata grupperat per dag
  - **Månadsvis**: Månadsdata grupperat per vecka
  - **Årlig**: Årsdata grupperat per månad
- Grafer exporteras till `output/` katalogen
- Grafgenerering körs i bakgrundstråd (GUI förblir responsiv)
- **Hjälp → Inställningar**: Öppnar inställningsdialogen

#### Vänsterpanel
- **Lista över städer**: Klicka på en stad för att se detaljerad information
- **"Lägg till stad"**: Lägg till en ny stad
- **"Ta bort stad"**: Ta bort vald stad

#### Huvudpanel
- **Aktuell väderdata**: Temperatur, luftfuktighet, vindhastighet
- **Luftkvalitet**: PM2.5, PM10, NO₂, O₃ (rådata i µg/m³)

#### Flikar

**Historik**
- Välj stad från dropdown
- Se historiska data för temperatur, luftfuktighet, vind och luftkvalitet
- **Dynamiska parametrar**: Alla tillgängliga parametrar från databasen visas automatiskt

**Statistik**
- Kallast/varmast stad
- Bäst/sämst luftkvalitet (baserat på PM2.5)
- Rankings baserat på senaste 24 timmarna

**Översikt**
- Snittvärden över alla städer
- Snitttemperatur, luftfuktighet, vindhastighet
- Snitt PM2.5 och beräknad AQI
- Välj mellan "Senaste värden" och "24h snitt"
- **Totala datapunkter**: Visar totalt antal sparade mätningar i databasen
- **Antal städer**: Visar antal städer i databasen
- **Korrekt aggregering**: Snittvärden beräknas med lika vikt per stad (inte per datapunkt)

**Varningar**
- **Nationell översikt**: Snitt PM2.5 och AQI över alla städer
- **Regionala varningar**: Städer med farliga PM2.5-nivåer
- **Top 10 städer**: Städer med högst PM2.5-värden
- **Färgkodning**: Visuell indikering av varningsnivåer
  - 🟢 Grön: Bra (PM2.5 ≤ 12.0 µg/m³)
  - 🟡 Gul: Acceptabelt (12.1-35.4 µg/m³)
  - 🟠 Orange: För känsliga (35.5-55.4 µg/m³)
  - 🔴 Röd: Ohälsosamt (55.5-150.4 µg/m³)
  - 🟣 Lila: Mycket ohälsosamt (150.5-250.4 µg/m³)
  - ⚫ Mörkröd: Farligt (>250.4 µg/m³)

**Stationer (Analytisk Karta)**
- **Layer-toolbar**: Stationer / Heatmap / Sensorer — ett aktivt lager åt gången
- **AQI-markörer**: Färg från `WarningDetector.get_threshold_metadata()`, yttre ring = vindhastighet
- **Heatmap**: Täthetsmedveten interpolering, low-density varningsbadge i glesbefolkade regioner
- **Analytiska popups**: PM2.5 24h sparkline, inversionsrisk 0–100, kalibrerings-metadata
- **Klustervarningsbanner**: Visas automatiskt vid regional avvikelse från nationellt 7d-snitt
- **Custom markers**: Högerklicka → formulär → sparas i databasen
- **Debug-läge**: Aktiveras i Inställningar → Debug; exponerar rådata i popupsen
- **Krav**: PyQtWebEngine måste vara installerat

**API Status**
- Status för alla API-källor
- Visar om API-nycklar är konfigurerade

**Loggar**
- Systemloggar för felsökning
- Visar API-anrop, fel och varningar

## AQI-beräkning

Applikationen använder **US EPA-standard** för AQI-beräkning:

- **Baseras på 24-timmars rullande medelvärde** av PM2.5
- **Inga fallback-värden**: Om data saknas visas "Ingen data"
- **Dynamisk beräkning**: AQI beräknas från rådata, inte lagras permanent

### AQI-brytpunkter (PM2.5)
- **0-50**: Bra (0.0-12.0 µg/m³)
- **51-100**: Acceptabelt (12.1-35.4 µg/m³)
- **101-150**: För känsliga personer (35.5-55.4 µg/m³)
- **151-200**: Ohälsosamt (55.5-150.4 µg/m³)
- **201-300**: Mycket ohälsosamt (150.5-250.4 µg/m³)
- **301-500**: Farligt (>250.4 µg/m³)

## Databasstruktur

### Tabeller

**cities**
- `id`: Primärnyckel
- `name`: Stadsnamn
- `latitude`: Latitud
- `longitude`: Longitud

**weather_data**
- `id`: Primärnyckel
- `city_id`: Foreign key till cities
- `temperature`: Temperatur (°C)
- `humidity`: Luftfuktighet (%)
- `wind_speed`: Vindhastighet (m/s)
- `pm25`: PM2.5 (µg/m³)
- `pm10`: PM10 (µg/m³)
- `no2`: NO₂ (µg/m³)
- `o3`: O₃ (µg/m³)
- `timestamp`: Tidsstämpel (collector timestamp eller measurement timestamp från API)
- `source`: API-källa

**sensors**
- `id`: Primärnyckel
- `city_id`: Foreign key till cities
- `sensor_id`: OpenAQ sensor ID (eller NULL för custom markers)
- `parameter`: Parameter (PM2.5, PM10, NO2, O3) eller NULL för custom markers
- `latitude`: Latitud
- `longitude`: Longitud
- `last_value`: Senaste mätvärde (eller NULL för custom markers)
- `last_updated`: Senaste uppdateringstid
- `is_custom`: Flagga för custom markers (0 = OpenAQ sensor, 1 = custom marker)
- `custom_info`: JSON med custom marker-information

**daily_stats**
- `date`: Datum
- `coldest_city`: Kallast stad
- `warmest_city`: Varmast stad
- `best_air_quality`: Bäst luftkvalitet
- `worst_air_quality`: Sämst luftkvalitet

## Rate Limiting

### OpenAQ
- **60 requests per minut**
- **2000 requests per timme**
- Automatisk väntning när gränser närmar sig
- Sensor-caching för att minska anrop

### OpenWeatherMap
- **60 requests per minut**
- **2000 requests per timme** (konservativt)
- Automatisk retry vid 429-fel

## Loggning

Alla loggar sparas i `logs/` katalogen:
- **Strukturerad loggning** till fil
- **Konsol-output** för debugging
- **GUI-integration** i Loggar-fliken

## Tekniska Förbättringar (2026)

### Dynamisk Parameter-Upptäckt
- **Ingen hardcoding**: Parametrar (pm25, pm10, no2, o3, temperature, wind_speed, humidity) upptäcks automatiskt från databasschema
- **Schema-baserad**: Använder `PRAGMA table_info()` för att upptäcka tillgängliga kolumner
- **Logisk sortering**: Parametrar sorteras automatiskt (pollutants först, sedan väderparametrar)
- **Fungerar för alla städer**: Inklusive Umeå och andra städer med varierande datatillgänglighet

### Korrekt Nationellt Snitt
- **Tidsstegsviktat medelvärde**: Varje stad har lika vikt per tidssteg
- **Tvåstegs-aggregation**: Först aggregeras per stad per tidssteg, sedan över städer
- **Ingen datapunkt-dominans**: Städer med fler datapunkter dominerar inte resultatet
- **Validering**: Loggar antal städer per tidssteg för datakvalitetskontroll
- **Hantering av saknad data**: NaN-värden exkluderas korrekt per parameter

### Event-Driven UI Refresh
- **Signal-baserad**: Använder PyQt `data_updated` signal för thread-safe uppdateringar
- **Ingen timer-baserad refresh**: UI uppdateras endast när ny data faktiskt sparas
- **Auto-update som standard**: Automatisk uppdatering är aktiverad vid start (10 minuters intervall)
- **Debouncing**: Flera samtidiga uppdateringar debouncas till en enda UI-refresh

### Förbättrad Datahantering
- **Alltid spara pollutants**: Pollutant-värden sparas alltid, även om de är identiska (säkerställer UI-uppdateringar)
- **Prioriterad hämtning**: `get_latest_weather()` prioriterar rader med pollutant-data
- **Ingen aggressiv deduplicering**: Identiska värden sparas med ny timestamp för att säkerställa aktuell data

## Nya Funktioner (2026)

### Grafgenerering
- **Mode-baserad arkitektur**: Polymorf design för olika tidsperioder
- **Daglig mode**: Timme-för-timme graf för valt datum (0-23 timmar)
- **Veckovis/Månadsvis/Årlig**: Aggregerad data per period
- **Menubar-integration**: Dynamisk menubar byggd från MODES dictionary
- **Bakgrundstråd**: Grafgenerering körs i QThread för att hålla GUI responsivt
- **Export**: Grafer sparas i `output/` katalogen med timestamp
- **Inga fallbacks**: Om data saknas returneras None, ingen tom graf genereras
- **Dynamisk parameter-upptäckt**: Parametrar upptäcks automatiskt från databasschema (ingen hardcoding)
- **Korrekt nationellt snitt**: Nationellt snitt använder tidsstegsviktat medelvärde där varje stad har lika vikt

### Analytisk Karta och Stationer
- **Interaktiv Leaflet-karta** med tre lager (Stationer, Heatmap, Sensorer)
- **AQI-markörer**: Färg dynamiskt från `WarningDetector.get_threshold_metadata()` — ingen hårdkodad hex-värde i GUI-koden
- **Täthetsmedveten heatmap**: Interpoleringsradius skalas med grannstationsantal; `low_density`-flagga ger varningsbadge i sparsamma regioner
- **Analytiska popups**: Inline SVG-sparkline, inversionsriskpoäng 0–100 med mätarbar, kalibrerings-metadata (N mätningar, p5–p95 gränser)
- **Regional klusteranalys**: `deviation_factor` härleds från `WarningDetector.THRESHOLDS` — uppdateras automatiskt vid WHO/EPA-revisioner
- **Inversionsriskmodell v3**: Winsoriserade p5/p95-gränser, temporalt stabila poäng, null-safe
- **Debug-läge**: Konfigureras i Inställningar; exponerar `wind_norm`, `hum_norm`, `national_baseline`, `deviation_factor`, `inversion_model_version`
- **Database-first**: Alla sensorer och custom markers lagras i databasen

### Inställningar (Settings Dialog)
- **5-flik inställningsdialog** tillgänglig via Hjälp → Inställningar
- **Utseende**: Mörkt läge (full QSS-tema), temperaturenhet (°C/°F)
- **Karta**: Standard kartlager, heatmap opacitet (0–100)
- **Data**: Auto-update intervall, datalagring (dagar)
- **API-nycklar**: OpenWeatherMap och OpenAQ (maskerade fält, sparas i `config.json`)
- **Debug**: Debug-läge toggle för analytisk transparens
- Alla värden läses från `ConfigLoader` vid öppning — inga hårdkodade defaults i dialogen
- Atomär `update_config()` på OK — inget partiellt tillstånd
- Sekvenserade sidoeffekter vid stängning: `apply_theme` → `pause_auto_update` → `load_map` → `restart_auto_update`

### WarningDetector.get_threshold_metadata()
- Ny `@staticmethod` som returnerar en ordnad `List[Dict]` med threshold/färg/namn/AQI-range för alla nivåer
- Kräver ingen instans och ingen databas
- Enda stabila publika API:t för alla konsumenter som behöver tröskeldata (HelpDialog, framtida komponenter)
- Uppdateringar i `THRESHOLDS` sprids automatiskt till alla konsumenter

### Intelligent Data Storage
- **Measurement timestamps**: Använder API:ernas faktiska measurement timestamps
- **Deduplicering**: Undviker att spara samma mätning flera gånger baserat på measurement timestamps
- **Alltid spara pollutants**: Pollutant-värden sparas alltid, även om de är identiska (för att säkerställa UI-uppdateringar)
- **Separat hantering**: Väderdata och luftkvalitetsdata hanteras separat
- **Prioriterad hämtning**: `get_latest_weather()` prioriterar rader med pollutant-data

### Event-Driven UI Refresh
- **Event-driven uppdatering**: GUI uppdateras endast när ny data faktiskt sparas till databasen
- **Automatisk uppdatering**: Auto-update är aktiverad som standard (10 minuters intervall)
- **Ingen timer-baserad refresh**: UI uppdateras inte om ingen ny data finns
- **Signal-baserad**: Använder PyQt signals för thread-safe UI-uppdateringar

### Data Points Count
- **Korrekt räkning**: Visar totalt antal rader i weather_data tabellen
- **Dynamisk**: Uppdateras automatiskt när ny data läggs till
- **Felhantering**: Tydlig skillnad mellan fel (None) och tom tabell (0)

## Designprinciper

### Inga Fallbacks
- **Inga hårdkodade värden**: Alla värden kommer från API:er eller databasen
- **Inga hårdkodade parametrar**: Parametrar (pm25, pm10, no2, o3, etc.) upptäcks dynamiskt från databasschema
- **"Ingen data"**: Om data saknas visas detta tydligt
- **Transparent**: Användaren ser exakt vad som händer
- **No data is better than mock data**: Inga mock-värden eller fallback-data

### Dynamisk
- **Inga hårdkodade städer**: Lägg till/ta bort städer dynamiskt
- **Inga hårdkodade parametrar**: Alla parametrar upptäcks från databasschema
- **Flexibel konfiguration**: Alla inställningar i config.json eller .env
- **Anpassningsbar**: Lätt att lägga till nya API-källor eller parametrar
- **Mode-baserad arkitektur**: Grafgenerering byggd på polymorf design
- **Dynamisk parameter-ordning**: Parametrar sorteras logiskt (pollutants först, sedan väder)

### Produktionsredo
- **Felhantering**: Robust hantering av API-fel, nätverksfel, databasfel
- **Thread-safety**: Thread-safe databashantering
- **Rate limiting**: Skydd mot API-rate limits
- **Loggning**: Omfattande loggning för felsökning

## Dokumentation

### Detaljerad Teknisk Dokumentation

- **[API Retrieval and Data Flow](docs/API_AND_DATA_FLOW.md)** — API-providers, datahämtning, deduplicering, timestamp-hantering, rate limiting, dataflödesdiagram
- **[Analytical Map](docs/ANALYTICAL_MAP.md)** — `MapDataBuilder`, inversionsriskmodell v3, klusteranalys, täthetsmedveten heatmap, DB-frågor, JavaScript-lager, null-policy
- **[Settings Dialog](docs/SETTINGS.md)** — `SettingsDialog`, `apply_theme()`, alla config-nycklar, sekvenserade sidoeffekter, config-merge-säkerhet

## Utveckling

### Projektstruktur
```
Weather app/
├── main.py                 # Applikationsstart
├── .env                    # API-nycklar (EJ i version control)
├── .env.example            # Mall för .env (I version control)
├── config.json            # Konfiguration (valfritt, EJ i version control)
├── weather.db             # SQLite-databas (EJ i version control)
├── logs/                  # Loggfiler (EJ i version control)
├── controllers/           # Controller-lager
│   ├── weather_controller.py
│   └── update_scheduler.py
├── providers/             # API-providers
│   ├── base_provider.py
│   ├── openmeteo_provider.py
│   ├── openweather_provider.py
│   └── openaq_provider.py
├── database/             # Databashantering
│   ├── db_manager.py
│   └── schema.sql
├── analytics/            # Analys och statistik
│   ├── analyzer.py
│   ├── statistics.py
│   ├── warnings.py
│   ├── graph_generator.py
│   └── graph_modes.py
├── gui/                  # GUI-komponenter
│   ├── main_window.py
│   ├── city_panel.py
│   ├── weather_panel.py
│   ├── history_tab.py
│   ├── stats_tab.py
│   ├── averages_tab.py
│   ├── warnings_tab.py
│   ├── stations_tab.py    # Analytisk karta (MapDataBuilder, Leaflet JS)
│   ├── help_dialog.py     # Hjälpdialog (6 flikar, dynamisk AQI-tabell)
│   ├── settings_dialog.py # Inställningsdialog + apply_theme()
│   ├── api_status_tab.py
│   └── logs_tab.py
├── docs/                  # Teknisk dokumentation
│   ├── ANALYTICAL_MAP.md  # Kartarkitektur, inversion, kluster, DB-frågor
│   ├── SETTINGS.md        # Settings dialog, config-nycklar, tema
│   └── API_AND_DATA_FLOW.md
└── utils/                # Hjälpfunktioner
    ├── logger.py
    ├── config_loader.py   # DEFAULT_CONFIG + setdefault-merge
    ├── rate_limiter.py
    └── aqi_calculator.py
```

### Lägga till ny API-källa
1. Skapa ny provider-klass som ärver från `WeatherProvider`
2. Implementera `get_current_weather()` och `get_air_quality()`
3. Lägg till provider i `WeatherController`
4. Providern integreras automatiskt i systemet

## Felsökning

### Applikationen startar inte
- Kontrollera att alla beroenden är installerade
- Kontrollera `config.json` för korrekt formatering
- Kolla loggfiler i `logs/` katalogen

### Inga väderdata
- Kontrollera API-nycklar i `config.json`
- Kolla API Status-fliken i GUI
- Kontrollera nätverksanslutning
- Kolla loggfiler för API-fel

### Rate limit-fel
- Applikationen hanterar detta automatiskt
- Om problem kvarstår: Öka väntetid mellan uppdateringar i config

### Heatmap renderas inte
- **Symptom**: `js: Uncaught IndexSizeError: Failed to execute 'getImageData' ... source width is 0`
- **Orsak**: `leaflet.heat` försöker rita på canvas innan Qt:s layout-motor har tilldelat pixeldimensioner
- **Lösning**: Heatmap-skapandet är fördröjt 300 ms med `setTimeout` + `map.invalidateSize()` för att tvinga Leaflet att fråga om behållarens dimensioner från Qt innan canvasen berörs — detta är redan implementerat

### Inversion score visas inte (null)
- Kräver minst 20 historiska rader för `wind_speed` och `humidity`
- Kontrollera "Historik < 20 rader" i stationspopupen
- Samla in mer data, sedan laddas om kartan automatiskt

## Licens

Detta projekt är skapat för personligt bruk och utbildning.

## Kontakt

För frågor eller problem, kontrollera loggfiler i `logs/` katalogen för detaljerad information.
