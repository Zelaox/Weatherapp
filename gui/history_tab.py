"""History tab with graphs."""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QTextEdit
from PyQt5.QtCore import Qt
from datetime import datetime


class HistoryTab(QWidget):
    """Tab for displaying weather history graphs."""
    
    def __init__(self, controller):
        """
        Initialize history tab.
        
        Args:
            controller: Weather controller instance
        """
        super().__init__()
        self.controller = controller
        self._refreshing = False  # Guard to prevent recursion
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # City selector
        selector_layout = QVBoxLayout()
        selector_layout.addWidget(QLabel("Välj stad:"))
        self.city_combo = QComboBox()
        self.city_combo.currentIndexChanged.connect(self._on_city_changed)
        selector_layout.addWidget(self.city_combo)
        layout.addLayout(selector_layout)
        
        # Initialize attributes - always use text fallback to avoid crashes
        self.temp_plot = None
        self.aqi_plot = None
        self.temp_curve = None
        self.aqi_curve = None
        
        # Always use text fallback to avoid pyqtgraph crashes on Windows
        # Text display fallback
        info_label = QLabel("Grafer kräver pyqtgraph. Installera med: pip install pyqtgraph\n(Notera: pyqtgraph kan orsaka krascher på vissa Windows-system)")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: orange; padding: 20px;")
        layout.addWidget(info_label)
        
        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)
        self.history_text.setFontFamily("Courier")
        layout.addWidget(self.history_text)
    
    def _on_city_changed(self):
        """Handle city selection change."""
        # Prevent recursion by blocking signals during refresh
        if not self._refreshing:
            self.refresh()
    
    def refresh(self):
        """Refresh graphs with error handling."""
        # Guard against recursion
        if self._refreshing:
            return
        
        self._refreshing = True
        try:
            # Get cities with error handling
            try:
                cities = self.controller.get_all_cities()
            except RecursionError:
                if hasattr(self, 'history_text'):
                    self.history_text.setText("Fel: Rekursion i databasåtkomst. Försök igen.")
                return
            except Exception as e:
                if hasattr(self, 'history_text'):
                    self.history_text.setText(f"Fel vid hämtning av städer: {e}")
                return
            
            # Update combo box
            current_text = self.city_combo.currentText()
            self.city_combo.blockSignals(True)  # Prevent recursion
            self.city_combo.clear()
            for city in cities:
                self.city_combo.addItem(city['name'], city['id'])
            
            # Restore selection
            index = self.city_combo.findText(current_text)
            if index >= 0:
                self.city_combo.setCurrentIndex(index)
            elif cities:
                self.city_combo.setCurrentIndex(0)
            self.city_combo.blockSignals(False)
            
            # Update graphs
            if self.city_combo.count() > 0:
                city_id = self.city_combo.currentData()
                if city_id:
                    self._update_graphs(city_id)
        except Exception as e:
            # Catch any unexpected errors
            if hasattr(self, 'history_text'):
                self.history_text.setText(f"Fel vid uppdatering: {e}")
        finally:
            self._refreshing = False
    
    def _update_graphs(self, city_id: int):
        """Update graphs for a city with error handling."""
        try:
            trend_data = self.controller.get_city_trend(city_id, hours=24)
        except RecursionError:
            if hasattr(self, 'history_text'):
                self.history_text.setText("Fel: Rekursion i databasåtkomst. Försök igen.")
            return
        except Exception as e:
            if hasattr(self, 'history_text'):
                self.history_text.setText(f"Fel vid hämtning av historik: {e}")
            return
        
        if not trend_data:
            if hasattr(self, 'history_text'):
                self.history_text.setText("Ingen historik tillgänglig")
            return
        
        # Text fallback display
        if hasattr(self, 'history_text'):
            lines = ["Historik (senaste 24 timmarna):\n"]
            for point in trend_data[-20:]:  # Last 20 points
                try:
                    ts = point.get('timestamp', 'N/A')
                    temp = point.get('temperature', 'N/A')
                    aqi = point.get('aqi', 'N/A')
                    if isinstance(ts, str):
                        ts_display = ts
                    else:
                        ts_display = ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ts, 'strftime') else str(ts)
                    lines.append(f"{ts_display}: Temp={temp}°C, AQI={aqi}")
                except Exception:
                    pass
            self.history_text.setText("\n".join(lines))
