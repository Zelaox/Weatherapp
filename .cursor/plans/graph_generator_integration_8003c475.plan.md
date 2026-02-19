---
name: Graph Generator Integration
overview: "Skapa en analytics-modul för grafgenerering som integreras i toolbar och följer systemets designprinciper: inga hårdkodade värden, inga fallbacks, endast verklig data från databasen."
todos:
  - id: extend-db-manager
    content: Utöka DatabaseManager med get_weather_data_for_city() och get_all_weather_data() metoder som stödjer tidsbaserad filtrering (inte datapunktsbaserad)
    status: completed
  - id: create-graph-generator
    content: Skapa analytics/graph_generator.py med GraphGenerator klass som följer designprinciperna
    status: completed
    dependencies:
      - extend-db-manager
  - id: implement-city-graph
    content: Implementera generate_city_graph() med dynamiskt grid (en subplot per parameter, ingen dual-axis, minimal styling)
    status: completed
    dependencies:
      - create-graph-generator
  - id: implement-national-graph
    content: Implementera generate_national_graph() med groupby timestamp och mean aggregation, använd tidsbaserad filtrering (inte datapunktsbaserad)
    status: completed
    dependencies:
      - create-graph-generator
  - id: create-worker-thread
    content: Skapa QThread worker för grafgenerering i gui/main_window.py för att inte frysa UI
    status: completed
    dependencies:
      - create-graph-generator
  - id: integrate-toolbar
    content: Lägg till Generera grafer-knapp i toolbar i gui/main_window.py som använder worker thread
    status: completed
    dependencies:
      - create-worker-thread
  - id: update-requirements
    content: Lägg till matplotlib och pandas i requirements.txt om de saknas
    status: completed
  - id: update-analytics-init
    content: Uppdatera analytics/__init__.py för att exportera GraphGenerator
    status: completed
    dependencies:
      - create-graph-generator
---

# Grafgenerator Integration

## Översikt

Skapa en dynamisk grafgenerator-modul i `/analytics/` som genererar grafer från verklig databasdata. Modulen ska integreras i toolbar och följa systemets strikta designprinciper: inga hårdkodade värden, inga fallbacks, endast verklig data.

## Arkitektur

### Datakälla

- Använd `database/db_manager.py` (inte direkt SQLite)
- Utöka `DatabaseManager` med metoder för att hämta all väderdata
- Ingen direkt SQL i grafmodulen

### Modulstruktur

```
analytics/
├── graph_generator.py  # Ny modul
└── __init__.py        # Uppdatera för export
```

## Implementation

### 1. Utöka DatabaseManager

Lägg till metoder i `database/db_manager.py`:

- `get_weather_data_for_city(city_id: int, hours: Optional[int] = None) -> List[Dict]`
  - Returnerar väderdata för en stad
  - **Standardbeteende**: Om `hours=None`: ALL väderdata (ingen tidsbegränsning)
  - Om `hours` angivet: Filtrera tidsbaserat: `timestamp >= now - timedelta(hours=hours)`
  - **VIKTIGT**: Tidsbaserad filtrering, INTE datapunktsbaserad (inte `.iloc[-24]`)
  - **VIKTIGT**: Inget implicit standardintervall - antingen ALL data (None) eller explicit hours
  - Sorterad på timestamp ASC
  - Returnerar tom lista om ingen data finns

- `get_all_weather_data(hours: Optional[int] = None) -> List[Dict]`
  - Returnerar väderdata från alla städer
  - **Standardbeteende**: Om `hours=None`: ALL väderdata (ingen tidsbegränsning)
  - Om `hours` angivet: Filtrera tidsbaserat: `timestamp >= now - timedelta(hours=hours)`
  - **VIKTIGT**: Tidsbaserad filtrering, INTE datapunktsbaserad
  - **VIKTIGT**: Inget implicit standardintervall - antingen ALL data (None) eller explicit hours
  - Inkluderar city_name via JOIN
  - Sorterad på timestamp ASC
  - Returnerar tom lista om ingen data finns

### 2. Skapa GraphGenerator

Ny fil: `analytics/graph_generator.py`

**Klassstruktur:**

```python
class GraphGenerator:
    def __init__(self, db_manager: DatabaseManager, output_dir: str = "output")
    
    def generate_city_graph(self, city_id: int, hours: Optional[int] = None) -> Optional[str]
    # Returnerar filväg eller None om ingen data
    # hours=None: ALL historik, hours=24: senaste 24 timmarna, etc.
    
    def generate_all_city_graphs(self, hours: Optional[int] = None) -> List[str]
    # Returnerar lista med filvägar
    # hours=None: ALL historik för alla städer
    
    def generate_national_graph(self, hours: Optional[int] = None) -> Optional[str]
    # Returnerar filväg eller None om ingen data
    # hours=None: ALL historik
```

**Designprinciper (Analysartefakt-tänk):**

