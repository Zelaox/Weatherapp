"""Stations tab with interactive Leaflet map showing OpenAQ sensors."""

import json
from typing import List, Dict, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox
)
from PyQt5.QtCore import Qt, QUrl
import logging

# Try to import QWebEngineView (optional dependency)
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    WEBENGINE_AVAILABLE = False

logger = logging.getLogger("WeatherApp.gui.stations_tab")


class CustomMarkerDialog(QDialog):
    """Dialog for adding custom markers."""
    
    def __init__(self, parent=None, lat: Optional[float] = None, lon: Optional[float] = None):
        super().__init__(parent)
        self.setWindowTitle("Lägg till Custom Marker")
        self.setModal(True)
        self._init_ui(lat, lon)
    
    def _init_ui(self, lat: Optional[float], lon: Optional[float]):
        """Initialize UI."""
        layout = QFormLayout(self)
        
        self.lat_input = QLineEdit()
        if lat is not None:
            self.lat_input.setText(str(lat))
        self.lat_input.setPlaceholderText("t.ex. 59.3293")
        layout.addRow("Latitud:", self.lat_input)
        
        self.lon_input = QLineEdit()
        if lon is not None:
            self.lon_input.setText(str(lon))
        self.lon_input.setPlaceholderText("t.ex. 18.0686")
        layout.addRow("Longitud:", self.lon_input)
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("t.ex. Min sensor")
        layout.addRow("Namn:", self.name_input)
        
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("t.ex. Luftkvalitetssensor hemma")
        layout.addRow("Beskrivning:", self.desc_input)
        
        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("Valfritt värde (t.ex. 15.5)")
        layout.addRow("Värde (µg/m³):", self.value_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
    
    def _validate_and_accept(self):
        """Validate input and accept."""
        try:
            lat = float(self.lat_input.text().strip())
            lon = float(self.lon_input.text().strip())
            
            if not (-90 <= lat <= 90):
                QMessageBox.warning(self, "Fel", "Latitud måste vara mellan -90 och 90")
                return
            
            if not (-180 <= lon <= 180):
                QMessageBox.warning(self, "Fel", "Longitud måste vara mellan -180 och 180")
                return
            
            self.latitude = lat
            self.longitude = lon
            self.name = self.name_input.text().strip()
            self.description = self.desc_input.text().strip()
            
            # Parse optional value
            value_str = self.value_input.text().strip()
            self.value = float(value_str) if value_str else None
            
            self.accept()
        except ValueError:
            QMessageBox.warning(self, "Fel", "Ogiltiga koordinater eller värde")
    
    def get_marker_data(self) -> Dict:
        """Get marker data."""
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "name": self.name,
            "description": self.description,
            "value": self.value
        }


class StationsTab(QWidget):
    """Tab showing stations and sensors on interactive map."""
    
    def __init__(self, controller):
        """
        Initialize stations tab.
        
        Args:
            controller: Weather controller instance
        """
        super().__init__()
        self.controller = controller
        self._sensors_loaded = False
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Check WebEngine availability
        if not WEBENGINE_AVAILABLE:
            error_label = QLabel("WebEngine krävs för karta. Installera PyQtWebEngine.")
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: red; font-size: 14px; padding: 20px;")
            layout.addWidget(error_label)
            return
        
        # Toolbar with refresh button
        toolbar = QHBoxLayout()
        refresh_button = QPushButton("Uppdatera Stationer")
        refresh_button.clicked.connect(self._refresh_map)
        toolbar.addWidget(refresh_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        # Map view
        self.map_view = QWebEngineView()
        layout.addWidget(self.map_view)
        
        # Load map on first show
        self._load_map()
    
    def _check_webengine_available(self) -> bool:
        """Check if WebEngine is available."""
        return WEBENGINE_AVAILABLE
    
    def _load_sensors(self) -> List[Dict]:
        """
        Load sensors from database.
        
        Returns:
            List of sensor dictionaries, empty list if no sensors found
        """
        try:
            sensors = self.controller.db.get_all_sensors()
            logger.info(f"Hämtade {len(sensors)} sensorer från databas")
            return sensors
        except Exception as e:
            logger.error(f"Fel vid hämtning av sensorer: {e}")
            return []
    
    def _generate_map_html(self, sensors: List[Dict]) -> str:
        """
        Generate HTML with Leaflet map.
        
        Args:
            sensors: List of sensor dictionaries
            
        Returns:
            HTML string
        """
        # Convert sensors to JSON
        sensors_json = json.dumps(sensors, default=str)
        
        # Calculate center and bounds from sensors
        if sensors:
            lats = [s.get('latitude') for s in sensors if s.get('latitude') is not None]
            lons = [s.get('longitude') for s in sensors if s.get('longitude') is not None]
            if lats and lons:
                center_lat = sum(lats) / len(lats)
                center_lon = sum(lons) / len(lons)
                zoom = 6  # Default zoom for Sweden
            else:
                center_lat, center_lon, zoom = 62.0, 15.0, 5  # Center on Sweden
        else:
            center_lat, center_lon, zoom = 62.0, 15.0, 5  # Center on Sweden
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; }}
        #map {{ height: 100vh; width: 100%; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([{center_lat}, {center_lon}], {zoom});
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '© OpenStreetMap contributors'
        }}).addTo(map);
        
        // Zoom controls
        L.control.zoom({{ position: 'topright' }}).addTo(map);
        
        // Enable scroll to zoom (default)
        map.scrollWheelZoom.enable();
        
        // Sensors data from Python
        var sensors = {sensors_json};
        
        // Add markers
        sensors.forEach(function(sensor) {{
            var lat = sensor.latitude;
            var lon = sensor.longitude;
            
            if (lat == null || lon == null) {{
                return; // Skip sensors without coordinates
            }}
            
            var marker = L.marker([lat, lon]).addTo(map);
            
            // Build popup content
            var popupContent = '';
            
            if (sensor.is_custom == 1) {{
                // Custom marker
                var customInfo = sensor.custom_info ? JSON.parse(sensor.custom_info) : {{}};
                popupContent += '<b>' + (customInfo.name || 'Custom Marker') + '</b><br>';
                if (customInfo.description) {{
                    popupContent += customInfo.description + '<br>';
                }}
                if (customInfo.value != null) {{
                    popupContent += 'Värde: ' + customInfo.value + ' µg/m³<br>';
                }}
            }} else {{
                // OpenAQ sensor
                popupContent += '<b>' + (sensor.parameter || 'Sensor') + '</b><br>';
                if (sensor.last_value != null) {{
                    popupContent += 'Värde: ' + sensor.last_value + ' µg/m³<br>';
                }}
                if (sensor.city_name) {{
                    popupContent += 'Stad: ' + sensor.city_name + '<br>';
                }}
            }}
            
            popupContent += '<a href="https://www.google.com/maps?q=' + lat + ',' + lon + '" target="_blank">Öppna i Google Maps</a>';
            
            marker.bindPopup(popupContent);
        }});
        
        // Right-click context menu
        map.on('contextmenu', function(e) {{
            // Store coordinates for Python
            window.mapRightClickLat = e.latlng.lat;
            window.mapRightClickLon = e.latlng.lng;
            
            // Trigger Python callback via page title change (workaround for QWebEngineView)
            document.title = 'MAP_RIGHT_CLICK:' + e.latlng.lat + ',' + e.latlng.lng;
        }});
    </script>
