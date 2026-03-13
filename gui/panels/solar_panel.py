"""Solar panel for displaying solar-related data."""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from typing import Optional
import logging

logger = logging.getLogger("WeatherApp.gui.panels.solar_panel")


class SolarPanel(QWidget):
    """Panel for displaying solar-related data."""
    
    def __init__(self, db):
        """
        Initialize solar panel.
        
        Args:
            db: DatabaseManager instance
        """
        super().__init__()
        self.db = db
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
        
        # Solar Index (large, bold)
        self.solar_index_label = QLabel("--")
        solar_index_font = QFont()
        solar_index_font.setPointSize(48)
        solar_index_font.setBold(True)
        self.solar_index_label.setFont(solar_index_font)
        self.solar_index_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.solar_index_label)
        
        # Solar Index description
        self.solar_index_desc = QLabel("Solar Index")
        desc_font = QFont()
        desc_font.setPointSize(12)
        desc_font.setItalic(True)
        self.solar_index_desc.setFont(desc_font)
        self.solar_index_desc.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.solar_index_desc)
        
        # Details section
        self.details_group = QFrame()
        self.details_group.setFrameShape(QFrame.Box)
        self.details_group.setMinimumHeight(150)
        details_layout = QVBoxLayout(self.details_group)
        details_layout.setSpacing(8)
        
        # Solar Radiation
        self.solar_radiation_label = QLabel("")
        details_font = QFont()
        details_font.setPointSize(12)
        self.solar_radiation_label.setFont(details_font)
        details_layout.addWidget(self.solar_radiation_label)
        
        # UV Index
        self.uv_index_label = QLabel("")
        self.uv_index_label.setFont(details_font)
        details_layout.addWidget(self.uv_index_label)
        
        # Sunshine Duration
        self.sunshine_label = QLabel("")
        self.sunshine_label.setFont(details_font)
        details_layout.addWidget(self.sunshine_label)
        
        # Direct Radiation
        self.direct_radiation_label = QLabel("")
        self.direct_radiation_label.setFont(details_font)
        details_layout.addWidget(self.direct_radiation_label)
        
        # Diffuse Radiation
        self.diffuse_radiation_label = QLabel("")
        self.diffuse_radiation_label.setFont(details_font)
        details_layout.addWidget(self.diffuse_radiation_label)
        
        layout.addWidget(self.details_group)
        
        # Last update
        self.update_label = QLabel("")
        update_font = QFont()
        update_font.setPointSize(10)
        update_font.setItalic(True)
        self.update_label.setFont(update_font)
        self.update_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.update_label)
        
        layout.addStretch()
    
    def _format_value(self, label: str, value: Optional[float], unit: str) -> str:
        """
        Format a value with label and unit.
        
        Args:
            label: Label text
            value: Numeric value (can be None)
            unit: Unit string
            
        Returns:
            Formatted string or empty string if value is None
        """
        if value is not None:
            return f"{label}: {value:.1f} {unit}"
        return f"{label}: Ingen data"
    
    def refresh(self):
        """Refresh solar data display."""
        if not self.current_city_id:
            self.city_label.setText("Välj en stad")
            self.solar_index_label.setText("--")
            self.solar_index_desc.setText("Solar Index")
            self.solar_radiation_label.setText("Solar Radiation: Ingen data")
            self.uv_index_label.setText("UV Index: Ingen data")
            self.sunshine_label.setText("Sunshine Duration: Ingen data")
            self.direct_radiation_label.setText("Direct Radiation: Ingen data")
            self.diffuse_radiation_label.setText("Diffuse Radiation: Ingen data")
            self.update_label.setText("")
            return
        
        try:
            # Get city name
            city = self.db.get_city(self.current_city_id)
            city_name = city['name'] if city else "Okänd stad"
            self.city_label.setText(city_name)
            
            # Get latest weather data
            weather = self.db.get_latest_weather(self.current_city_id)
            
            # Get latest analytical indices (for solar_index)
            indices = self.db.get_latest_analytical_indices(self.current_city_id)
            
            if weather or indices:
                # Solar Index (from analytical_indices)
                solar_index = None
                if indices:
                    solar_index = indices.get('solar_index')
                
                if solar_index is not None:
                    self.solar_index_label.setText(f"{solar_index:.2f}")
                else:
                    self.solar_index_label.setText("--")
                    self.solar_index_desc.setText("Solar Index (ej beräknad)")
                
                # Solar Radiation
                solar_radiation = weather.get('solar_radiation') if weather else None
                self.solar_radiation_label.setText(
                    self._format_value("Solar Radiation", solar_radiation, "W/m²")
                )
                
                # UV Index
                uv_index = weather.get('uv_index') if weather else None
                self.uv_index_label.setText(
                    self._format_value("UV Index", uv_index, "")
                )
                
                # Sunshine Duration
                sunshine_duration = weather.get('sunshine_duration') if weather else None
                self.sunshine_label.setText(
                    self._format_value("Sunshine Duration", sunshine_duration, "h")
                )
                
                # Direct Radiation
                direct_radiation = weather.get('direct_radiation') if weather else None
                self.direct_radiation_label.setText(
                    self._format_value("Direct Radiation", direct_radiation, "W/m²")
                )
                
                # Diffuse Radiation
                diffuse_radiation = weather.get('diffuse_radiation') if weather else None
                self.diffuse_radiation_label.setText(
                    self._format_value("Diffuse Radiation", diffuse_radiation, "W/m²")
                )
                
                # Update timestamp
                timestamp = weather.get('timestamp') if weather else None
                if timestamp:
                    if isinstance(timestamp, str):
                        self.update_label.setText(f"Senaste uppdatering: {timestamp}")
                    else:
                        self.update_label.setText(f"Senaste uppdatering: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    self.update_label.setText("")
            else:
                # No data available
                self.solar_index_label.setText("--")
                self.solar_index_desc.setText("Solar Index")
                self.solar_radiation_label.setText("Solar Radiation: Ingen data")
                self.uv_index_label.setText("UV Index: Ingen data")
                self.sunshine_label.setText("Sunshine Duration: Ingen data")
                self.direct_radiation_label.setText("Direct Radiation: Ingen data")
                self.diffuse_radiation_label.setText("Diffuse Radiation: Ingen data")
                self.update_label.setText("")
        except Exception as e:
            logger.error(f"Error refreshing solar panel: {e}", exc_info=True)
            self.city_label.setText("Fel vid laddning")
            self.solar_index_label.setText("--")
            self.solar_index_desc.setText("Solar Index")
            self.solar_radiation_label.setText("Fel vid laddning av data")
            self.uv_index_label.setText("")
            self.sunshine_label.setText("")
            self.direct_radiation_label.setText("")
            self.diffuse_radiation_label.setText("")
            self.update_label.setText("")
    
    def set_city(self, city_id: int):
        """Set current city."""
        self.current_city_id = city_id
        self.refresh()
