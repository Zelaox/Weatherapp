"""Weather panel for displaying current weather."""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor, QPalette


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
        
        # Air quality section (raw pollutants only)
        self.aq_group = QFrame()
        self.aq_group.setFrameShape(QFrame.Box)
        self.aq_group.setMinimumHeight(100)
        aq_layout = QVBoxLayout(self.aq_group)
        aq_layout.setSpacing(8)
        
        # PM2.5 (primary)
        self.pm25_label = QLabel("PM2.5: -- µg/m³")
        pm25_font = QFont()
        pm25_font.setPointSize(16)
        pm25_font.setBold(True)
        self.pm25_label.setFont(pm25_font)
        self.pm25_label.setAlignment(Qt.AlignCenter)
        aq_layout.addWidget(self.pm25_label)
        
        # Additional pollutants (if available)
        self.other_pollutants_label = QLabel("")
        other_font = QFont()
        other_font.setPointSize(10)
        self.other_pollutants_label.setFont(other_font)
        self.other_pollutants_label.setAlignment(Qt.AlignCenter)
        aq_layout.addWidget(self.other_pollutants_label)
        
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
    
    def update_weather(self, city_name: str, weather_data: dict):
        """
        Update weather display.
        
        Args:
            city_name: Name of the city
            weather_data: Weather data dictionary
        """
        self.city_label.setText(city_name)
        
        if weather_data:
            temp = weather_data.get('temperature')
            humidity = weather_data.get('humidity')
            wind_speed = weather_data.get('wind_speed')
            pm25 = weather_data.get('pm25')
            pm10 = weather_data.get('pm10')
            no2 = weather_data.get('no2')
            o3 = weather_data.get('o3')
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
                details.append(f"Vind: {wind_speed:.1f} m/s")
            self.details_label.setText(" | ".join(details) if details else "")
            
            # PM2.5 (primary display)
            if pm25 is not None:
                self.pm25_label.setText(f"PM2.5: {pm25:.1f} µg/m³")
            else:
                self.pm25_label.setText("PM2.5: Ej tillgängligt")
            
            # Other pollutants
            other_pollutants = []
            if pm10 is not None:
                other_pollutants.append(f"PM10: {pm10:.1f} µg/m³")
            if no2 is not None:
                other_pollutants.append(f"NO₂: {no2:.1f} µg/m³")
            if o3 is not None:
                other_pollutants.append(f"O₃: {o3:.1f} µg/m³")
            
            if other_pollutants:
                self.other_pollutants_label.setText(" | ".join(other_pollutants))
            else:
                self.other_pollutants_label.setText("")
            
            # Update time
            if timestamp:
                if isinstance(timestamp, str):
                    self.update_label.setText(f"Senaste uppdatering: {timestamp}")
                else:
                    self.update_label.setText(f"Senaste uppdatering: {timestamp.strftime('%H:%M:%S')}")
        else:
            self.temp_label.setText("--°C")
            self.details_label.setText("")
            self.pm25_label.setText("PM2.5: --")
            self.aq_group.setStyleSheet("")
            self.other_pollutants_label.setText("")
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
