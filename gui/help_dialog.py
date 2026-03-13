"""Help dialog with feature dictionary."""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QTextEdit, QPushButton, QDialogButtonBox
)
from PyQt5.QtCore import Qt
from analytics.graph_modes import MODES
from analytics.warnings import WarningDetector


class HelpDialog(QDialog):
    """Help dialog with comprehensive feature documentation."""

    def __init__(self, parent=None):
        """
        Initialize help dialog.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("Hjälp - Funktioner och Användning")
        self.setMinimumSize(900, 700)
        self._init_ui()

    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()

        self.tabs.addTab(self._create_text_widget(self._get_overview_content()),        "Översikt")
        self.tabs.addTab(self._create_text_widget(self._get_weather_content()),         "Väderdata")
        self.tabs.addTab(self._create_text_widget(self._get_air_quality_content()),     "Luftkvalitet")
        self.tabs.addTab(self._create_text_widget(self._get_graphs_content()),          "Grafer")
        self.tabs.addTab(self._create_text_widget(self._get_stations_content()),        "Stationer")
        self.tabs.addTab(self._create_text_widget(self._get_analytical_map_content()), "Analytisk Karta")
        self.tabs.addTab(self._create_text_widget(self._get_inversion_content()),       "Inversionsmodell")
        self.tabs.addTab(self._create_text_widget(self._get_cluster_content()),         "Klusteranalys")
        self.tabs.addTab(self._create_text_widget(self._get_statistics_content()),      "Statistik")
        self.tabs.addTab(self._create_text_widget(self._get_shortcuts_content()),       "Kortkommandon")
        self.tabs.addTab(self._create_text_widget(self._get_troubleshooting_content()),"Felsökning")

        layout.addWidget(self.tabs)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.accept)
        layout.addWidget(button_box)

    def _create_text_widget(self, html_content: str) -> QTextEdit:
        """
        Create QTextEdit widget with HTML content.

        Args:
            html_content: HTML formatted content

        Returns:
            QTextEdit widget
        """
        text_widget = QTextEdit()
        text_widget.setReadOnly(True)
        text_widget.setHtml(html_content)
        return text_widget

    # ------------------------------------------------------------------
    # Tab: Översikt
    # ------------------------------------------------------------------

    def _get_overview_content(self) -> str:
        """Get overview tab content."""
        return """
        <h1>Väderapplikation - Översikt</h1>

        <h2>Vad är detta?</h2>
        <p>En produktionsklar miljöanalys-desktopapp som samlar väderdata och luftkvalitetsdata
        från flera gratis API-källor, lagrar allt lokalt i SQLite och erbjuder avancerad
        realtidsanalys med kartor, modeller och varningssystem.</p>

        <h2>Snabbstart</h2>
        <ol>
            <li><b>Starta applikationen</b>: Kör <code>python main.py</code></li>
            <li><b>Lägg till städer</b>: Klicka på "Lägg till stad" i vänsterpanelen</li>
            <li><b>Hämta data</b>: Klicka på "Hämta nu" (F5) eller aktivera "Auto-uppdatering"</li>
            <li><b>Utforska</b>: Använd flikarna för statistik, historik, varningar, grafer och karta</li>
        </ol>

        <h2>Huvudkomponenter</h2>
        <ul>
            <li><b>Vänsterpanel</b>: Lista över städer, lägg till/ta bort städer</li>
            <li><b>Huvudpanel</b>: Aktuell väderdata och luftkvalitet för vald stad</li>
            <li><b>Flikar</b>: Historik, Statistik, Översikt, Varningar, Stationer, API Status, Loggar</li>
            <li><b>Analytisk Karta</b>: Interaktiv Leaflet-karta med AQI-markörer, heatmap,
                sparklines, inversionsrisk och klustervarningar</li>
            <li><b>Menubar</b>: Generera grafer och öppna Inställningar</li>
            <li><b>Verktygsfält</b>: Manuell uppdatering och auto-update toggle</li>
        </ul>

        <h2>Vad är nytt?</h2>
        <ul>
            <li><b>Inversionsriskmodell v3</b>: Probabilistisk 0–100-poäng, winsoriserade p5/p95-gränser,
                robust mot uteliggare</li>
            <li><b>Regional klusteranalys</b>: Identifierar regional luftkvalitetspåverkan relativt
                nationellt 7-dagars medelvärde</li>
            <li><b>Täthetsmedveten heatmap</b>: Interpoleringsradien anpassas automatiskt efter
                stationstätheten — inget falskt gradient i glesbebyggda områden</li>
            <li><b>Debug-läge</b>: Visar rådata, normaliserade värden, nationellt basvärde och
                deviation_factor direkt i stationsmarkörer</li>
            <li><b>Versionshanterad konfiguration</b>: Nya inställningsnycklar slås samman utan att
                befintliga användarvärden skrivs över</li>
        </ul>

        <h2>Real-time uppdatering</h2>
        <p>GUI:t uppdateras automatiskt var 5:e sekund med senaste data från databasen.
        Detta är oberoende av auto-update och hämtar inte ny data från API:er.</p>

        <h2>Designprinciper</h2>
        <ul>
            <li><b>Inga fallback-värden</b>: Visar endast verklig data eller "Ingen data"</li>
            <li><b>Dynamisk</b>: Inga hårdkodade städer, trösklar eller färger</li>
            <li><b>Transparent</b>: Alla analytiska beslut är synliga och dokumenterade</li>
            <li><b>Null-safe</b>: Saknad data ger <code>None</code> — aldrig ett ersättningsvärde</li>
        </ul>
        """

    # ------------------------------------------------------------------
    # Tab: Väderdata
    # ------------------------------------------------------------------

    def _get_weather_content(self) -> str:
        """Get weather data tab content."""
        return """
        <h1>Väderdata</h1>

        <h2>Vad visas?</h2>
        <ul>
            <li><b>Temperatur</b>: I Celsius (°C)</li>
            <li><b>Luftfuktighet</b>: I procent (%)</li>
            <li><b>Vindhastighet</b>: I meter per sekund (m/s)</li>
        </ul>

        <h2>Datakällor</h2>
        <p>Applikationen använder flera API-källor för redundans:</p>
        <ul>
            <li><b>Open-Meteo</b> (Primär): Väderdata, ingen API-nyckel krävs</li>
        </ul>

        <h2>Uppdatering</h2>
        <h3>Manuell uppdatering</h3>
        <ul>
            <li>Klicka på <b>"Hämta nu"</b> i verktygsfältet</li>
            <li>Eller tryck <b>F5</b></li>
        </ul>

        <h3>Automatisk uppdatering</h3>
        <ul>
            <li>Aktivera <b>"Auto-uppdatering"</b> i verktygsfältet</li>
            <li>Intervall konfigureras i <b>Inställningar → Data</b></li>
        </ul>

        <h2>Historik</h2>
        <p>All väderdata sparas i databasen. Se historiska data i <b>Historik</b>-fliken.</p>

        <h2>Intelligent Lagring</h2>
        <p>Systemet använder measurement timestamps från API:er för att undvika duplicering.
        Om samma mätning hämtas flera gånger sparas den bara en gång.</p>
        """

    # ------------------------------------------------------------------
    # Tab: Luftkvalitet
    # ------------------------------------------------------------------

    def _get_air_quality_content(self) -> str:
        """Get air quality tab content."""
        return """
        <h1>Luftkvalitet</h1>

        <h2>Parametrar</h2>
        <ul>
            <li><b>PM2.5</b>: Partiklar mindre än 2.5 mikrometer (µg/m³)</li>
            <li><b>PM10</b>: Partiklar mindre än 10 mikrometer (µg/m³)</li>
            <li><b>NO₂</b>: Kvävedioxid (µg/m³)</li>
            <li><b>O₃</b>: Ozon (µg/m³)</li>
        </ul>

        <h2>AQI-beräkning</h2>
        <p>Applikationen använder <b>US EPA-standard</b> för AQI-beräkning:</p>
        <ul>
            <li>Baseras på <b>24-timmars rullande medelvärde</b> av PM2.5</li>
            <li>Beräknas dynamiskt från rådata (lagras inte permanent)</li>
            <li>Inga fallback-värden: Om data saknas visas "Ingen data"</li>
        </ul>

        <h2>AQI-brytpunkter</h2>
        <p>Se fliken <b>Analytisk Karta</b> för en komplett, dynamiskt genererad tabell
        med aktuella WHO/EPA-gränsvärden, namn och färgkoder.</p>

        <h2>Datakällor</h2>
        <ul>
            <li><b>OpenAQ</b>: Rådata för PM2.5, PM10, NO₂, O₃ (kräver API-nyckel)</li>
        </ul>

        <h2>Varningar</h2>
        <p>Applikationen genererar automatiskt varningar för farliga luftkvalitetsnivåer.
        Se <b>Varningar</b>-fliken för nationell översikt och regionala varningar.
        Se <b>Klusteranalys</b>-fliken för förklaring av regionala klustervarningar.</p>
        """

    # ------------------------------------------------------------------
    # Tab: Grafer
    # ------------------------------------------------------------------

    def _get_graphs_content(self) -> str:
        """Get graphs tab content."""
        modes_html = "".join(
            f"<li><b>{mode_name}</b></li>"
            for mode_name in MODES
        )

        return f"""
        <h1>Grafgenerering</h1>

        <h2>Tillgängliga Lägen</h2>
        <p>Applikationen stödjer följande graf-lägen (byggda dynamiskt från systemet):</p>
        <ul>
            {modes_html}
        </ul>

        <h2>Hur genererar jag grafer?</h2>
        <ol>
            <li>Gå till <b>Menubar</b> → <b>Generera</b></li>
            <li>Välj önskat läge (Daglig, Veckovis, Månadsvis, eller Årlig)</li>
            <li>För <b>Daglig</b> läge: Välj datum i kalendern</li>
            <li>Vänta medan graferna genereras (körs i bakgrundstråd)</li>
            <li>Graferna sparas automatiskt i <code>output/</code> katalogen</li>
        </ol>

        <h2>Export</h2>
        <ul>
            <li>Grafer sparas i <code>output/</code> katalogen</li>
            <li>Filnamn: <code>&lt;stad_namn&gt;_&lt;timestamp&gt;.png</code></li>
            <li>Nationell graf: <code>sweden_&lt;timestamp&gt;.png</code></li>
        </ul>

        <h2>Tekniska Detaljer</h2>
        <ul>
            <li><b>Bakgrundstråd</b>: Grafgenerering körs i QThread för att hålla GUI responsivt</li>
            <li><b>Inga fallbacks</b>: Om data saknas returneras None, ingen tom graf genereras</li>
            <li><b>Minimal styling</b>: Svarta linjer, grid, inga färger (ren analysartefakt)</li>
            <li><b>Dynamisk layout</b>: En subplot per parameter, inga dual-axis</li>
        </ul>
        """

    # ------------------------------------------------------------------
    # Tab: Stationer  (A1 — full rewrite)
    # ------------------------------------------------------------------

    def _get_stations_content(self) -> str:
        """Get stations tab content — map interaction, layers, AQI markers, custom markers."""
        meta = WarningDetector.get_threshold_metadata()
        color_items = "".join(
            f"<li><span style='display:inline-block;width:14px;height:14px;"
            f"background:{m['color']};border-radius:50%;margin-right:6px;'></span>"
            f"<b>{m['level_name']}</b> — PM2.5 ≤ {m['threshold']} µg/m³ (AQI {m['aqi_range']})</li>"
            for m in meta
        )

        return f"""
        <h1>Stationer och Sensorer</h1>

        <h2>Interaktiv Karta</h2>
        <p>Stationer-fliken visar en analytisk Leaflet-karta med alla stationer,
        sensorer och meteorologiska lageranalyser. All data är dynamisk och hämtas
        direkt från databasen varje gång kartan laddas.</p>

        <h2>Kartlager — Layer-toolbar</h2>
        <p>Tre knappar i kartans övre vänstra hörn byter aktivt lager (ett åt gången):</p>
        <ul>
            <li><b>Stationer</b>: Färgkodade AQI-cirkelmarkörer för varje stad med data</li>
            <li><b>Heatmap</b>: Interpolerad PM2.5-gradient över kartan (täthetsmedveten)</li>
            <li><b>Sensorer</b>: Råa OpenAQ-sensorer med parameter och senaste värde</li>
        </ul>

        <h2>Färgkodade AQI-markörer</h2>
        <p>Varje stadscirkel färgas dynamiskt baserat på det 24-timmars rullande PM2.5-medelvärdet
        via <code>WarningDetector</code>. Yttre grå ring = vindhastighet (bredare = starkare vind).</p>
        <ul>
            {color_items}
        </ul>

        <h2>Täthetsmedveten Heatmap</h2>
        <ul>
            <li>Interpoleringsradien per station skalas med antalet grannstationer inom 2°</li>
            <li>Stationer i glesbefolkade områden (t.ex. norra Sverige) markeras med ett
                varningsbadge — ingen falsk gradient skapas</li>
            <li>Opacitet konfigureras i <b>Inställningar → Karta → Heatmap opacitet</b></li>
        </ul>

        <h2>Analytiska Popups</h2>
        <p>Klicka på en AQI-markör för att se:</p>
        <ul>
            <li><b>24h sparkline</b>: Inline trend för PM2.5 de senaste 24 timmarna</li>
            <li><b>Inversionsrisk</b>: 0–100-poäng med färgad mätarbar</li>
            <li><b>Kalibrering</b>: "Kalibrerad mot N mätningar (p5–p95), Vind X–Y m/s · Fuktighet A–B%"</li>
            <li><b>Low-density badge</b>: Varning om stationsdata är gles i området</li>
            <li><b>Temperatur, luftfuktighet, vindhastighet, NO₂, O₃</b></li>
        </ul>

        <h2>Custom Markers</h2>
        <ol>
            <li>Högerklicka på kartan där du vill lägga till en markör</li>
            <li>Fyll i formuläret: Namn, Beskrivning, Värde (valfritt)</li>
            <li>Klicka OK — markören sparas i databasen och visas direkt</li>
        </ol>

        <h2>Krav</h2>
        <p><b>PyQtWebEngine</b> måste vara installerat:</p>
        <ul>
            <li><code>pip install PyQtWebEngine</code></li>
            <li>Om inte installerat: applikationen fungerar men kartan visas inte</li>
        </ul>
        """

    # ------------------------------------------------------------------
    # Tab: Analytisk Karta  (A2 — new)
    # ------------------------------------------------------------------

    def _get_analytical_map_content(self) -> str:
        """Analytical map — AQI table, heatmap gradient, popup anatomy, null policy."""
        meta = WarningDetector.get_threshold_metadata()

        # AQI table rows — dynamically built from WarningDetector.get_threshold_metadata()
        table_rows = "".join(
            f"<tr>"
            f"<td>{m['aqi_range']}</td>"
            f"<td>≤ {m['threshold']}</td>"
            f"<td style='background-color:{m['color']};color:{'#fff' if m['level_key'] not in ('moderate',) else '#333'};'>"
            f"{m['level_name']}</td>"
            f"</tr>"
            for m in meta
        )

        # Heatmap band descriptions derived from the same metadata
        heatmap_bands = "".join(
            f"<li><span style='display:inline-block;width:14px;height:14px;"
            f"background:{m['color']};margin-right:6px;'></span>"
            f"{m['level_name']} (PM2.5 ≤ {m['threshold']} µg/m³)</li>"
            for m in meta
        )

        return f"""
        <h1>Analytisk Karta — Referens</h1>

        <h2>AQI-färgskala</h2>
        <p>Tabellen nedan genereras dynamiskt från <code>WarningDetector.get_threshold_metadata()</code>
        — exakt samma källa som kartans markörer använder. Om WHO/EPA reviderar gränsvärden
        uppdateras tabellen automatiskt.</p>
        <table border="1" cellpadding="6">
            <tr><th>AQI</th><th>PM2.5 (µg/m³)</th><th>Nivå</th></tr>
            {table_rows}
        </table>

        <h2>Heatmap-gradient</h2>
        <p>Heatmap-lagret interpolerar PM2.5 mellan stationer med samma färgskala:</p>
        <ul>
            {heatmap_bands}
        </ul>
        <p><b>Täthetsmedvetenhet</b>: I glesbefolkade områden (t.ex. norra Sverige) används
        en smalare interpoleringsradius för att undvika missvisande gradients.
        Stationer med <code>low_density = true</code> visas med ett varningsbadge i sin popup.</p>

        <h2>Stationspopup — anatomin</h2>
        <p>Varje analytisk popup innehåller följande fält (fältet visas inte alls om data saknas):</p>
        <ol>
            <li><b>Stadsnamn + AQI-nivå</b>: Dynamisk rubrik med AQI-färg</li>
            <li><b>PM2.5 24h medelvärde</b>: µg/m³</li>
            <li><b>24h sparkline</b>: Inline med PM2.5-trend (upp till 24 datapunkter)</li>
            <li><b>Inversionsrisk</b>: 0–100 poäng med färgad horisontell mätarbar</li>
            <li><b>Kalibrering</b>: Antal historiska mätningar, vindbounds (p5–p95), luftfuktighetsbounds</li>
            <li><b>Low-density varning</b>: Visas om stationen är i ett glest mätarområde</li>
            <li><b>Väderparametrar</b>: Temperatur, luftfuktighet, vindhastighet</li>
            <li><b>Luftkvalitetsparametrar</b>: NO₂, O₃</li>
            <li><b>Debug-fält</b> (om debug_mode aktivt): wind_norm, hum_norm, national_baseline,
                deviation_factor, inversion_model_version</li>
        </ol>

        <h2>Null-policy</h2>
        <p>Systemet emitterar <code>None</code> — aldrig ett ersättningsvärde. Konsekvenser:</p>
        <ul>
            <li>En stad utan PM2.5-data exkluderas från heatmap och klusteranalys</li>
            <li>En stad utan vindhastighet eller luftfuktighet får <code>inversion_score = null</code></li>
            <li>En popup visar inte fältet alls om värdet är <code>null</code></li>
            <li>"Ingen data" visas aldrig — fältet är simpelt frånvarande</li>
        </ul>

        <h2>Klustervarningsbanner</h2>
        <p>En banner längst ner på kartan visas automatiskt om en region avviker signifikant
        från det nationella 7-dagarsmedelvärdet. Se fliken <b>Klusteranalys</b> för detaljer.</p>
        """

    # ------------------------------------------------------------------
    # Tab: Inversionsmodell  (A3 — new)
    # ------------------------------------------------------------------

    def _get_inversion_content(self) -> str:
        """Inversion risk model — formula, winsorization, null conditions, version history."""
        return """
        <h1>Inversionsriskmodell</h1>

        <h2>Fysikalisk grund</h2>
        <p>Temperaturinversion uppstår när ett varmt luftlager fångar kall luft vid markytan.
        Detta hindrar vertikal omblandning och orsakar ackumulering av partiklar.</p>
        <p>Modellen uppskattar inversionsrisken från två meteorologiska proxies som finns i
        <code>weather_data</code>:</p>
        <ul>
            <li><b>Låg vindhastighet</b>: Svag turbulens → stillastående luft → hög risk</li>
            <li><b>Hög luftfuktighet</b>: Proxy för stabila, fuktiga luftmassor associerade
                med inversionsförhållanden</li>
        </ul>

        <h2>Poängformel</h2>
        <p>Vikterna läses från <code>calibration_parameters</code>-tabellen i databasen
        (standardvärden: <code>inversion_wind_weight = 0.6</code>, 
        <code>inversion_humidity_weight = 0.4</code>):</p>
        <pre style='background:#f4f4f4;padding:8px;'>
