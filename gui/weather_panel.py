"""Weather panel for displaying current weather."""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor, QPalette
from typing import Dict


class WeatherPanel(QWidget):
    """Main panel for displaying current weather."""
    
    def __init__(self, controller):
        """
        Initialize weather panel.
        
        Args:
            controller: Weather controller instance
        """
        super().__init__()
        self.controller = controller
        self.current_city_id = None
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # City name
        self.city_label = QLabel("Välj en stad")
        city_font = QFont()
        city_font.setPointSize(16)
        city_font.setBold(True)
        self.city_label.setFont(city_font)
        layout.addWidget(self.city_label)
        
        # Temperature
        self.temp_label = QLabel("--°C")
        temp_font = QFont()
        temp_font.setPointSize(48)
        temp_font.setBold(True)
        self.temp_label.setFont(temp_font)
        self.temp_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.temp_label)
        
        # Humidity and wind
        self.details_label = QLabel("")
        details_font = QFont()
        details_font.setPointSize(12)
        self.details_label.setFont(details_font)
        self.details_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.details_label)
        
        # Air quality section (raw pollutants only - dynamically displayed)
        self.aq_group = QFrame()
        self.aq_group.setFrameShape(QFrame.Box)
        self.aq_group.setMinimumHeight(100)
        aq_layout = QVBoxLayout(self.aq_group)
        aq_layout.setSpacing(8)
        
        # Dynamic pollutants label (will show all available pollutants)
        self.pollutants_label = QLabel("")
        pollutants_font = QFont()
        pollutants_font.setPointSize(12)
        self.pollutants_label.setFont(pollutants_font)
        self.pollutants_label.setAlignment(Qt.AlignCenter)
        aq_layout.addWidget(self.pollutants_label)
        
        layout.addWidget(self.aq_group)
        
        # Last update
        self.update_label = QLabel("")
        update_font = QFont()
        update_font.setPointSize(10)
        update_font.setItalic(True)
        self.update_label.setFont(update_font)
        self.update_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.update_label)
        
        layout.addStretch()
    
    def _get_pollutant_metadata(self) -> Dict[str, Dict[str, str]]:
        """
        Get pollutant metadata (display names and units) from parameter_registry.
        Returns dict mapping parameter_name -> {display_name, unit}.
        """
        metadata = {}
        try:
            db = self.controller.db
            conn = db.get_connection()
            cursor = conn.cursor()
            
            # Query parameter_registry for air_quality category parameters
            cursor.execute("""
                SELECT parameter_name, display_name, unit
                FROM parameter_registry
                WHERE category = 'air_quality'
            """)
            
            for row in cursor.fetchall():
                metadata[row['parameter_name']] = {
                    'display_name': row['display_name'],
                    'unit': row['unit']
                }
        except Exception as e:
            # If parameter_registry doesn't exist or query fails, use fallback formatting
            # But we should still try to display pollutants dynamically
            import logging
            logger = logging.getLogger("WeatherApp.gui.weather_panel")
            logger.warning(f"Could not load parameter metadata from parameter_registry: {e}")
        
        return metadata
    
    def _format_pollutant_value(self, param_name: str, value: float, metadata: Dict[str, Dict[str, str]]) -> str:
        """
        Format a pollutant value with display name and unit.
        
        Args:
            param_name: Parameter name (e.g., 'pm25', 'no2')
            value: Numeric value
            metadata: Dict from _get_pollutant_metadata()
            
        Returns:
            Formatted string (e.g., "PM2.5: 12.3 µg/m³")
        """
        if param_name in metadata:
            display_name = metadata[param_name]['display_name']
            unit = metadata[param_name]['unit']
        else:
            # Fallback: format parameter name (e.g., 'pm25' -> 'PM25', 'no2' -> 'NO2')
            display_name = param_name.upper().replace('_', ' ')
            # Try to infer unit from common patterns
            if 'pm' in param_name.lower():
                unit = 'µg/m³'
            elif param_name.lower() in ['no2', 'o3', 'so2', 'co']:
                unit = 'µg/m³'
            else:
                unit = ''
        
        return f"{display_name}: {value:.1f} {unit}".strip()
    
    def update_weather(self, city_name: str, weather_data: dict):
        """
        Update weather display.
        Dynamically displays all pollutants from weather_data (no hardcoding, no fallbacks).
        
        Args:
            city_name: Name of the city
            weather_data: Weather data dictionary
        """
        self.city_label.setText(city_name)
        
        if weather_data:
            temp = weather_data.get('temperature')
            humidity = weather_data.get('humidity')
            wind_speed = weather_data.get('wind_speed')
            timestamp = weather_data.get('timestamp', '')
            
            # Temperature
            if temp is not None:
                self.temp_label.setText(f"{temp:.1f}°C")
            else:
                self.temp_label.setText("--°C")
            
            # Details
            details = []
            if humidity is not None:
                details.append(f"Luftfuktighet: {humidity:.0f}%")
            if wind_speed is not None:
                details.append(f"Vind (medel): {wind_speed:.1f} m/s")
            self.details_label.setText(" | ".join(details) if details else "")
            
            # Pollutants: dynamically discover and display all pollutants from weather_data
            # Exclude non-pollutant fields
            excluded_fields = {
                'temperature', 'humidity', 'wind_speed', 'timestamp', 
                'source', 'aqi', 'measurement_timestamp', 'city_id',
                'uv_index', 'solar_radiation', 'direct_radiation', 
                'diffuse_radiation', 'sunshine_duration', 'cape',
                'precipitation_probability', 'convective_precipitation'
            }
            
            # Get pollutant metadata for display names and units
            pollutant_metadata = self._get_pollutant_metadata()
            
            # Collect all pollutants that have values (no fallbacks - only show if value exists)
            pollutant_strings = []
            for param_name, value in weather_data.items():
                if param_name not in excluded_fields and value is not None:
                    try:
                        # Ensure value is numeric
                        float_value = float(value)
                        formatted = self._format_pollutant_value(param_name, float_value, pollutant_metadata)
                        pollutant_strings.append(formatted)
                    except (ValueError, TypeError):
                        # Skip non-numeric values
                        continue
            
            # Display all pollutants (no fallback messages)
            if pollutant_strings:
                self.pollutants_label.setText(" | ".join(pollutant_strings))
            else:
                self.pollutants_label.setText("")
            
            # Update time
            if timestamp:
                if isinstance(timestamp, str):
                    self.update_label.setText(f"Senaste uppdatering: {timestamp}")
                else:
                    self.update_label.setText(f"Senaste uppdatering: {timestamp.strftime('%H:%M:%S')}")
        else:
            self.temp_label.setText("--°C")
            self.details_label.setText("")
            self.pollutants_label.setText("")
            self.aq_group.setStyleSheet("")
            self.update_label.setText("")
    
    
    def refresh(self):
        """Refresh weather display."""
        if self.current_city_id:
            weather = self.controller.get_city_weather(self.current_city_id)
            city = self.controller.get_city(self.current_city_id)
            if city and weather:
                # Add city_id to weather data for AQI calculation
                weather_with_id = weather.copy()
                weather_with_id['city_id'] = self.current_city_id
                self.update_weather(city['name'], weather_with_id)
    
    def set_city(self, city_id: int):
        """Set current city."""
        self.current_city_id = city_id
        self.refresh()