- Inga hårdkodade städer - hämta dynamiskt via `db.get_all_cities()`
- Inga hårdkodade intervall - standardbeteende: ALL historik (hours=None), eller explicit hours-argument
- **VIKTIGT**: Inget implicit standardintervall - antingen ALL data eller explicit angivet intervall
- Inga fallback-värden - om data saknas → returnera None, logga, INTE rendera text i bilden
- Inga antaganden om kolumner - kontrollera dynamiskt vilka kolumner som finns
- Endast verklig data - plotta exakt vad som finns i databasen
- Minimal styling - svart linje, grid, ingen färglogik, ingen styling
- Ren analysartefakt - ingen dashboard-tänk
- **Tidsbaserad filtrering**: Använd alltid `timestamp >= cutoff_time`, INTE datapunktsbaserad (inte `.iloc[-N]`)
- **Dynamisk tidsfiltrering**: Om filtrering behövs, använd `datetime.now() - timedelta(hours=hours)`, inte antal datapunkter
- **Inga hårdkodade perioder**: Om period behövs, ska den vara parameter, inte hårdkodad i kod

**Stadsgraf layout (dynamiskt grid):**

- En subplot per parameter (PM2.5, PM10, NO2, O₃, temperature, wind_speed, humidity)
- Grid-layout beräknas dynamiskt baserat på antal parametrar med data
- Varje parameter får egen subplot (INGEN dual-axis)
- Layout: `ceil(sqrt(num_params))` kolumner, `ceil(num_params / cols)` rader
- Om parameter saknas i data → hoppa över subplot
- Titel: `{city_name} - {first_timestamp} to {last_timestamp}`

**Nationell graf:**

- Använd pandas DataFrame från `get_all_weather_data()`
- **VIKTIGT**: Konvertera timestamp-kolumner till datetime om de är strings
- Filtrera data tidsbaserat om intervall angivet: `df[df["timestamp"] >= cutoff_time]`
- `df.groupby("timestamp").mean(numeric_only=True)` för aggregering per timestamp
- Dynamiskt antal subplots baserat på vilka parametrar som finns i data
- Varje parameter får egen subplot (PM2.5, PM10, NO2, O₃, temperature, wind_speed, humidity)
- Samma dynamiska grid-layout som stadsgrafer
- Titel: `Sweden National Average - {first_timestamp} to {last_timestamp}`
- **Tidsbaserad filtrering**: Använd alltid `df[df["timestamp"] >= cutoff]`, INTE `df.iloc[-N:]`

**Renderingsregler (minimal styling, ren data):**

- Alla datapunkter plottas (ingen smoothing, ingen aggregation, ingen nedsampling)
- Y-axel: `data.min()` → `data.max()` (dynamiskt från data)
- **VIKTIGT**: Om all data är None för en parameter → returnera None, INTE sätta 0-1 (det är en fallback)
- X-axel: första → sista timestamp (dynamiskt från data)
- Sortering på timestamp (alltid ASC)
- Styling: svart linje (`color='black'`), grid aktiverat, ingen färglogik
- Inga färger, ingen styling, bara data
- Om ingen data → returnera None, logga att ingen data fanns, INTE rendera text i bilden
- Om parameter har data men alla värden är None → returnera None för den parametern, INTE plotta med 0-1

**Output:**

- `output/<city_name>_<export_timestamp>.png` (sanitized filnamn)
- `output/sweden_<export_timestamp>.png`
- Skapa `output/` katalog automatiskt om den inte finns
- Timestamp-format: `YYYYMMDD_HHMMSS`
- **Global export timestamp**: Alla grafer får samma timestamp vid export (spårbarhet)
- Timestamp genereras när `generate_all_city_graphs()` eller `generate_national_graph()` anropas

### 3. Integrering i GUI

**Toolbar-knapp i `gui/main_window.py`:**

Lägg till i `_create_toolbar()`:

```python
toolbar.addSeparator()

# Graph export button
graph_action = QAction("Generera grafer", self)
graph_action.triggered.connect(self._generate_graphs)
toolbar.addAction(graph_action)
```

Implementera `_generate_graphs()`:

- Skapa `QThread` worker för grafgenerering (för att inte frysa UI)
- Worker skapar `GraphGenerator` instans
- Worker anropar `generate_all_city_graphs(hours=None)` och `generate_national_graph(hours=None)`
- **Standardbeteende**: hours=None ger ALL historik (ingen tidsbegränsning)
- **VIKTIGT**: Inget implicit standardintervall - antingen ALL data (None) eller explicit hours
- Visa meddelande i status bar om lyckad/misslyckad generering
- Hantera fel gracefully (inga fallbacks, bara logga)
- Disable toolbar-knapp under generering, enable när klar

## Tekniska Detaljer

### Databehandling

- Använd pandas DataFrame för nationell graf (groupby)
- Använd matplotlib för rendering
- Thread-safe: GraphGenerator ska inte modifiera databasen
- Felhantering: Om databasfel → returnera None/tom lista, logga fel
- **Tidsbaserad filtrering**: Alltid använd `timestamp >= cutoff_time`, INTE datapunktsbaserad filtrering
- **Timestamp-hantering**: Konvertera timestamp-kolumner till datetime för korrekt filtrering
- **Dynamisk filtrering**: Om intervall behövs, använd `datetime.now() - timedelta(hours=hours)`, inte hårdkodade värden
- **Inga antaganden om sampling**: Fungera korrekt oavsett om data kommer varje timme, var 10:e minut, eller varierande intervall