wind_norm = clamp((wind_speed - wind_lo) / (wind_hi - wind_lo), 0, 1)
hum_norm  = clamp((humidity   - hum_lo)  / (hum_hi  - hum_lo),  0, 1)

inversion_score = (
    (1 - wind_norm) * wind_weight      # hög vind → låg risk
  +     hum_norm   * humidity_weight   # hög luftfuktighet → högre risk
) * 100
        </pre>
        <p>Utdataområde: <b>0</b> (ingen risk) till <b>100</b> (maximal observerad risk).</p>
        <p><b>Viktigt:</b> Alla parametrar (vikter, percentiler) kommer från databasen — inga hårdkodade värden i koden.</p>

        <h2>Winsorisering — varför?</h2>
        <p>Gränserna <code>wind_lo / wind_hi</code> och <code>hum_lo / hum_hi</code> är
        <b>5:e och 95:e percentilen</b> av all historisk data i <code>weather_data</code>.</p>
        <p>Varför inte vanliga min/max?</p>
        <ul>
            <li>En enda felaktig sensor med <code>wind_speed = 120 m/s</code> korrupterar
                max permanent — alla framtida poäng komprimeras mot 0</li>
            <li>p5/p95-gränser är robusta så länge felsensorn representerar &lt;5% av alla mätningar,
                vilket gäller för enstaka sensorer med tillräcklig datamängd</li>
            <li>Poäng 70 beräknad idag är direkt jämförbar med poäng 70 beräknad nästa månad
                (temporal stabilitet)</li>
        </ul>

        <h2>Null-betingelser</h2>
        <p>Poängen emitteras som <code>null</code> (aldrig ersatt) i följande fall:</p>
        <table border="1" cellpadding="6">
            <tr><th>Betingelse</th><th>Orsak</th></tr>
            <tr>
                <td>Färre än 20 historiska rader för någon parameter</td>
                <td>Otillräcklig data för att lita på percentilpositionerna</td>
            </tr>
            <tr>
                <td><code>wind_range == 0</code> efter winsorisering</td>
                <td>Alla historiska vindmätningar identiska — datakvalitetssignal</td>
            </tr>
            <tr>
                <td><code>hum_range == 0</code> efter winsorisering</td>
                <td>Alla historiska luftfuktighetsmätningar identiska — datakvalitetssignal</td>
            </tr>
            <tr>
                <td><code>wind_speed</code> eller <code>humidity</code> är <code>None</code></td>
                <td>Saknad aktuell observation</td>
            </tr>
        </table>

        <h2>Kalibreringsparametrar (DB-drivna)</h2>
        <p>Alla analytiska modellparametrar (inversion percentiler, vikter, IDW-parametrar) 
        läses från <code>calibration_parameters</code>-tabellen i databasen vid körning. 
        Inga hårdkodade konstanter finns längre i koden.</p>
        <p>Viktiga parametrar:</p>
        <ul>
            <li><code>inversion_p_low</code>, <code>inversion_p_high</code>: Winsoriseringspercentiler (standard: 5, 95)</li>
            <li><code>inversion_wind_weight</code>, <code>inversion_humidity_weight</code>: Vikter för inversion score (standard: 0.6, 0.4)</li>
            <li><code>idw_power</code>, <code>idw_max_r_factor</code>, <code>idw_scale_percentile</code>: IDW heatmap-parametrar</li>
        </ul>
        <p>Om en obligatorisk parameter saknas i databasen, misslyckas systemet högljutt med ett tydligt felmeddelande — inga tysta fallbacks till kodkonstanter.</p>

        <h2>Kalibrerings-metadata i popup</h2>
        <p>Varje popup som visar en inversionspoäng inkluderar:</p>
        <pre style='background:#f4f4f4;padding:8px;'>
