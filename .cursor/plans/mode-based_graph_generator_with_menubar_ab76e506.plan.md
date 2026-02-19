---
name: Mode-Based Graph Generator with MenuBar
overview: Omstrukturera grafgeneratorn till en polymorf mode-arkitektur med MenuBar istället för ToolBar. Helt dynamisk periodlogik utan hårdkodade värden eller fallbacks.
todos:
  - id: create-mode-architecture
    content: Skapa analytics/graph_modes.py med BaseMode, DailyMode, WeeklyMode, MonthlyMode, YearlyMode och MODES dictionary
    status: completed
  - id: update-graph-generator-modes
    content: Uppdatera GraphGenerator med generate_plot_with_mode() och mode-parameter i generate_city_graph() och generate_national_graph()
    status: completed
    dependencies:
      - create-mode-architecture
  - id: replace-toolbar-menubar
    content: Ersätt ToolBar grafgenerering med MenuBar i gui/main_window.py, bygg meny dynamiskt från MODES
    status: completed
    dependencies:
      - create-mode-architecture
  - id: implement-run-mode
    content: Implementera run_mode() metod i MainWindow som tar Mode-klass och kör grafgenerering i worker thread
    status: completed
    dependencies:
      - replace-toolbar-menubar
      - update-graph-generator-modes
  - id: update-worker-mode
    content: Uppdatera GraphGenerationWorker för att stödja mode-parameter
    status: completed
    dependencies:
      - update-graph-generator-modes
  - id: update-analytics-init-modes
    content: Uppdatera analytics/__init__.py för att exportera Mode-klasser
    status: completed
    dependencies:
      - create-mode-architecture
---

# Mode-Based Graph Generator with MenuBar

## Översikt

Omstrukturera grafgeneratorn till en polymorf mode-arkitektur där olika tidsperioder (dag, vecka, månad, år) hanteras via Mode-objekt. Ersätt ToolBar med MenuBar och bygg menyn dynamiskt från registrerade modes.

**Arkitektur-nivå:**

Detta är inte längre "grafgenerator" - det är en **deterministisk, reproducerbar analysartefakt-motor**.

En graf är en funktion av: (dataset snapshot, time filter, parameters, export timestamp)

- Samma input → samma output (deterministisk)
- Graf är reproducerbar analysartefakt

**Arkitektur-nivå:**

Detta är inte längre "grafgenerator" - det är en **deterministisk, reproducerbar analysartefakt-motor**.

En graf är en funktion av: (dataset snapshot, time filter, parameters, export timestamp)

- Samma input → samma output (deterministisk)
- Graf är reproducerbar analysartefakt

## Arkitektur

### Mode-arkitektur (Polymorf design)

**Abstrakt basklass:**

```python
class BaseMode:
    def transform(self, df: pd.DataFrame, selected_date: Optional[date] = None) -> pd.DataFrame:
        """Transform dataframe with grouping logic."""
        raise NotImplementedError
    
    def legend_label(self, group_key) -> str:
        """Generate legend label for a group key."""
        raise NotImplementedError
    
    def title(self, df: pd.DataFrame, city_name: str) -> str:
        """Generate title for the graph."""
        raise NotImplementedError
    
    def get_name(self) -> str:
        """Return mode name for menu."""
        raise NotImplementedError
    
    def needs_date_selection(self) -> bool:
        """Return True if mode requires date selection (e.g. DailyMode)."""
        return False
```

**Konkreta Mode-klasser:**

- `DailyMode`: Grupperar per timme på dygnet (0-23, 24-timmars format)
- `WeeklyMode`: Grupperar per veckodag
- `MonthlyMode`: Grupperar per vecka i månaden
- `YearlyMode`: Grupperar per månad i året

### Central Generator

**Mode-agnostisk plot-generering:**

```python
def generate_plot(df: pd.DataFrame, mode_obj: BaseMode, city_name: str) -> matplotlib.figure.Figure:
    """Generate plot using mode object - no if-else logic."""
    # Transform dataframe using mode
    df = mode_obj.transform(df)
    
    # Generate plot based on transformed data
    # No hardcoded period checks
```