</body>
</html>"""
        return html
    
    def _load_map(self):
        """Load map with sensors."""
        if not WEBENGINE_AVAILABLE:
            return
        
        sensors = self._load_sensors()
        
        if not sensors:
            logger.info("Inga sensorer hittades, visar tom karta")
        
        html = self._generate_map_html(sensors)
        self.map_view.setHtml(html)
        
        # Monitor page title for right-click events
        self.map_view.page().titleChanged.connect(self._on_title_changed)
        
        self._sensors_loaded = True
    
    def _on_title_changed(self, title: str):
        """Handle title change (used for right-click detection)."""
        if title.startswith('MAP_RIGHT_CLICK:'):
            try:
                coords_str = title.replace('MAP_RIGHT_CLICK:', '')
                lat_str, lon_str = coords_str.split(',')
                lat = float(lat_str)
                lon = float(lon_str)
                self._on_map_right_click(lat, lon)
                # Reset title
                self.map_view.page().runJavaScript("document.title = 'Stations Map';")
            except (ValueError, IndexError) as e:
                logger.warning(f"Fel vid parsing av right-click koordinater: {e}")
    
    def _on_map_right_click(self, lat: float, lon: float):
        """Handle right-click on map."""
        dialog = CustomMarkerDialog(self, lat, lon)
        if dialog.exec_() == QDialog.Accepted:
            marker_data = dialog.get_marker_data()
            
            # Find city for this location (nearest city or create new)
            cities = self.controller.get_all_cities()
            nearest_city = None
            min_distance = float('inf')
            
            for city in cities:
                city_lat = city['latitude']
                city_lon = city['longitude']
                # Simple distance calculation
                distance = ((lat - city_lat) ** 2 + (lon - city_lon) ** 2) ** 0.5
                if distance < min_distance:
                    min_distance = distance
                    nearest_city = city
            
            if nearest_city and min_distance < 0.5:  # Within ~50km
                city_id = nearest_city['id']
            else:
                # Use first city as fallback (or could create new city)
                if cities:
                    city_id = cities[0]['id']
                else:
                    QMessageBox.warning(self, "Fel", "Inga städer hittades. Lägg till en stad först.")
                    return
            
            # Create custom_info JSON
            custom_info = json.dumps({
                "name": marker_data["name"],
                "description": marker_data["description"],
                "value": marker_data["value"]
            })
            
            try:
                self.controller.db.add_custom_marker(
                    city_id=city_id,
                    latitude=lat,
                    longitude=lon,
                    custom_info=custom_info
                )
                logger.info(f"Lade till custom marker för stad {city_id}")
                QMessageBox.information(self, "Klart", "Custom marker tillagd!")
                self._refresh_map()
            except Exception as e:
                logger.error(f"Fel vid tillägg av custom marker: {e}")
                QMessageBox.warning(self, "Fel", f"Kunde inte lägga till marker: {e}")
    
    def _refresh_map(self):
        """Refresh map by reloading sensors from database."""
        logger.info("Uppdaterar karta med sensorer från databas")
        self._load_map()