Kalibrerad mot 4821 mätningar (p5–p95)
Vind: 0.2–9.1 m/s · Fuktighet: 52–94%
        </pre>
        <p>Detta låter användaren bedöma om gränserna är mogna (stort N, bred spridning)
        eller fortfarande osäkra (litet N, smal spridning). Percentilerna (p5–p95) kommer från 
        <code>calibration_parameters</code>-tabellen, inte från hårdkodade värden.</p>

        <h2>Modellversion</h2>
        <p>Aktuell version lagras i <code>config.settings.inversion_model_version</code>
        och inkrementeras vid formeländringar. Historiska poäng kan då märkas med vilken
        modellversion som genererade dem.</p>

        <h2>Versionshistorik</h2>
        <table border="1" cellpadding="6">
            <tr><th>Version</th><th>Normalisering</th><th>Problem</th></tr>
            <tr>
                <td>v1</td>
                <td>Runtime snapshot min/max</td>
                <td>Poängen skiftar dagligen — inte jämförbar över tid</td>
            </tr>
            <tr>
                <td>v2</td>
                <td>Full-history min/max</td>
                <td>En felaktig sensor korrupterar max permanent</td>
            </tr>
            <tr>
                <td><b>v3 (aktuell)</b></td>
                <td><b>Winsoriserat p5/p95 från full historik</b></td>
                <td><b>Outlier-robust och temporalt stabil</b></td>
            </tr>
        </table>
        """

    # ------------------------------------------------------------------
    # Tab: Klusteranalys  (A4 — new)
    # ------------------------------------------------------------------

    def _get_cluster_content(self) -> str:
        """Cluster analysis — algorithm, deviation factor derivation, alert payload."""
        meta = WarningDetector.get_threshold_metadata()
        # Derive the two threshold values used in deviation_factor, same as MapDataBuilder
        moderate_val = next(m["threshold"] for m in meta if m["level_key"] == "moderate")
        good_val     = next(m["threshold"] for m in meta if m["level_key"] == "good")
        factor       = moderate_val / good_val

        return f"""
        <h1>Regional Klusteranalys</h1>

        <h2>Syfte</h2>
        <p>Identifiera när en geografisk region i Sverige visar förhöjt PM2.5 relativt
        den nationella trenden — inte bara relativt ett absolut tröskelvärde.
        En varning som aktiveras bara när en region överstiger det nationella 7-dagars-
        baslinjemedelvärdet med en statistiskt meningsfull marginal undviker falska larm
        när hela landet är jämnt förhöjt.</p>

        <h2>Algoritm (steg för steg)</h2>
        <ol>
            <li><b>Nationellt 7-dagarsmedelvärde</b>: Hämtas via
                <code>get_national_pm25_7day_average()</code>
                — medelvärdet av PM2.5 över alla städer de senaste 168 timmarna</li>
            <li><b>Median-latitud-delning</b>: Beräknas från data (ingen hårdkodad latitud).
                Städer med latitude ≥ median → "norr", annars "söder"</li>
            <li><b>Regionmedelvärde</b>: Medelvärde av <code>pm25_24h</code> för giltiga
                städer i varje region</li>
            <li><b>Deviationstest</b>:
                <pre style='background:#f4f4f4;padding:6px;'>