## Implementation

### 1. Skapa Mode-arkitektur

**Ny fil: `analytics/graph_modes.py`**

**BaseMode (abstrakt):**

- `transform(df, selected_date=None)`: Transform DataFrame baserat på mode-logik
  - För DailyMode: tar `selected_date` parameter (datum för den specifika dagen)
  - För andra modes: `selected_date` är None (använder all data)
- `legend_label(key)`: Genererar legend-label för group key (används INTE i DailyMode)
- `title(df, city_name)`: Genererar graf-titel
- `get_name()`: Returnerar mode-namn för meny
- `needs_date_selection()`: Returnerar True om mode kräver datum-val (DailyMode)

**DailyMode:**

- **VIKTIGT**: Daily mode = exakt EN dag, INTE gruppering av flera dagar
- Tar `selected_date` som parameter (datum för den specifika dagen)
- `transform()`: 
  - Filtrera exakt en dag: `df_day = df[df["timestamp"].dt.date == selected_date]`
  - Skapa hour-kolumn: `df_day["hour"] = df_day["timestamp"].dt.hour`
  - Aggregra per timme (INTE smoothing): `hourly = df_day.groupby("hour").mean(numeric_only=True)`
  - Returnera aggregated DataFrame med hour som index (0-23)
- `legend_label()`: Används INTE i daily mode (ingen legend)
- `title()`: `"{city_name} – {date}"` (exakt datum)
- X-axel: 0-23 (timmar på dygnet)
- Y-axel: parameter-värden (aggregated per timme)
- **INGEN smoothing, INGEN interpolation, INGEN fillna**
- Om timme saknas → hoppa över (ingen fallback, ingen 0-värde)

**WeeklyMode:**

- `transform()`: `df["group"] = df["timestamp"].dt.day_name()`
- `legend_label()`: Returnerar veckodagsnamn
- `title()`: `"{city_name} – Vecka {week} ({year})"`

**MonthlyMode:**

- `transform()`: `df["group"] = (df["timestamp"].dt.day - 1) // 7 + 1`
- `legend_label()`: `"Vecka {key}"`
- `title()`: `"{city_name} – {month} {year}"`

**YearlyMode:**

- `transform()`: `df["group"] = df["timestamp"].dt.month`
- `legend_label()`: `calendar.month_name[key]`
- `title()`: `"{city_name} – År {year}"`

**Mode-registrering:**

```python
MODES = {
    "Daily": DailyMode,
    "Weekly": WeeklyMode,
    "Monthly": MonthlyMode,
    "Yearly": YearlyMode,
}
```

**VIKTIGT**: Ordningen i MODES dictionary bestämmer ordningen i menyn. Daily ska vara först.

### 2. Uppdatera GraphGenerator

**Ändringar i `analytics/graph_generator.py`:**

- Lägg till `generate_plot_with_mode()` metod:
  - Tar `mode_obj: BaseMode` och `selected_date: Optional[date]` som parametrar
  - Använder `mode_obj.transform(df, selected_date=selected_date)` för att transformera data
  - **DailyMode specialhantering**:
    - Om `mode_obj.needs_date_selection()`: kräv `selected_date` parameter
    - X-axel: 0-23 (timmar), INTE riktig timestamp
    - En linje per parameter, INGEN legend
    - Aggregra per timme: `groupby("hour").mean()`
  - **Andra modes**:
    - Använder `mode_obj.legend_label()` för legend
    - X-axel: riktig timestamp
    - För varje unik `group`: plotta separat linje
  - Använder `mode_obj.title()` för titel
  - Inga if-else för perioder (använd polymorfism)
  - **Semantisk metadata**: Lägg till parameter-namn (ylabel), axeltitlar (xlabel, ylabel), graf-titel (suptitle)
  - **INGEN styling-text**: Inga "Ingen data"-meddelanden, inga färgkodade varningar

