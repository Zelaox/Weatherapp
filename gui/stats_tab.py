"""Statistics tab."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGroupBox,
    QGridLayout
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class StatsTab(QWidget):
    """Tab for displaying statistics and rankings."""
    
    def __init__(self, controller):
        """
        Initialize stats tab.
        
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
        self.timeframe_combo.addItems(["1h", "24h", "Idag", "Vecka"])
        self.timeframe_combo.currentIndexChanged.connect(self.refresh)
        selector_layout.addWidget(self.timeframe_combo)
        selector_layout.addStretch()
        layout.addLayout(selector_layout)
        
        # Rankings
        rankings_group = QGroupBox("Ranking")
        rankings_layout = QGridLayout(rankings_group)
        rankings_layout.setSpacing(10)
        
        # Headers
        header_font = QFont()
        header_font.setBold(True)
        
        rankings_layout.addWidget(self._create_label("Kategori", header_font), 0, 0)
        rankings_layout.addWidget(self._create_label("Stad", header_font), 0, 1)
        rankings_layout.addWidget(self._create_label("Värde", header_font), 0, 2)
        
        # Ranking rows
        self.coldest_label = self._create_label("Kallast:", bold=True)
        self.coldest_city_label = QLabel("--")
        self.coldest_value_label = QLabel("--")
        rankings_layout.addWidget(self.coldest_label, 1, 0)
        rankings_layout.addWidget(self.coldest_city_label, 1, 1)
        rankings_layout.addWidget(self.coldest_value_label, 1, 2)
        
        self.warmest_label = self._create_label("Varmast:", bold=True)
        self.warmest_city_label = QLabel("--")
        self.warmest_value_label = QLabel("--")
        rankings_layout.addWidget(self.warmest_label, 2, 0)
        rankings_layout.addWidget(self.warmest_city_label, 2, 1)
        rankings_layout.addWidget(self.warmest_value_label, 2, 2)
        
        self.best_air_label = self._create_label("Bäst luft:", bold=True)
        self.best_air_city_label = QLabel("--")
        self.best_air_value_label = QLabel("--")
        rankings_layout.addWidget(self.best_air_label, 3, 0)
        rankings_layout.addWidget(self.best_air_city_label, 3, 1)
        rankings_layout.addWidget(self.best_air_value_label, 3, 2)
        
        self.worst_air_label = self._create_label("Sämst luft:", bold=True)
        self.worst_air_city_label = QLabel("--")
        self.worst_air_value_label = QLabel("--")
        rankings_layout.addWidget(self.worst_air_label, 4, 0)
        rankings_layout.addWidget(self.worst_air_city_label, 4, 1)
        rankings_layout.addWidget(self.worst_air_value_label, 4, 2)
        
        layout.addWidget(rankings_group)
        layout.addStretch()
    
    def _create_label(self, text: str, bold: bool = False, font: QFont = None) -> QLabel:
        """Create a label with optional formatting."""
        label = QLabel(text)
        if font:
            label.setFont(font)
        elif bold:
            font = QFont()
            font.setBold(True)
            label.setFont(font)
        return label
    
    def refresh(self):
        """Refresh statistics."""
        timeframe_map = {"1h": "1h", "24h": "24h", "Idag": "today", "Vecka": "week"}
        timeframe = timeframe_map.get(self.timeframe_combo.currentText(), "24h")
        
        rankings = self.controller.get_rankings(timeframe)
        
        # Coldest
        if rankings.get('coldest'):
            coldest = rankings['coldest']
            self.coldest_city_label.setText(coldest['city_name'])
            self.coldest_value_label.setText(f"{coldest['temperature']:.1f}°C")
        else:
            self.coldest_city_label.setText("--")
            self.coldest_value_label.setText("--")
        
        # Warmest
        if rankings.get('warmest'):
            warmest = rankings['warmest']
            self.warmest_city_label.setText(warmest['city_name'])
            self.warmest_value_label.setText(f"{warmest['temperature']:.1f}°C")
        else:
            self.warmest_city_label.setText("--")
            self.warmest_value_label.setText("--")
        
        # Best air (PM2.5)
        if rankings.get('best_air'):
            best_air = rankings['best_air']
            self.best_air_city_label.setText(best_air['city_name'])
            # Show PM2.5 value (24h rolling average)
            pm25 = best_air.get('pm25')
            if pm25 is not None:
                self.best_air_value_label.setText(f"{pm25:.1f} µg/m³")
            else:
                self.best_air_value_label.setText("--")
        else:
            self.best_air_city_label.setText("--")
            self.best_air_value_label.setText("--")
        
        # Worst air (PM2.5)
        if rankings.get('worst_air'):
            worst_air = rankings['worst_air']
            self.worst_air_city_label.setText(worst_air['city_name'])
            # Show PM2.5 value (24h rolling average)
            pm25 = worst_air.get('pm25')
            if pm25 is not None:
                self.worst_air_value_label.setText(f"{pm25:.1f} µg/m³")
            else:
                self.worst_air_value_label.setText("--")
        else:
            self.worst_air_city_label.setText("--")
            self.worst_air_value_label.setText("--")
