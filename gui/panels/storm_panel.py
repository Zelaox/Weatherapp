"""Storm panel for displaying storm-related data."""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from typing import Optional
import logging

logger = logging.getLogger("WeatherApp.gui.panels.storm_panel")


class StormPanel(QWidget):
    """Panel for displaying storm-related data."""
    
    def __init__(self, db):
        """
        Initialize storm panel.
        
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
        
        # Storm Risk (large, bold)
        self.storm_risk_label = QLabel("--")
        storm_risk_font = QFont()
        storm_risk_font.setPointSize(48)
        storm_risk_font.setBold(True)
        self.storm_risk_label.setFont(storm_risk_font)
        self.storm_risk_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.storm_risk_label)
        
        # Storm Risk description
        self.storm_risk_desc = QLabel("Storm Risk")
        desc_font = QFont()
        desc_font.setPointSize(12)
        desc_font.setItalic(True)
        self.storm_risk_desc.setFont(desc_font)
        self.storm_risk_desc.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.storm_risk_desc)
        
        # Details section
        self.details_group = QFrame()
        self.details_group.setFrameShape(QFrame.Box)
        self.details_group.setMinimumHeight(150)
        details_layout = QVBoxLayout(self.details_group)
        details_layout.setSpacing(8)
        
        # CAPE
        self.cape_label = QLabel("")
        details_font = QFont()
        details_font.setPointSize(12)
        self.cape_label.setFont(details_font)
        details_layout.addWidget(self.cape_label)
        
        # Convective Precipitation
        self.convective_precip_label = QLabel("")
        self.convective_precip_label.setFont(details_font)
        details_layout.addWidget(self.convective_precip_label)
        
        # Precipitation Probability
        self.precip_prob_label = QLabel("")
        self.precip_prob_label.setFont(details_font)
        details_layout.addWidget(self.precip_prob_label)
        
        # Humidity
        self.humidity_label = QLabel("")
        self.humidity_label.setFont(details_font)
        details_layout.addWidget(self.humidity_label)
        
        # Wind Speed
        self.wind_speed_label = QLabel("")
        self.wind_speed_label.setFont(details_font)
        details_layout.addWidget(self.wind_speed_label)
        
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
            Formatted string
        """
        if value is not None:
            return f"{label}: {value:.1f} {unit}"
        return f"{label}: Ingen data"
    
    def refresh(self):
        """Refresh storm data display."""
        if not self.current_city_id:
            self.city_label.setText("Välj en stad")
            self.storm_risk_label.setText("--")
            self.storm_risk_desc.setText("Storm Risk")
            self.cape_label.setText("CAPE: Ingen data")
            self.convective_precip_label.setText("Convective Precipitation: Ingen data")
            self.precip_prob_label.setText("Precipitation Probability: Ingen data")
            self.humidity_label.setText("Humidity: Ingen data")
            self.wind_speed_label.setText("Wind Speed: Ingen data")
            self.update_label.setText("")
            return
        
        try:
            # Get city name
            city = self.db.get_city(self.current_city_id)
            city_name = city['name'] if city else "Okänd stad"
            self.city_label.setText(city_name)
            
            # Get latest weather data
            weather = self.db.get_latest_weather(self.current_city_id)
            
            # Get latest analytical indices (for storm_risk)
            indices = self.db.get_latest_analytical_indices(self.current_city_id)
            
            if weather or indices:
                # Storm Risk (from analytical_indices)
                storm_risk = None
                if indices:
                    storm_risk = indices.get('storm_risk')
                
                if storm_risk is not None:
                    self.storm_risk_label.setText(f"{storm_risk:.2f}")
                else:
                    self.storm_risk_label.setText("--")
                    self.storm_risk_desc.setText("Storm Risk (ej beräknad)")
                
                # CAPE (Convective Available Potential Energy)
                cape = weather.get('cape') if weather else None
                if cape is not None:
                    cape_category = self.db.get_cape_display_suffix_sv(cape)
                    self.cape_label.setText(f"CAPE: {cape:.1f} J/kg{cape_category}")
                else:
                    self.cape_label.setText("CAPE: Ingen data")
                
                # Convective Precipitation
                convective_precip = weather.get('convective_precipitation') if weather else None
                self.convective_precip_label.setText(
                    self._format_value("Convective Precipitation", convective_precip, "mm")
                )
                
                # Precipitation Probability
                precip_prob = weather.get('precipitation_probability') if weather else None
                if precip_prob is not None:
                    self.precip_prob_label.setText(f"Precipitation Probability: {precip_prob:.0f}%")
                else:
                    self.precip_prob_label.setText("Precipitation Probability: Ingen data")
                
                # Humidity
                humidity = weather.get('humidity') if weather else None
                if humidity is not None:
                    self.humidity_label.setText(f"Humidity: {humidity:.0f}%")
                else:
                    self.humidity_label.setText("Humidity: Ingen data")
                
                # Wind Speed
                wind_speed = weather.get('wind_speed') if weather else None
                self.wind_speed_label.setText(
                    self._format_value("Wind Speed", wind_speed, "m/s")
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
                self.storm_risk_label.setText("--")
                self.storm_risk_desc.setText("Storm Risk")
                self.cape_label.setText("CAPE: Ingen data")
                self.convective_precip_label.setText("Convective Precipitation: Ingen data")
                self.precip_prob_label.setText("Precipitation Probability: Ingen data")
                self.humidity_label.setText("Humidity: Ingen data")
                self.wind_speed_label.setText("Wind Speed: Ingen data")
                self.update_label.setText("")
        except Exception as e:
            logger.error(f"Error refreshing storm panel: {e}", exc_info=True)
            self.city_label.setText("Fel vid laddning")
            self.storm_risk_label.setText("--")
            self.storm_risk_desc.setText("Storm Risk")
            self.cape_label.setText("Fel vid laddning av data")
            self.convective_precip_label.setText("")
            self.precip_prob_label.setText("")
            self.humidity_label.setText("")
            self.wind_speed_label.setText("")
            self.update_label.setText("")
    
    def set_city(self, city_id: int):
        """Set current city."""
        self.current_city_id = city_id
        self.refresh()