### Filnamn-sanitization

- Ersätt ogiltiga tecken i stadsnamn: `/[<>:"|?*]/ `→ `_`
- Använd `pathlib.Path` för säker filsökvägshantering

### Kolumn-detektion

- Kontrollera dynamiskt vilka kolumner som finns i data
- Om parameter saknas → hoppa över subplot
- Beräkna grid-layout dynamiskt: `cols = ceil(sqrt(num_params))`, `rows = ceil(num_params / cols)`
- Endast parametrar med minst en datapunkt får subplot

### Tom data-hantering (INGA fallbacks)

- Om `get_weather_data_for_city()` returnerar tom lista → returnera None, logga, INTE generera graf
- Om `get_all_weather_data()` returnerar tom lista → returnera None från `generate_national_graph()`, logga
- Om stad har data men alla parametrar är None → returnera None, logga
- Om parameter har data men alla värden är None → returnera None för den parametern, INTE plotta med 0-1 (det är en fallback)
- **VIKTIGT**: Om all data är None för en parameter → returnera None, INTE sätta Y-axel till 0-1
- INGEN text i bilden, INGEN "Ingen data"-meddelande i PNG
- INGEN fallback-värden för Y-axel (inte 0-1, inte något annat standardvärde)
- Loggning sker i logger, inte i grafen

## Beroenden

Lägg till i `requirements.txt`:

- `matplotlib` (om inte redan finns)
- `pandas` (för nationell graf groupby)

## Testning

- Testa med tom databas → ska returnera None/tom lista, logga, INTE generera grafer
- Testa med en stad utan data → ska returnera None, logga, INTE generera graf
- Testa med data som saknar vissa kolumner (t.ex. ingen O₃) → ska hoppa över O₃-subplot, generera graf med övriga parametrar
- Testa med stora datamängder → ska plotta alla datapunkter (ingen nedsampling)
- Testa med worker thread → UI ska inte frysa under generering
- Testa global timestamp → alla grafer ska ha samma timestamp vid export
- **Testa None-data**: Om parameter har data men alla värden är None → ska returnera None, INTE plotta med 0-1 Y-axel
- **Testa standardbeteende**: Verifiera att hours=None ger ALL historik, inget implicit standardintervall
- **Testa tidsbaserad filtrering**: Verifiera att `get_weather_data_for_city(city_id, hours=24)` returnerar data från senaste 24 timmarna, inte senaste 24 datapunkterna
- **Testa varierande sampling**: Verifiera att filtrering fungerar korrekt även om data kommer med varierande intervall (t.ex. var 10:e minut vs varje timme)
- **Testa timestamp-konvertering**: Verifiera att timestamp-kolumner konverteras korrekt till datetime för filtrering

## Filer att Modifiera

1. `database/db_manager.py` - Lägg till `get_weather_data_for_city()` och `get_all_weather_data()`
2. `analytics/graph_generator.py` - Ny fil (dynamiskt grid, minimal styling, ingen text i grafer)
3. `analytics/__init__.py` - Export GraphGenerator
4. `gui/main_window.py` - Lägg till toolbar-knapp och worker thread för grafgenerering
5. `requirements.txt` - Lägg till matplotlib och pandas (om saknas)

## Viktiga Invariants (Analysartefakt-tänk)

- INGA hårdkodade städer
- INGA hårdkodade intervall
- INGA fallback-värden
- INGA antaganden om kolumner
- Endast verklig data från databasen
- Om data saknas → returnera None, logga, INTE generera graf med text
- Om all data är None för parameter → returnera None, INTE sätta Y-axel till 0-1 (det är en fallback)
- Dynamiskt grid-layout baserat på antal parametrar
- En subplot per parameter (INGEN dual-axis)
- Minimal styling: svart linje, grid, ingen färglogik
- INGEN text i PNG-filer (ren analysartefakt)
- Global export timestamp för spårbarhet
- Worker thread för att inte frysa UI
- **Tidsbaserad filtrering**: Alltid använd `timestamp >= cutoff_time`, INTE datapunktsbaserad (inte `.iloc[-N]`)
- **Inga antaganden om sampling**: Fungera korrekt oavsett datainsamlingsintervall
- **Dynamisk tidsfiltrering**: Om intervall behövs, använd `datetime.now() - timedelta(hours=hours)`, inte hårdkodade perioder
- **Korrekt timestamp-hantering**: Konvertera timestamp-kolumner till datetime för korrekt filtrering och sortering
- **Standardbeteende**: hours=None ger ALL historik, inget implicit standardintervall
- **INGA fallback-värden för Y-axel**: Om all data är None → returnera None, INTE 0-1 eller något annat standardvärde