- Uppdatera `generate_city_graph()`:
  - Lägg till `mode: Optional[BaseMode] = None` parameter
  - Lägg till `export_timestamp: Optional[str] = None` parameter
  - Lägg till `selected_date: Optional[date] = None` parameter (för DailyMode)
  - Om mode angivet: använd `generate_plot_with_mode(mode, selected_date)`
  - Om mode=None: använd befintlig logik (ALL data, en linje per parameter)
  - Använd export_timestamp om angivet, annars generera ny
  - Om `mode.needs_date_selection()` och `selected_date` är None → returnera None, logga

- Uppdatera `generate_national_graph()`:
  - Lägg till `mode: Optional[BaseMode] = None` parameter
  - Lägg till `export_timestamp: Optional[str] = None` parameter
  - Lägg till `selected_date: Optional[date] = None` parameter (för DailyMode)
  - Samma logik som för stadsgrafer

- Uppdatera `generate_all_city_graphs()`:
  - Lägg till `mode: Optional[BaseMode] = None` parameter
  - Lägg till `export_timestamp: Optional[str] = None` parameter
  - Lägg till `selected_date: Optional[date] = None` parameter (för DailyMode)
  - Injicera export_timestamp och selected_date i alla `generate_city_graph()` anrop

### 3. Ersätt ToolBar med MenuBar

**Ändringar i `gui/main_window.py`:**

**Ta bort:**

- ToolBar-implementationen för grafgenerering
- `GraphGenerationWorker` (behåll men uppdatera)

**Lägg till:**

- MenuBar med "Generate"-meny
- Dynamisk menybyggnad från `MODES` dictionary
- `run_mode(mode_class)` metod som tar Mode-klass

**MenuBar-struktur:**

```python
menubar = self.menuBar()
generate_menu = menubar.addMenu("Generera")

# Dynamisk byggnad från MODES
for mode_name, mode_class in MODES.items():
    action = QAction(mode_name, self)
    action.triggered.connect(lambda checked, m=mode_class: self.run_mode(m))
    generate_menu.addAction(action)
```

**Datumväljare för DailyMode:**

- Om `mode.needs_date_selection()` returnerar True:
- Visa `QDateDialog` för användaren
- Om användaren valde datum: `selected_date = dialog.selectedDate().toPyDate()`
- Om användaren avbröt: returnera, kör INTE worker
- Skicka `selected_date` till worker

**run_mode() metod:**

- **VIKTIGT**: Generera global export timestamp FÖRE worker startar (EN gång)
- `export_ts = datetime.now(ZoneInfo("Europe/Stockholm"))`
- `export_timestamp = export_ts.strftime("%Y%m%d_%H%M%S")`
- Skapar Mode-instans
- **Om `mode.needs_date_selection()`**: Visa datumväljare (QDateDialog) för användaren
- Om datum valt: `selected_date = date.fromisoformat(selected_date_str)`
- Om datum INTE valt (användaren avbröt): returnera, kör INTE worker
- Skapar GraphGenerator
- Skapar GraphGenerationWorker med mode, export_timestamp och selected_date
- Worker injicerar SAMMA export_timestamp och selected_date i alla genereringsanrop
- Kör i worker thread

**Global timestamp-injektion (STRICT):**

- Timestamp genereras EN gång i `run_mode()` FÖRE worker startar
- `export_ts = datetime.now(ZoneInfo("Europe/Stockholm"))` (EN anrop)
- `export_timestamp = export_ts.strftime("%Y%m%d_%H%M%S")`
- Timestamp skickas som parameter till worker
- Worker injicerar SAMMA timestamp i:
  - `generate_all_city_graphs(export_timestamp=export_timestamp)`
  - `generate_national_graph(export_timestamp=export_timestamp)`
- **ALDRIG separata `datetime.now()`-anrop i worker**
- Alla grafer i samma batch får exakt samma timestamp (samma sekund, CET)

### 4. Designprinciper

**Inga hårdkodade perioder:**

- Alla perioder definieras via Mode-klasser
- Inga if-else för period-checks
- Ny period = ny Mode-klass + registrering i MODES

