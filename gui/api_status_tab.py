"""API status tab."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QGridLayout
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor, QPalette


class APIStatusTab(QWidget):
    """Tab for displaying API provider status."""
    
    def __init__(self, controller):
        """
        Initialize API status tab.
        
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
        
        # Title
        title = QLabel("API Provider Status")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Status group
        status_group = QGroupBox("Provider Status")
        status_layout = QGridLayout(status_group)
        status_layout.setSpacing(10)
        
        # Headers
        header_font = QFont()
        header_font.setBold(True)
        
        status_layout.addWidget(self._create_label("Provider", header_font), 0, 0)
        status_layout.addWidget(self._create_label("Status", header_font), 0, 1)
        status_layout.addWidget(self._create_label("API Key", header_font), 0, 2)
        
        # Provider rows
        self.openmeteo_status = self._create_status_row("Open-Meteo", status_layout, 1)
        self.openweather_status = self._create_status_row("OpenWeatherMap", status_layout, 2)
        self.openaq_status = self._create_status_row("OpenAQ", status_layout, 3)
        
        layout.addWidget(status_group)
        layout.addStretch()
    
    def _create_label(self, text: str, font: QFont = None) -> QLabel:
        """Create a label."""
        label = QLabel(text)
        if font:
            label.setFont(font)
        return label
    
    def _create_status_row(self, name: str, layout: QGridLayout, row: int):
        """Create a status row for a provider."""
        name_label = QLabel(name)
        status_label = QLabel("--")
        key_label = QLabel("--")
        
        layout.addWidget(name_label, row, 0)
        layout.addWidget(status_label, row, 1)
        layout.addWidget(key_label, row, 2)
        
        return {
            'name': name_label,
            'status': status_label,
            'key': key_label
        }
    
    def refresh(self):
        """Refresh API status."""
        providers = self.controller.get_provider_status()
        
        # Open-Meteo
        openmeteo = providers.get('openmeteo', {})
        self._update_status(self.openmeteo_status, openmeteo.get('available', False), None)
        
        # OpenWeather
        openweather = providers.get('openweather', {})
        has_key = openweather.get('has_key', False)
        self._update_status(
            self.openweather_status,
            openweather.get('available', False),
            "Ja" if has_key else "Nej"
        )
        
        # OpenAQ
        openaq = providers.get('openaq', {})
        has_key = openaq.get('has_key', False)
        self._update_status(
            self.openaq_status,
            openaq.get('available', False),
            "Ja" if has_key else "Nej"
        )
    
    def _update_status(self, status_row: dict, available: bool, key_status: str):
        """Update status for a provider."""
        if available:
            status_row['status'].setText("Tillgänglig")
            status_row['status'].setStyleSheet("color: green; font-weight: bold;")
        else:
            status_row['status'].setText("Ej tillgänglig")
            status_row['status'].setStyleSheet("color: red; font-weight: bold;")
        
        if key_status:
            status_row['key'].setText(key_status)
        else:
            status_row['key'].setText("Ej krävd")
