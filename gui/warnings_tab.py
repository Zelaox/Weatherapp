"""Warnings tab for displaying dangerous PM2.5 levels."""

from typing import List, Dict
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor


class WarningsTab(QWidget):
    """Tab for displaying PM2.5 warnings and dangerous levels."""
    
    def __init__(self, controller):
        """
        Initialize warnings tab.
        
        Args:
            controller: Weather controller instance
        """
        super().__init__()
        self.controller = controller
        self._init_ui()
        self.refresh()
    
    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # National Overview Section
        national_group = QGroupBox("Nationell översikt")
        national_layout = QGridLayout(national_group)
        national_layout.setSpacing(10)
        national_layout.setContentsMargins(15, 15, 15, 15)
        
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(11)
        
        label_font = QFont()
        label_font.setPointSize(10)
        
        value_font = QFont()
        value_font.setBold(True)
        value_font.setPointSize(11)
        
        # National PM2.5
        self.national_pm25_label = QLabel("Nationellt snitt PM2.5:")
        self.national_pm25_label.setFont(label_font)
        self.national_pm25_value = QLabel("--")
        self.national_pm25_value.setFont(value_font)
        national_layout.addWidget(self.national_pm25_label, 0, 0)
        national_layout.addWidget(self.national_pm25_value, 0, 1)
        
        # National AQI
        self.national_aqi_label = QLabel("Nationell AQI:")
        self.national_aqi_label.setFont(label_font)
        self.national_aqi_value = QLabel("--")
        self.national_aqi_value.setFont(value_font)
        national_layout.addWidget(self.national_aqi_label, 1, 0)
        national_layout.addWidget(self.national_aqi_value, 1, 1)
        
        # Warning Status
        self.warning_status_label = QLabel("Varningsnivå:")
        self.warning_status_label.setFont(label_font)
        self.warning_status_value = QLabel("--")
        self.warning_status_value.setFont(value_font)
        national_layout.addWidget(self.warning_status_label, 2, 0)
        national_layout.addWidget(self.warning_status_value, 2, 1)
        
        # Warning Statistics
        self.stats_label = QLabel("Städer över tröskel:")
        self.stats_label.setFont(label_font)
        self.stats_value = QLabel("--")
        self.stats_value.setFont(value_font)
        national_layout.addWidget(self.stats_label, 3, 0)
        national_layout.addWidget(self.stats_value, 3, 1)
        
        layout.addWidget(national_group)
        
        # Regional Warnings Section
        regional_group = QGroupBox("Regionala varningar")
        regional_layout = QVBoxLayout(regional_group)
        
        # Table for cities with dangerous levels
        self.warnings_table = QTableWidget()
        self.warnings_table.setColumnCount(5)
        self.warnings_table.setHorizontalHeaderLabels([
            "Stad", "PM2.5 (µg/m³)", "AQI", "Nivå", "Status"
        ])
        self.warnings_table.horizontalHeader().setStretchLastSection(True)
        self.warnings_table.setAlternatingRowColors(True)
        self.warnings_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.warnings_table.setEditTriggers(QTableWidget.NoEditTriggers)
        regional_layout.addWidget(self.warnings_table)
        
        layout.addWidget(regional_group)
        
        # Top Cities Section
        top_group = QGroupBox("Top 10 städer med högst PM2.5")
        top_layout = QVBoxLayout(top_group)
        
        self.top_table = QTableWidget()
        self.top_table.setColumnCount(5)
        self.top_table.setHorizontalHeaderLabels([
            "Rank", "Stad", "PM2.5 (µg/m³)", "AQI", "Status"
        ])
        self.top_table.horizontalHeader().setStretchLastSection(True)
        self.top_table.setAlternatingRowColors(True)
        self.top_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.top_table.setEditTriggers(QTableWidget.NoEditTriggers)
        top_layout.addWidget(self.top_table)
        
        layout.addWidget(top_group)
        
        layout.addStretch()
    
    def refresh(self):
        """Refresh warnings display."""
        try:
            # Get national warning status
            national_warning = self.controller.get_national_warning_status()
            
            # Update national overview
            if national_warning.get('pm25') is not None:
                self.national_pm25_value.setText(f"{national_warning['pm25']:.1f} µg/m³")
                self.national_aqi_value.setText(f"{national_warning['aqi']:.0f}")
                self.warning_status_value.setText(national_warning['name'])
                # Set color
                color = national_warning.get('color', '#cccccc')
                self.warning_status_value.setStyleSheet(f"color: {color}; font-weight: bold;")
            else:
                self.national_pm25_value.setText("Ingen data")
                self.national_aqi_value.setText("Ingen data")
                self.warning_status_value.setText("Ingen data")
                self.warning_status_value.setStyleSheet("")
            
            # Get warning statistics
            stats = self.controller.get_warning_statistics()
            if stats:
                # Count cities over "moderate" threshold
                over_moderate = (
                    stats.get('unhealthy_sensitive', 0) +
                    stats.get('unhealthy', 0) +
                    stats.get('very_unhealthy', 0) +
                    stats.get('hazardous', 0)
                )
                total = stats.get('total', 0)
                self.stats_value.setText(f"{over_moderate} av {total} städer")
            else:
                self.stats_value.setText("--")
            
            # Get regional warnings
            regional_warnings = self.controller.get_regional_warnings()
            self._populate_warnings_table(regional_warnings)
            
            # Get top cities
            top_cities = self.controller.get_max_pm25_cities(limit=10)
            self._populate_top_table(top_cities)
            
        except Exception as e:
            # On error, show empty tables
            self.warnings_table.setRowCount(0)
            self.top_table.setRowCount(0)
            self.controller.logger.error(f"Fel vid uppdatering av varningar: {e}")
    
    def _populate_warnings_table(self, warnings: List[Dict]):
        """Populate warnings table with city data."""
        self.warnings_table.setRowCount(len(warnings))
        
        for row, warning in enumerate(warnings):
            # City name
            city_item = QTableWidgetItem(warning.get('city_name', '--'))
            self.warnings_table.setItem(row, 0, city_item)
            
            # PM2.5
            pm25_item = QTableWidgetItem(f"{warning.get('pm25', 0):.1f}")
            pm25_item.setTextAlignment(Qt.AlignCenter)
            self.warnings_table.setItem(row, 1, pm25_item)
            
            # AQI
            aqi_item = QTableWidgetItem(f"{warning.get('aqi', 0):.0f}")
            aqi_item.setTextAlignment(Qt.AlignCenter)
            self.warnings_table.setItem(row, 2, aqi_item)
            
            # Level
            level_item = QTableWidgetItem(warning.get('level_name', '--'))
            level_item.setTextAlignment(Qt.AlignCenter)
            self.warnings_table.setItem(row, 3, level_item)
            
            # Status (color indicator)
            status_item = QTableWidgetItem("⚠️")
            status_item.setTextAlignment(Qt.AlignCenter)
            color = warning.get('color', '#cccccc')
            status_item.setForeground(QColor(color))
            self.warnings_table.setItem(row, 4, status_item)
            
            # Set row background color based on severity
            if warning.get('level') in ['very_unhealthy', 'hazardous']:
                self.warnings_table.item(row, 0).setBackground(QColor(255, 240, 240))
        
        # Resize columns to content
        self.warnings_table.resizeColumnsToContents()
    
    def _populate_top_table(self, cities: List[Dict]):
        """Populate top cities table."""
        self.top_table.setRowCount(len(cities))
        
        for row, city in enumerate(cities):
            # Rank
            rank_item = QTableWidgetItem(str(row + 1))
            rank_item.setTextAlignment(Qt.AlignCenter)
            self.top_table.setItem(row, 0, rank_item)
            
            # City name
            city_item = QTableWidgetItem(city.get('city_name', '--'))
            self.top_table.setItem(row, 1, city_item)
            
            # PM2.5
            pm25_item = QTableWidgetItem(f"{city.get('pm25', 0):.1f}")
            pm25_item.setTextAlignment(Qt.AlignCenter)
            self.top_table.setItem(row, 2, pm25_item)
            
            # AQI
            aqi_item = QTableWidgetItem(f"{city.get('aqi', 0):.0f}")
            aqi_item.setTextAlignment(Qt.AlignCenter)
            self.top_table.setItem(row, 3, aqi_item)
            
            # Status
            status_item = QTableWidgetItem(city.get('level_name', '--'))
            status_item.setTextAlignment(Qt.AlignCenter)
            color = city.get('color', '#cccccc')
            status_item.setForeground(QColor(color))
            self.top_table.setItem(row, 4, status_item)
            
            # Set row background color based on severity
            if city.get('level') in ['very_unhealthy', 'hazardous']:
                self.top_table.item(row, 1).setBackground(QColor(255, 240, 240))
        
        # Resize columns to content
        self.top_table.resizeColumnsToContents()