**Inga fallbacks:**

- Om data saknas → returnera None
- Om mode saknas → inte möjligt (mode är parameter)
- Om group saknas → hoppa över (dynamisk detektion)

**VIKTIG INVARIANT - Parameter-hantering (STRICT DEFINITION):**

**Total None-return (inga grafer genereras):**

- Om `get_weather_data_for_city()` returnerar tom lista → returnera None
- Om stad har data men alla parametrar är None (ingen parameter har minst ett giltigt numeriskt värde) → returnera None

**Partiell parameter-hantering (graf genereras):**

- **Om minst en parameter har minst ett giltigt numeriskt värde → generera graf**
- **Parametrar utan giltiga värden ignoreras helt (hoppas över, ax.axis('off'))**
- **Exempel**: Stad har 7 parametrar, 6 har riktig data, 1 är None-only → generera graf med 6 subplots, hoppa över None-parametern
- **Detta är STABILT**: Systemet kraschar inte om en parameter saknas, det genererar bara graf för tillgängliga parametrar

**Helt dynamisk:**

- Meny byggs från MODES dictionary
- Inga hårdkodade meny-items
- Lägg till ny mode = lägg till i MODES, meny uppdateras automatiskt

**Inga färger:**

- Svart linje för alla grupper
- Grid, minimal styling
- Legend för att skilja grupper

**Semantisk metadata vs styling-text:**

- **TILLÅTET (semantisk metadata)**: Parameter-namn på subplot (ylabel), axeltitlar (xlabel, ylabel), graf-titel (suptitle)
- **INTE TILLÅTET (styling-text)**: "Ingen data"-meddelanden, färgkodade varningar, instruktioner, fallback-text
- **Distinktion**: Metadata är nödvändig för att förstå grafen, styling-text är dekorativ/fallback

### 5. Mode-transformering

**Varje Mode måste:**

- **Historical modes (WeeklyMode, MonthlyMode, YearlyMode):**
  - Lägga till `group`-kolumn i DataFrame
  - Hantera timestamp-konvertering korrekt
  - Hantera tom data gracefully (returnera tom DataFrame, inte fallback)

- **DailyMode (special):**
  - Ta `selected_date: date` parameter (krävs)
  - Filtrera exakt EN dag: `df_day = df[df["timestamp"].dt.date == selected_date]`
  - Skapa hour-kolumn: `df_day["hour"] = df_day["timestamp"].dt.hour`
  - Aggregra per timme: `hourly = df_day.groupby("hour").mean(numeric_only=True)`
  - Returnera aggregated DataFrame med hour som index (0-23)
  - **INGEN smoothing, INGEN interpolation, INGEN fillna**
  - Om timme saknas → hoppa över (ingen fallback)

**Group-logik:**

- **DailyMode**: 
  - Filtrera exakt EN dag: `df_day = df[df["timestamp"].dt.date == selected_date]`
  - Skapa hour-kolumn: `df_day["hour"] = df_day["timestamp"].dt.hour`
  - Aggregra per timme: `hourly = df_day.groupby("hour").mean(numeric_only=True)`
  - X-axel: 0-23 (timmar på dygnet)
  - En linje per parameter (INTE per timme)
  - **INGEN legend** (bara en dag)
  - Om flera datapunkter per timme → groupby.mean() (aggregation, inte smoothing)
  - Om timme saknas → hoppa över (ingen fallback)
- WeeklyMode: `df["group"] = df["timestamp"].dt.day_name()`
- MonthlyMode: `df["group"] = (df["timestamp"].dt.day - 1) // 7 + 1`
- YearlyMode: `df["group"] = df["timestamp"].dt.month`

**DailyMode detaljer (STRICT):**

