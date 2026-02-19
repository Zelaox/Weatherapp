"""Averages tab showing average values across all cities."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGroupBox,
    QGridLayout
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from datetime import datetime


class AveragesTab(QWidget):
    """Tab for displaying average values across all cities."""
    
    def __init__(self, controller):
        """
        Initialize averages tab.
        
        Args:
            controller: Weather controller instance
        """
        super().__init__()
        self.controller = controller
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Timeframe selector
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("Tidsperiod:"))
        self.timeframe_combo = QComboBox()
        self.timeframe_combo.addItems(["Senaste värden", "24h snitt"])
        self.timeframe_combo.currentIndexChanged.connect(self.refresh)
        selector_layout.addWidget(self.timeframe_combo)
        selector_layout.addStretch()
        layout.addLayout(selector_layout)
        
        # Averages group
        averages_group = QGroupBox("Genomsnitt över alla städer")
        averages_layout = QGridLayout(averages_group)
        averages_layout.setSpacing(15)
        averages_layout.setContentsMargins(15, 15, 15, 15)
        
        # Headers
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(11)
        
        # Labels and values
        label_font = QFont()
        label_font.setPointSize(10)
        
        value_font = QFont()
        value_font.setBold(True)
        value_font.setPointSize(11)
        
        # Temperature
        temp_label = QLabel("Snitt temperatur:")
        temp_label.setFont(label_font)
        self.temp_value = QLabel("--")
        self.temp_value.setFont(value_font)
        averages_layout.addWidget(temp_label, 0, 0)
        averages_layout.addWidget(self.temp_value, 0, 1)
        
        # Humidity
        humidity_label = QLabel("Snitt fuktighet:")
        humidity_label.setFont(label_font)
        self.humidity_value = QLabel("--")
        self.humidity_value.setFont(value_font)
        averages_layout.addWidget(humidity_label, 1, 0)
        averages_layout.addWidget(self.humidity_value, 1, 1)
        
        # Wind speed
        wind_label = QLabel("Snitt vindhastighet:")
        wind_label.setFont(label_font)
        self.wind_value = QLabel("--")
        self.wind_value.setFont(value_font)
        averages_layout.addWidget(wind_label, 2, 0)
        averages_layout.addWidget(self.wind_value, 2, 1)
        
        # PM2.5
        pm25_label = QLabel("Snitt PM2.5:")
        pm25_label.setFont(label_font)
        self.pm25_value = QLabel("--")
        self.pm25_value.setFont(value_font)
        averages_layout.addWidget(pm25_label, 3, 0)
        averages_layout.addWidget(self.pm25_value, 3, 1)
        
        # AQI (calculated from PM2.5)
        aqi_label = QLabel("Snitt AQI (från PM2.5):")
        aqi_label.setFont(label_font)
        self.aqi_value = QLabel("--")
        self.aqi_value.setFont(value_font)
        averages_layout.addWidget(aqi_label, 4, 0)
        averages_layout.addWidget(self.aqi_value, 4, 1)
        
        layout.addWidget(averages_group)
        
        # Metadata group
        metadata_group = QGroupBox("Information")
        metadata_layout = QGridLayout(metadata_group)
        metadata_layout.setSpacing(10)
        metadata_layout.setContentsMargins(15, 15, 15, 15)
        
        # City count
        city_count_label = QLabel("Antal städer:")
        city_count_label.setFont(label_font)
        self.city_count_value = QLabel("--")
        self.city_count_value.setFont(value_font)
        metadata_layout.addWidget(city_count_label, 0, 0)
        metadata_layout.addWidget(self.city_count_value, 0, 1)
        
        # Data points
        data_points_label = QLabel("Datapunkter:")
        data_points_label.setFont(label_font)
        self.data_points_value = QLabel("--")
        self.data_points_value.setFont(value_font)
        metadata_layout.addWidget(data_points_label, 1, 0)
        metadata_layout.addWidget(self.data_points_value, 1, 1)
        
        # Last update
        last_update_label = QLabel("Senaste uppdatering:")
        last_update_label.setFont(label_font)
        self.last_update_value = QLabel("--")
        self.last_update_value.setFont(value_font)
        metadata_layout.addWidget(last_update_label, 2, 0)
        metadata_layout.addWidget(self.last_update_value, 2, 1)
        
        layout.addWidget(metadata_group)
        layout.addStretch()
    
    def refresh(self):
        """Refresh averages display."""
        try:
            # Get timeframe
            timeframe_map = {"Senaste värden": "latest", "24h snitt": "24h"}
            timeframe = timeframe_map.get(self.timeframe_combo.currentText(), "latest")
            
            # Get averages
            averages = self.controller.get_all_cities_averages(timeframe)
            
            # Update temperature
            if averages.get('avg_temperature') is not None:
                self.temp_value.setText(f"{averages['avg_temperature']:.1f}°C")
            else:
                self.temp_value.setText("Ingen data")
            
            # Update humidity
            if averages.get('avg_humidity') is not None:
                self.humidity_value.setText(f"{averages['avg_humidity']:.1f}%")
            else:
                self.humidity_value.setText("Ingen data")
            
            # Update wind speed
            if averages.get('avg_wind_speed') is not None:
                self.wind_value.setText(f"{averages['avg_wind_speed']:.1f} m/s")
            else:
                self.wind_value.setText("Ingen data")
            
            # Update PM2.5
            if averages.get('avg_pm25') is not None:
                self.pm25_value.setText(f"{averages['avg_pm25']:.1f} µg/m³")
            else:
                self.pm25_value.setText("Ingen data")
            
            # Update AQI (calculated from PM2.5)
            if averages.get('avg_aqi') is not None:
                self.aqi_value.setText(f"{averages['avg_aqi']:.0f}")
            else:
                self.aqi_value.setText("Ingen data")
            
            # Update metadata
            city_count = averages.get('city_count', 0)  # Total cities in database
            self.city_count_value.setText(str(city_count))
            
            # Handle data_points: None (error), 0 (empty table), or int (count)
            data_points = averages.get('data_points')
            if data_points is None:
                # Error state: database query failed
                self.data_points_value.setText("--")
            elif data_points == 0:
                # Empty table: table exists but has no data
                self.data_points_value.setText("0")
            else:
                # Valid count: display the number
                self.data_points_value.setText(str(data_points))
            
            # Update last update time
            last_update = averages.get('last_update')
            if last_update:
                try:
                    if isinstance(last_update, str):
                        # Parse string timestamp
                        dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                    else:
                        dt = last_update
                    self.last_update_value.setText(dt.strftime('%H:%M:%S'))
                except Exception:
                    self.last_update_value.setText("--")
            else:
                self.last_update_value.setText("--")
                
        except Exception as e:
            # On error, show "Ingen data" for all values
            self.temp_value.setText("Ingen data")
            self.humidity_value.setText("Ingen data")
            self.wind_value.setText("Ingen data")
            self.pm25_value.setText("Ingen data")
            self.aqi_value.setText("Ingen data")
            self.city_count_value.setText("0")
            self.data_points_value.setText("--")  # Error state, not empty table
            self.last_update_value.setText("--")