if region_mean > national_7day_mean * deviation_factor:
    emit cluster_alert
                </pre>
            </li>
        </ol>

        <h2>Varför deviation_factor är härlett — inte hårdkodat</h2>
        <p><code>deviation_factor = THRESHOLDS['moderate'] / THRESHOLDS['good']
        = {moderate_val} / {good_val} ≈ {factor:.2f}</code></p>
        <p>Kvoten kodar frågan: "är den här regionen mer än ~{factor:.1f}× good-air-tröskeln
        över det nationella baslinjemedelvärdet?"</p>
        <p>Om WHO/EPA reviderar sina tröskelvärden uppdateras
        <code>deviation_factor</code> automatiskt — inget manuellt underhåll krävs.</p>

        <h2>Varningsbannerns format</h2>
        <p>En banner visas längst ner på kartan med följande text:</p>
        <pre style='background:#f4f4f4;padding:6px;'>
⚠ Regional påverkan: Södra Sverige — PM2.5 snitt 28.4 µg/m³
(+250.6% mot nationellt 7d-snitt 8.1 µg/m³, 12 stationer)
        </pre>

        <h2>Noll-varningsfallet</h2>
        <p>Om ingen region överstiger tröskeln är bannern <b>helt dold</b> — den visas
        inte med texten "Inga varningar". Frånvaro av banner = allt normalt.</p>

        <h2>Exkluderingsregel</h2>
        <p>Städer med <code>pm25_24h = None</code> exkluderas från:</p>
        <ul>
            <li>Beräkningen av median-latitud (för regiondelning)</li>
            <li>Beräkningen av regionmedelvärde</li>
            <li>Heatmap-lagret</li>
        </ul>
        <p>De inkluderas fortfarande som markörer på kartan (med saknad PM2.5 markerat i popup).</p>
        """

    # ------------------------------------------------------------------
    # Tab: Statistik
    # ------------------------------------------------------------------

    def _get_statistics_content(self) -> str:
        """Get statistics tab content."""
        return """
        <h1>Statistik och Rankings</h1>

        <h2>Statistik-fliken</h2>
        <p>Visa rankings baserat på olika tidsperioder:</p>
        <ul>
            <li><b>1h</b>: Senaste timmen</li>
            <li><b>24h</b>: Senaste 24 timmarna</li>
            <li><b>Idag</b>: Idag (från midnatt)</li>
            <li><b>Vecka</b>: Senaste 7 dagarna</li>
        </ul>

        <h2>Rankings</h2>
        <ul>
            <li><b>Kallast stad</b>: Lägst temperatur</li>
            <li><b>Varmast stad</b>: Högst temperatur</li>
            <li><b>Bäst luftkvalitet</b>: Lägst PM2.5-värde</li>
            <li><b>Sämst luftkvalitet</b>: Högst PM2.5-värde</li>
        </ul>

        <h2>Översikt-fliken</h2>
        <p>Snittvärden över alla städer — temperatur, luftfuktighet, vindhastighet,
        PM2.5 och beräknad AQI.</p>

        <h2>Varningar-fliken</h2>
        <ul>
            <li><b>Nationell översikt</b>: Snitt PM2.5 och AQI över alla städer</li>
            <li><b>Regionala varningar</b>: Städer med farliga PM2.5-nivåer</li>
            <li><b>Top 10 städer</b>: Städer med högst PM2.5-värden</li>
        </ul>
        """

    # ------------------------------------------------------------------
    # Tab: Kortkommandon  (A6 — updated)
    # ------------------------------------------------------------------

    def _get_shortcuts_content(self) -> str:
        """Get keyboard shortcuts tab content."""
        return """
        <h1>Kortkommandon</h1>

        <h2>Verktygsfält</h2>
        <table border="1" cellpadding="5">
            <tr><th>Kortkommando</th><th>Funktion</th></tr>
            <tr><td><b>F5</b></td><td>Manuell uppdatering av all väderdata</td></tr>
        </table>

        <h2>Musinteraktion</h2>
        <ul>
            <li><b>Vänsterklick på stad</b>: Välj stad och visa detaljerad information</li>
            <li><b>Klick på AQI-markör (karta)</b>: Öppnar analytisk popup med 24h sparkline,
                inversionsrisk och kalibrerings-metadata</li>
            <li><b>Klick på layer-knapp (Stationer / Heatmap / Sensorer)</b>: Byter aktivt
                kartlager — bara ett lager är aktivt åt gången</li>
            <li><b>Klick på sensor-markör</b>: Visar sensor-popup med parameter och senaste värde</li>
            <li><b>Högerklick på karta</b>: Lägg till custom marker (sparas i databasen)</li>
            <li><b>Scroll på karta</b>: Zooma in/ut</li>
            <li><b>Dra på karta</b>: Panora kartan</li>
        </ul>

        <h2>Menubar</h2>
        <ul>
            <li><b>Generera</b> → Välj läge: Öppnar grafgenerering för valt läge</li>
            <li><b>Hjälp</b> → Funktioner och Hjälp: Öppnar denna hjälpdialog</li>
            <li><b>Hjälp</b> → Inställningar: Öppnar inställningsdialogen</li>
        </ul>
        """

    # ------------------------------------------------------------------
    # Tab: Felsökning  (A7 — updated)
    # ------------------------------------------------------------------

    def _get_troubleshooting_content(self) -> str:
        """Get troubleshooting tab content."""
        return """
        <h1>Felsökning</h1>

        <h2>Applikationen startar inte</h2>
        <ul>
            <li>Kontrollera att alla beroenden är installerade:
                <code>pip install -r requirements.txt</code></li>
            <li>Kontrollera Python-version: Kräver Python 3.7 eller senare</li>
            <li>Kolla loggfiler i <code>logs/</code> katalogen</li>
        </ul>

        <h2>Inga väderdata</h2>
        <ul>
            <li>Kontrollera API-nycklar i <b>Inställningar → API-nycklar</b>
                eller i <code>.env</code></li>
            <li>Kolla <b>API Status</b>-fliken för källstatus</li>
            <li>Kontrollera nätverksanslutning</li>
        </ul>

        <h2>Heatmap renderas inte</h2>
        <p><b>Symptom</b>: Kartans heatmap-lager är tomt, eller konsolen visar
        <code>IndexSizeError: Failed to execute 'getImageData': The source width is 0</code></p>
        <p><b>Rotorsak</b>: Qt:s layoutmotor tilldelar canvas-dimensioner <i>efter</i>
        Leaflets konstruktor körs. Canvas rapporterar width = 0, varvid
        <code>leaflet.heat</code> kastar ett <code>IndexSizeError</code> vid försök att rita.</p>
        <p><b>Tillämpad fix</b>: Heatmap-skapandet fördröjs med <code>setTimeout(..., 300)</code>
        kombinerat med <code>map.invalidateSize()</code>. Detta tvingar Leaflet att återfråga
        behållarens pixeldimensioner från Qt:s layoutmotor innan <code>leaflet.heat</code>
        försöker rita.</p>
        <p><b>Om problemet kvarstår</b>:</p>
        <ul>
            <li>Kontrollera PyQtWebEngine-version:
                <code>pip show PyQtWebEngine</code></li>
            <li>Om du kör utan skärm (headless): inaktivera GPU-kompositering via miljövariabeln
                <code>QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu</code></li>
        </ul>

        <h2>Kartan fungerar inte (Stationer-fliken)</h2>
        <ul>
            <li>Installera PyQtWebEngine: <code>pip install PyQtWebEngine</code></li>
            <li>Kolla loggfiler för detaljerade felmeddelanden</li>
        </ul>

        <h2>Grafer genereras inte</h2>
        <ul>
            <li>Kontrollera att data finns i databasen</li>
            <li>För Daglig läge: välj ett datum med data</li>
            <li>Kolla <code>output/</code> katalogen och statusbaren</li>
        </ul>

        <h2>"Ingen data" visas överallt</h2>
        <ul>
            <li>Klicka "Hämta nu" (F5) för att hämta data från API:er</li>
            <li>Kontrollera API-nycklar och nätverksanslutning</li>
            <li>Lägg till minst en stad i vänsterpanelen</li>
        </ul>

        <h2>Inställningar återställdes efter omstart</h2>
        <ul>
            <li>Kontrollera att <code>config.json</code> finns och är skrivbar</li>
            <li>Vid uppgradering: nya nycklar läggs till automatiskt utan att befintliga
                användarvärden skrivs över (setdefault-merge)</li>
        </ul>

        <h2>Rate limit-fel</h2>
        <ul>
            <li>Öka auto-update intervall i <b>Inställningar → Data</b></li>
            <li>Kolla loggfiler för detaljerade rate limit-meddelanden</li>
        </ul>

        <h2>Databasfel</h2>
        <ul>
            <li>Kontrollera att <code>weather.db</code> finns och är skrivbar</li>
            <li>Databasen skapas automatiskt vid första start</li>
            <li>Om problem kvarstår: ta bort <code>weather.db</code> och starta om
                (obs: all historik förloras)</li>
        </ul>
        """