- **Exakt EN dag**: Filtrera med `df[df["timestamp"].dt.date == selected_date]`
- **X-axel = 0-23**: Timmar på dygnet, INTE riktig timestamp
- **Aggregation per timme**: `groupby("hour").mean()` om flera datapunkter per timme
- **En linje per parameter**: INTE en linje per timme
- **INGEN legend**: Bara en dag, ingen behov av legend
- **INGEN smoothing**: `.rolling()`, `.interpolate()`, `.fillna()` är FORBIDDEN
- **Om timme saknas**: Hoppa över, INTE fyll med 0 eller interpolera
- **Resultat**: Ren 24-punkters profil av exakt den dagen

**Plot-logik (beroende på mode):**

**Historical mode (mode=None eller WeeklyMode/MonthlyMode/YearlyMode):**

- För varje unik `group`: plotta separat linje
- Använd `mode_obj.legend_label(key)` för legend
- Alla linjer svarta (ingen färglogik)
- X-axel: riktig timestamp
- **Plot all datapunkter (no downsampling)**: Alla datapunkter plottas, ingen nedsampling

**Daily mode (DailyMode):**

- Filtrera exakt EN dag: `df_day = df[df["timestamp"].dt.date == selected_date]`
- Skapa hour-kolumn: `df_day["hour"] = df_day["timestamp"].dt.hour`
- Aggregra per timme: `hourly = df_day.groupby("hour").mean(numeric_only=True)`
- X-axel: 0-23 (timmar på dygnet)
- En linje per parameter (INTE per timme)
- **INGEN legend** (bara en dag)
- **INGEN smoothing**: `.rolling()`, `.interpolate()`, `.fillna()` är FORBIDDEN
- Om timme saknas → hoppa över (ingen fallback)
- `ax.set_xlim(0, 23)`, `ax.set_xticks(range(0, 24))`

**Designval:**

- Stora datamängder (t.ex. 6 år × 40 städer × 10 min intervall ≈ 13 miljoner rader) kan ta flera sekunder att rendera
- Detta är okej - det är designval, inte fel
- Matplotlib klarar stora datamängder, men rendering blir långsam och PNG blir tung

## Tekniska Detaljer

### Mode-registrering

**Central MODES dictionary:**

- Placeras i `analytics/graph_modes.py`
- Importeras i `gui/main_window.py` för menybyggnad
- Kan utökas utan att ändra UI-kod

### Worker Thread

**Behåll GraphGenerationWorker:**

- Uppdatera för att acceptera mode-parameter, export_timestamp och selected_date
- `__init__(self, db_manager, mode_class=None, export_timestamp=None, selected_date=None, output_dir="output")`
- `run(self)`: Använder mode-instans, export_timestamp och selected_date som redan skapats
- Injicerar export_timestamp och selected_date i alla genereringsanrop
- Kör grafgenerering med mode, global timestamp och selected_date

**VIKTIGT**:

- Worker tar emot export_timestamp och selected_date som parametrar, genererar INTE egen timestamp
- **ALDRIG separata `datetime.now()`-anrop i worker**
- Injicerar SAMMA export_timestamp och selected_date i:
  - `generate_all_city_graphs(mode=mode_instance, export_timestamp=export_timestamp, selected_date=selected_date)`
  - `generate_national_graph(mode=mode_instance, export_timestamp=export_timestamp, selected_date=selected_date)`
- Alla anrop använder samma export_timestamp-sträng och selected_date

### Timestamp-hantering (Europe/Stockholm med DST)

**VIKTIGT: Alla timestamps ska vara timezone-aware (Europe/Stockholm)**

**Använd ZoneInfo för korrekt DST-hantering:**

```python
from zoneinfo import ZoneInfo
from datetime import datetime

CET = ZoneInfo("Europe/Stockholm")
```

**I Mode.transform():**

- Konvertera timestamp till datetime om sträng
- Om timestamp är UTC: `pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("Europe/Stockholm")`
- Om timestamp är naive: `pd.to_datetime(df["timestamp"]).dt.tz_localize("Europe/Stockholm")`
- Använd pandas `.dt` accessor för datetime-operationer
- **ALLA timestamps ska vara timezone-aware (Europe/Stockholm)**

**DailyMode.transform() specialhantering:**

