"""Help dialog with feature dictionary."""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QTextEdit, QPushButton, QDialogButtonBox
)
from PyQt5.QtCore import Qt
from analytics.graph_modes import MODES


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
        
        # Create tab widget
        self.tabs = QTabWidget()
        
        # Add tabs with content
        self.tabs.addTab(self._create_text_widget(self._get_overview_content()), "Översikt")
        self.tabs.addTab(self._create_text_widget(self._get_weather_content()), "Väderdata")
        self.tabs.addTab(self._create_text_widget(self._get_air_quality_content()), "Luftkvalitet")
        self.tabs.addTab(self._create_text_widget(self._get_graphs_content()), "Grafer")
        self.tabs.addTab(self._create_text_widget(self._get_stations_content()), "Stationer")
        self.tabs.addTab(self._create_text_widget(self._get_statistics_content()), "Statistik")
        self.tabs.addTab(self._create_text_widget(self._get_shortcuts_content()), "Kortkommandon")
        self.tabs.addTab(self._create_text_widget(self._get_troubleshooting_content()), "Felsökning")
        
        layout.addWidget(self.tabs)
        
        # Close button
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
    
    def _get_overview_content(self) -> str:
        """Get overview tab content."""
        return """
        <h1>Väderapplikation - Översikt</h1>
        
        <h2>Vad är detta?</h2>
        <p>En produktionsklar väderapplikation som samlar väderdata och luftkvalitetsdata från flera gratis API-källor. 
        Applikationen lagrar data lokalt i en SQLite-databas och ger dig detaljerad statistik, varningar och historik.</p>
        
        <h2>Snabbstart</h2>
        <ol>
            <li><b>Starta applikationen</b>: Kör <code>python main.py</code></li>
            <li><b>Lägg till städer</b>: Klicka på "Lägg till stad" i vänsterpanelen</li>
            <li><b>Hämta data</b>: Klicka på "Hämta nu" (F5) eller aktivera "Auto-uppdatering"</li>
            <li><b>Utforska</b>: Använd flikarna för att se statistik, historik, varningar och grafer</li>
        </ol>
        
        <h2>Huvudkomponenter</h2>
        <ul>
            <li><b>Vänsterpanel</b>: Lista över städer, lägg till/ta bort städer</li>
            <li><b>Huvudpanel</b>: Aktuell väderdata och luftkvalitet för vald stad</li>
            <li><b>Flikar</b>: Historik, Statistik, Översikt, Varningar, Stationer, API Status, Loggar</li>
            <li><b>Menubar</b>: Generera grafer i olika tidsperioder</li>
            <li><b>Verktygsfält</b>: Manuell uppdatering och auto-update toggle</li>
        </ul>
        
        <h2>Real-time Uppdatering</h2>
        <p>GUI:t uppdateras automatiskt var 5:e sekund med senaste data från databasen. 
        Detta är oberoende av auto-update och hämtar inte ny data från API:er, utan visar bara data som redan finns i databasen.</p>
        
        <h2>Designprinciper</h2>
        <ul>
            <li><b>Inga fallback-värden</b>: Visar endast verklig data eller "Ingen data"</li>
            <li><b>Dynamisk</b>: Inga hårdkodade städer eller värden</li>
            <li><b>Transparent</b>: Du ser exakt vad som händer</li>
        </ul>
        """
    
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
            <li><b>OpenWeatherMap</b> (Backup): Väderdata, kräver gratis API-nyckel</li>
        </ul>
        
        <h2>Uppdatering</h2>
        <h3>Manuell uppdatering</h3>
        <ul>
            <li>Klicka på <b>"Hämta nu"</b> i verktygsfältet</li>
            <li>Eller tryck <b>F5</b></li>
            <li>Hämtar data för alla städer från API:er</li>
        </ul>
        
        <h3>Automatisk uppdatering</h3>
        <ul>
            <li>Aktivera <b>"Auto-uppdatering"</b> i verktygsfältet</li>
            <li>Uppdaterar automatiskt var 10:e minut (standardintervall)</li>
            <li>Kan stängas av när som helst</li>
        </ul>
        
        <h2>Historik</h2>
        <p>All väderdata sparas i databasen. Du kan se historiska data i <b>Historik</b>-fliken genom att välja en stad från dropdown-menyn.</p>
        
        <h2>Intelligent Lagring</h2>
        <p>Systemet använder measurement timestamps från API:er för att undvika duplicering. 
        Om samma mätning hämtas flera gånger sparas den bara en gång.</p>
        """
    
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
        <table border="1" cellpadding="5">
            <tr>
                <th>AQI</th>
                <th>PM2.5 (µg/m³)</th>
                <th>Nivå</th>
                <th>Färg</th>
            </tr>
            <tr>
                <td>0-50</td>
                <td>0.0-12.0</td>
                <td>Bra</td>
                <td style="background-color: #00e400; color: white;">🟢 Grön</td>
            </tr>
            <tr>
                <td>51-100</td>
                <td>12.1-35.4</td>
                <td>Acceptabelt</td>
                <td style="background-color: #ffff00;">🟡 Gul</td>
            </tr>
            <tr>
                <td>101-150</td>
                <td>35.5-55.4</td>
                <td>För känsliga personer</td>
                <td style="background-color: #ff7e00; color: white;">🟠 Orange</td>
            </tr>
            <tr>
                <td>151-200</td>
                <td>55.5-150.4</td>
                <td>Ohälsosamt</td>
                <td style="background-color: #ff0000; color: white;">🔴 Röd</td>
            </tr>
            <tr>
                <td>201-300</td>
                <td>150.5-250.4</td>
                <td>Mycket ohälsosamt</td>
                <td style="background-color: #8f3f97; color: white;">🟣 Lila</td>
            </tr>
            <tr>
                <td>301-500</td>
                <td>>250.4</td>
                <td>Farligt</td>
                <td style="background-color: #7e0023; color: white;">⚫ Mörkröd</td>
            </tr>
        </table>
        
        <h2>Datakällor</h2>
        <ul>
            <li><b>OpenAQ</b>: Rådata för PM2.5, PM10, NO₂, O₃ (kräver API-nyckel)</li>
            <li><b>OpenWeatherMap</b>: Kategorisk AQI och rådata (kräver API-nyckel)</li>
        </ul>
        
        <h2>Varningar</h2>
        <p>Applikationen genererar automatiskt varningar för farliga luftkvalitetsnivåer. 
        Se <b>Varningar</b>-fliken för nationell översikt och regionala varningar.</p>
        
        <h2>Intelligent Lagring</h2>
        <p>Luftkvalitetsdata kontrolleras mot measurement timestamps för att undvika duplicering. 
        Om samma mätning hämtas flera gånger sparas den bara en gång.</p>
        """
    
    def _get_graphs_content(self) -> str:
        """Get graphs tab content."""
        # Get available modes dynamically
        modes_list = []
        for mode_name, mode_class in MODES.items():
            modes_list.append(f"<li><b>{mode_name}</b></li>")
        modes_html = "".join(modes_list)
        
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
        
        <h2>Daglig Läge</h2>
        <ul>
            <li>Timme-för-timme graf för valt datum (0-23 timmar)</li>
            <li>X-axel: Timmar (0-23)</li>
            <li>Y-axel: Parametervärden</li>
            <li>Ingen legend (en datapunkt per timme)</li>
            <li>Aggregerad per timme om flera datapunkter finns</li>
        </ul>
        
        <h2>Veckovis/Månadsvis/Årlig Läge</h2>
        <ul>
            <li>Aggregerad data per period</li>
            <li>X-axel: Riktiga timestamps</li>
            <li>Y-axel: Parametervärden</li>
            <li>Legend visar period-gruppering</li>
        </ul>
        
        <h2>Export</h2>
        <ul>
            <li>Grafer sparas i <code>output/</code> katalogen</li>
            <li>Filnamn: <code>&lt;stad_namn&gt;_&lt;timestamp&gt;.png</code></li>
            <li>Nationell graf: <code>sweden_&lt;timestamp&gt;.png</code></li>
            <li>En graf per stad + en nationell graf</li>
        </ul>
        
        <h2>Tekniska Detaljer</h2>
        <ul>
            <li><b>Bakgrundstråd</b>: Grafgenerering körs i QThread för att hålla GUI responsivt</li>
            <li><b>Inga fallbacks</b>: Om data saknas returneras None, ingen tom graf genereras</li>
            <li><b>Minimal styling</b>: Svarta linjer, grid, inga färger (ren analysartefakt)</li>
            <li><b>Dynamisk layout</b>: En subplot per parameter, inga dual-axis</li>
        </ul>
        """
    
    def _get_stations_content(self) -> str:
        """Get stations tab content."""
        return """
        <h1>Stationer och Sensorer</h1>
        
        <h2>Interaktiv Karta</h2>
        <p>Stationer-fliken visar alla OpenAQ-stationer och sensorer på en interaktiv Leaflet-karta.</p>
        
        <h2>Funktioner</h2>
        <ul>
            <li><b>Visa sensorer</b>: Alla OpenAQ-sensorer för städer i databasen visas automatiskt</li>
            <li><b>Sensor-popups</b>: Klicka på en marker för att se sensor-information:
                <ul>
                    <li>Sensor-ID</li>
                    <li>Parameter (PM2.5, PM10, NO2, O3)</li>
                    <li>Senaste värde</li>
                    <li>Koordinater</li>
                    <li>Google Maps-länk</li>
                </ul>
            </li>
            <li><b>Custom markers</b>: Högerklicka på kartan för att lägga till egna sensorer/markörer</li>
            <li><b>Zoom och scroll</b>: Scrolla för att zooma, dra för att panora</li>
        </ul>
        
        <h2>Uppdatera Stationer</h2>
        <ul>
            <li>Klicka på <b>"Uppdatera Stationer"</b> för att ladda om sensor-data från databasen</li>
            <li>Sensorer uppdateras automatiskt när OpenAQ returnerar data</li>
            <li>Data läses från databasen (database-first approach)</li>
        </ul>
        
        <h2>Custom Markers</h2>
        <ol>
            <li>Högerklicka på kartan där du vill lägga till en marker</li>
            <li>Fyll i formuläret:
                <ul>
                    <li>Namn</li>
                    <li>Beskrivning</li>
                    <li>Värde (valfritt)</li>
                </ul>
            </li>
            <li>Klicka OK för att spara</li>
            <li>Markern visas på kartan och sparas i databasen</li>
        </ol>
        
        <h2>Krav</h2>
        <p><b>PyQtWebEngine</b> måste vara installerat för att kartan ska fungera:</p>
        <ul>
            <li>Installera med: <code>pip install PyQtWebEngine</code></li>
            <li>Om inte installerat: Applikationen fungerar normalt, men kartan visas inte</li>
            <li>Ett felmeddelande visas i Stationer-fliken om WebEngine saknas</li>
        </ul>
        
        <h2>Google Maps Integration</h2>
        <p>Varje sensor-popup innehåller en länk till Google Maps som öppnar sensorens plats i en webbläsare.</p>
        """
    
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
        <p>Visa snittvärden över alla städer:</p>
        <ul>
            <li><b>Snitttemperatur</b>: Genomsnittlig temperatur</li>
            <li><b>Snittfuktighet</b>: Genomsnittlig luftfuktighet</li>
            <li><b>Snittvindhastighet</b>: Genomsnittlig vindhastighet</li>
            <li><b>Snitt PM2.5</b>: Genomsnittlig PM2.5</li>
            <li><b>Snitt AQI</b>: Beräknad från snitt PM2.5</li>
        </ul>
        
        <h2>Tidsperioder</h2>
        <p>Välj mellan:</p>
        <ul>
            <li><b>Senaste värden</b>: Nuvarande värden för alla städer</li>
            <li><b>24h snitt</b>: 24-timmars rullande medelvärden</li>
        </ul>
        
        <h2>Metadata</h2>
        <ul>
            <li><b>Antal städer</b>: Totalt antal städer i databasen</li>
            <li><b>Datapunkter</b>: Totalt antal sparade mätningar i weather_data tabellen</li>
            <li><b>Senaste uppdatering</b>: Tidpunkt för senaste datapunkt</li>
        </ul>
        
        <h2>Varningar-fliken</h2>
        <ul>
            <li><b>Nationell översikt</b>: Snitt PM2.5 och AQI över alla städer</li>
            <li><b>Regionala varningar</b>: Städer med farliga PM2.5-nivåer</li>
            <li><b>Top 10 städer</b>: Städer med högst PM2.5-värden</li>
            <li><b>Färgkodning</b>: Visuell indikering av varningsnivåer</li>
        </ul>
        """
    
    def _get_shortcuts_content(self) -> str:
        """Get keyboard shortcuts tab content."""
        return """
        <h1>Kortkommandon</h1>
        
        <h2>Verktygsfält</h2>
        <table border="1" cellpadding="5">
            <tr>
                <th>Kortkommando</th>
                <th>Funktion</th>
            </tr>
            <tr>
                <td><b>F5</b></td>
                <td>Manuell uppdatering av all väderdata</td>
            </tr>
        </table>
        
        <h2>Musinteraktion</h2>
        <ul>
            <li><b>Vänsterklick på stad</b>: Välj stad och visa detaljerad information</li>
            <li><b>Vänsterklick på sensor-marker</b>: Visa sensor-popup med information</li>
            <li><b>Högerklick på karta</b>: Lägg till custom marker (i Stationer-fliken)</li>
            <li><b>Scroll på karta</b>: Zooma in/ut</li>
            <li><b>Dra på karta</b>: Panora kartan</li>
        </ul>
        
        <h2>Menubar</h2>
        <ul>
            <li><b>Generera</b> → Välj läge: Öppnar grafgenerering för valt läge</li>
            <li><b>Hjälp</b> → Funktioner och Hjälp: Öppnar denna hjälpdialog</li>
        </ul>
        """
    
    def _get_troubleshooting_content(self) -> str:
        """Get troubleshooting tab content."""
        return """
        <h1>Felsökning</h1>
        
        <h2>Applikationen startar inte</h2>
        <ul>
            <li>Kontrollera att alla beroenden är installerade: <code>pip install -r requirements.txt</code></li>
            <li>Kontrollera Python-version: Kräver Python 3.7 eller senare</li>
            <li>Kolla loggfiler i <code>logs/</code> katalogen för detaljerade felmeddelanden</li>
        </ul>
        
        <h2>Inga väderdata</h2>
        <ul>
            <li><b>Kontrollera API-nycklar</b>:
                <ul>
                    <li>Öppna <code>.env</code> filen</li>
                    <li>Kontrollera att <code>OPENWEATHER_API_KEY</code> och <code>OPENAQ_API_KEY</code> är korrekt ifyllda</li>
                    <li>Eller kontrollera <code>config.json</code> (om används)</li>
                </ul>
            </li>
            <li><b>Kolla API Status-fliken</b>: Visar status för alla API-källor</li>
            <li><b>Kontrollera nätverksanslutning</b>: API:er kräver internetanslutning</li>
            <li><b>Kolla loggfiler</b>: <code>logs/</code> katalogen innehåller detaljerade felmeddelanden</li>
        </ul>
        
        <h2>Kartan fungerar inte (Stationer-fliken)</h2>
        <ul>
            <li><b>Installera PyQtWebEngine</b>: <code>pip install PyQtWebEngine</code></li>
            <li>Om installationen misslyckas: Kontrollera att PyQt5 är korrekt installerat</li>
            <li>Om kartan fortfarande inte fungerar: Kolla loggfiler för detaljerade felmeddelanden</li>
        </ul>
        
        <h2>Grafer genereras inte</h2>
        <ul>
            <li><b>Kontrollera att data finns</b>: Grafer genereras bara om data finns i databasen</li>
            <li><b>För Daglig läge</b>: Välj ett datum som har data</li>
            <li><b>Kolla status bar</b>: Visar felmeddelanden om grafgenerering misslyckas</li>
            <li><b>Kontrollera output-katalogen</b>: Grafer sparas i <code>output/</code> katalogen</li>
        </ul>
        
        <h2>"Ingen data" visas överallt</h2>
        <ul>
            <li><b>Hämta data först</b>: Klicka på "Hämta nu" (F5) för att hämta data från API:er</li>
            <li><b>Aktivera auto-update</b>: För automatisk datahämtning</li>
            <li><b>Kontrollera API-nycklar</b>: Se ovan</li>
            <li><b>Kontrollera städer</b>: Lägg till minst en stad i vänsterpanelen</li>
        </ul>
        
        <h2>Rate limit-fel</h2>
        <ul>
            <li>Applikationen hanterar detta automatiskt med rate limiting</li>
            <li>Om problem kvarstår: Öka väntetid mellan uppdateringar i config</li>
            <li>Kontrollera loggfiler för detaljerade rate limit-meddelanden</li>
        </ul>
        
        <h2>Databasfel</h2>
        <ul>
            <li><b>Kontrollera databasfil</b>: <code>weather.db</code> ska finnas i projektmappen</li>
            <li><b>Kontrollera skrivrättigheter</b>: Applikationen behöver skrivrättigheter för databasfilen</li>
            <li><b>Kontrollera schema</b>: Databasen skapas automatiskt vid första start</li>
            <li>Om problem kvarstår: Ta bort <code>weather.db</code> och starta om (varning: förlorar all data)</li>
        </ul>
        
        <h2>Få mer hjälp</h2>
        <ul>
            <li><b>Loggfiler</b>: Kolla <code>logs/</code> katalogen för detaljerade felmeddelanden</li>
            <li><b>API Status-fliken</b>: Visar status för alla API-källor</li>
            <li><b>Loggar-fliken</b>: Visar systemloggar i GUI</li>
        </ul>
        """