- Ta `selected_date: date` parameter (krävs för DailyMode)
- Filtrera exakt EN dag: `df_day = df[df["timestamp"].dt.date == selected_date]`
- Om `df_day.empty`: returnera tom DataFrame (ingen fallback)
- Skapa hour-kolumn: `df_day["hour"] = df_day["timestamp"].dt.hour`
- Aggregra per timme: `hourly = df_day.groupby("hour").mean(numeric_only=True)`
- Returnera aggregated DataFrame med hour som index (0-23)
- **INGEN smoothing**: `.rolling()`, `.interpolate()`, `.fillna()` är FORBIDDEN
- Om timme saknas → hoppa över (ingen fallback, ingen 0-värde)

**I DatabaseManager (filtrering):**

- `cutoff = datetime.now(ZoneInfo("Europe/Stockholm")) - timedelta(hours=hours)`
- Filtrera med CET-aware cutoff
- **ALDRIG naive datetime, ALDRIG manuell offset (+1, +2)**

**Export timestamp:**

- `export_ts = datetime.now(ZoneInfo("Europe/Stockholm")).strftime("%Y%m%d_%H%M%S")`
- Alla grafer får samma CET-timestamp

**DST-hantering:**

- ZoneInfo("Europe/Stockholm") hanterar automatiskt:
  - CET (UTC+1) vintertid
  - CEST (UTC+2) sommartid
  - DST-skiften (02:00 → 03:00, eller 02:00 upprepas)
- **ALDRIG manuell offset-hantering**

**Intern lagring vs presentation:**

- Intern lagring: UTC (om möjligt, för framtidssäkerhet)
- Presentation + filtrering: Europe/Stockholm (tz-aware)

### Stora datamängder (Designval)

**Plot all datapunkter (no downsampling):**

- Alla datapunkter plottas, ingen nedsampling
- **Designval**: Stora datamängder kan ta flera sekunder att rendera
- Exempel: 6 år × 40 städer × 10 min intervall ≈ 13 miljoner rader
- Matplotlib klarar det, men:
  - Rendering blir långsam
  - PNG blir tung
  - Worker kan ta flera sekunder
- **Detta är okej - det är designval, inte fel**
- Användaren är medveten om att stora datamängder tar tid

### Tom data-hantering (Strikt definierat)

**I Mode.transform():**

- Om DataFrame tom → returnera tom DataFrame
- Om ingen timestamp → returnera tom DataFrame
- INGA fallbacks, INGA default-värden

**I GraphGenerator.generate_city_graph() / generate_national_graph():**

**Total None-return (inga grafer genereras):**

- Om `get_weather_data_for_city()` returnerar tom lista → returnera None
- Om `get_all_weather_data()` returnerar tom lista → returnera None
- Om stad har data men alla parametrar är None (ingen parameter har minst ett giltigt värde) → returnera None
- Om `mode.needs_date_selection()` och `selected_date` är None → returnera None, logga

**DailyMode specialhantering:**

- Om `selected_date` angivet men ingen data för den dagen → returnera None, logga
- Om `df_day.empty` efter filtrering → returnera None, logga
- Om aggregering ger tom DataFrame (ingen timme har data) → returnera None, logga

**Partiell parameter-hantering (graf genereras):**

- **Om minst en parameter har minst ett giltigt numeriskt värde → generera graf**
- För varje parameter: om parameter har minst ett giltigt värde → skapa subplot
- För varje parameter: om alla värden är None → hoppa över subplot (ax.axis('off'))
- **Exempel**: Stad har 7 parametrar, 6 har riktig data, 1 är None-only → generera graf med 6 subplots, hoppa över None-parametern
- **Detta är STABILT**: Systemet kraschar inte om en parameter saknas, det genererar bara graf för tillgängliga parametrar

**DailyMode parameter-hantering:**

- För varje parameter: om parameter har data för minst en timme → skapa subplot
- Om parameter saknar data för alla timmar → hoppa över subplot (ax.axis('off'))
- Om timme saknas (t.ex. ingen data kl 03) → hoppa över den timmen (ingen fallback, ingen 0-värde)

**Invariant (STRICT):**

- **Om minst en parameter har minst ett giltigt numeriskt värde → generera graf**
- **Parametrar utan giltiga värden ignoreras helt (hoppas över)**
- Om alla parametrar är None → returnera None (total None)

**Numerisk stabilisering (inte fallback):**

- **Y-axel edge case**: Om `y_min == y_max` (alla värden exakt samma, t.ex. konstant 0)
- Detta är matematisk degenerering, inte fallback
- Hantera med: `if y_min == y_max: ax.set_ylim(y_min - epsilon, y_max + epsilon)`
- Epsilon: `abs(y_min) * 0.01 if y_min != 0 else 0.1`
- Detta förhindrar matplotlib-krascher eller platta grafer

## Filer att Modifiera

1. `analytics/graph_modes.py` - Ny fil med Mode-arkitektur
2. `analytics/graph_generator.py` - Lägg till mode-stöd
3. `analytics/__init__.py` - Export Mode-klasser
4. `gui/main_window.py` - Ersätt ToolBar med MenuBar, lägg till run_mode() och datumväljare för DailyMode
5. `gui/main_window.py` - Uppdatera GraphGenerationWorker för mode-stöd och selected_date

## Viktiga Invariants

- INGA hårdkodade perioder - alla via Mode-klasser
- INGA if-else för period-checks - använd polymorfism
- INGA fallback-värden - returnera None/tom DataFrame
- INGA hårdkodade meny-items - bygg från MODES dictionary
- INGA färger - svart linje för alla, legend för skillnad
- Helt dynamisk - ny mode = lägg till klass + registrering
- MenuBar-driven - ingen ToolBar för grafgenerering

**Parameter-hantering invariant (STRICT):**

- **Om minst en parameter har minst ett giltigt numeriskt värde → generera graf**
- **Parametrar utan giltiga värden ignoreras helt (hoppas över)**
- Om alla parametrar är None → returnera None (total None)
- **Detta är STABILT**: Systemet kraschar inte om en parameter saknas

**Semantisk metadata vs styling:**

- TILLÅTET: Parameter-namn (ylabel), axeltitlar (xlabel, ylabel), graf-titel (suptitle)
- INTE TILLÅTET: "Ingen data"-meddelanden, färgkodade varningar, instruktioner, fallback-text

**Global timestamp invariant (STRICT):**

- Timestamp genereras EN gång FÖRE worker startar (i run_mode())
- `export_ts = datetime.now(ZoneInfo("Europe/Stockholm"))` (EN anrop)
- `export_timestamp = export_ts.strftime("%Y%m%d_%H%M%S")`
- Timestamp injiceras i worker som parameter
- Worker injicerar SAMMA timestamp i alla genereringsanrop
- **ALDRIG separata `datetime.now()`-anrop i worker**
- Alla grafer i samma batch får exakt samma timestamp (samma sekund, CET)

**Timezone invariant (STRICT):**

- ALLA timestamps ska vara timezone-aware (Europe/Stockholm)
- Använd `ZoneInfo("Europe/Stockholm")` för korrekt DST-hantering
- **ALDRIG naive datetime, ALDRIG manuell offset (+1, +2)**
- ZoneInfo hanterar automatiskt: CET (UTC+1), CEST (UTC+2), DST-skiften
- Intern lagring: UTC (om möjligt, för framtidssäkerhet)
- Presentation + filtrering: Europe/Stockholm (tz-aware)

**Numerisk stabilisering invariant (inte fallback):**

- Om `y_min == y_max` (alla värden samma): `ax.set_ylim(y_min - epsilon, y_max + epsilon)`
- Detta är matematisk degenerering-hantering, inte fallback
- Epsilon: `abs(y_min) * 0.01 if y_min != 0 else 0.1`
- Förhindrar matplotlib-krascher eller platta grafer

**Reproducerbarhet invariant:**

- En graf är en funktion av: (dataset snapshot, time filter, parameters, export timestamp)
- Samma input → samma output (deterministisk)
- Graf är reproducerbar analysartefakt