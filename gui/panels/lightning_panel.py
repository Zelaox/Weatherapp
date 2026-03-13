"""Lightning panel for displaying lightning events."""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QScrollArea
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from typing import Optional, List, Dict
import logging
from datetime import datetime

logger = logging.getLogger("WeatherApp.gui.panels.lightning_panel")


class LightningPanel(QWidget):
    """Panel for displaying lightning events."""
    
    def __init__(self, db):
        """
        Initialize lightning panel.
        
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
        
        # Header
        self.header_label = QLabel("Lightning Events (24h)")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        self.header_label.setFont(header_font)
        layout.addWidget(self.header_label)
        
        # Scroll area for events list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        # Events container
        self.events_container = QWidget()
        self.events_layout = QVBoxLayout(self.events_container)
        self.events_layout.setSpacing(8)
        self.events_layout.setContentsMargins(5, 5, 5, 5)
        self.events_layout.addStretch()
        
        scroll_area.setWidget(self.events_container)
        layout.addWidget(scroll_area, 1)
        
        # Last update
        self.update_label = QLabel("")
        update_font = QFont()
        update_font.setPointSize(10)
        update_font.setItalic(True)
        self.update_label.setFont(update_font)
        self.update_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.update_label)
    
    def _format_timestamp(self, timestamp) -> str:
        """
        Format timestamp for display.
        
        Args:
            timestamp: Timestamp (string or datetime)
            
        Returns:
            Formatted timestamp string
        """
        if timestamp is None:
            return "Okänd tid"
        
        try:
            if isinstance(timestamp, str):
                # Try to parse string timestamp
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                dt = timestamp
            
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logger.debug(f"Error formatting timestamp: {e}")
            return str(timestamp)
    
    def _clear_events(self):
        """Clear all event labels from the layout."""
        while self.events_layout.count() > 1:  # Keep the stretch
            item = self.events_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def _add_event_label(self, event: Dict):
        """
        Add a single event label to the layout.
        
        Args:
            event: Event dictionary with timestamp, intensity, distance_km
        """
        event_frame = QFrame()
        event_frame.setFrameShape(QFrame.Box)
        event_frame.setStyleSheet("QFrame { background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 4px; }")
        event_layout = QVBoxLayout(event_frame)
        event_layout.setSpacing(4)
        event_layout.setContentsMargins(8, 8, 8, 8)
        
        # Timestamp with lightning emoji
        timestamp_str = self._format_timestamp(event.get('timestamp'))
        timestamp_label = QLabel(f"⚡ {timestamp_str}")
        timestamp_font = QFont()
        timestamp_font.setPointSize(11)
        timestamp_font.setBold(True)
        timestamp_label.setFont(timestamp_font)
        event_layout.addWidget(timestamp_label)
        
        # Intensity
        intensity = event.get('intensity')
        if intensity is not None:
            intensity_label = QLabel(f"Intensity: {intensity:.1f}")
            intensity_font = QFont()
            intensity_font.setPointSize(10)
            intensity_label.setFont(intensity_font)
            event_layout.addWidget(intensity_label)
        
        # Distance
        distance = event.get('distance_km')
        if distance is not None:
            distance_label = QLabel(f"Distance: {distance:.1f} km")
            distance_font = QFont()
            distance_font.setPointSize(10)
            distance_label.setFont(distance_font)
            event_layout.addWidget(distance_label)
        
        self.events_layout.insertWidget(self.events_layout.count() - 1, event_frame)
    
    def refresh(self):
        """Refresh lightning events display."""
        # Clear existing events
        self._clear_events()
        
        if not self.current_city_id:
            self.city_label.setText("Välj en stad")
            self.header_label.setText("Lightning Events (24h)")
            no_events_label = QLabel("Välj en stad för att visa blixtar")
            no_events_label.setAlignment(Qt.AlignCenter)
            no_events_font = QFont()
            no_events_font.setPointSize(12)
            no_events_font.setItalic(True)
            no_events_label.setFont(no_events_font)
            self.events_layout.insertWidget(0, no_events_label)
            self.update_label.setText("")
            return
        
        try:
            # Get city name
            city = self.db.get_city(self.current_city_id)
            city_name = city['name'] if city else "Okänd stad"
            self.city_label.setText(city_name)
            
            # Get lightning display hours from calibration
            display_hours = self.db.get_calibration_parameter('lightning_display_hours')
            if display_hours is None:
                display_hours = 24
            else:
                display_hours = int(float(display_hours))
            
            self.header_label.setText(f"Lightning Events ({display_hours}h)")
            
            # Get lightning events for this city
            events = self.db.get_lightning_events(city_id=self.current_city_id, hours=display_hours)
            
            if events:
                # Sort by timestamp (newest first)
                events.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
                
                # Add event labels
                for event in events:
                    self._add_event_label(event)
                
                # Update timestamp
                if events:
                    latest_timestamp = events[0].get('timestamp')
                    if latest_timestamp:
                        self.update_label.setText(f"Senaste event: {self._format_timestamp(latest_timestamp)}")
                    else:
                        self.update_label.setText(f"Totalt {len(events)} event(s)")
                else:
                    self.update_label.setText("")
            else:
                # No events
                no_events_label = QLabel("Inga blixtar de senaste 24 timmarna")
                no_events_label.setAlignment(Qt.AlignCenter)
                no_events_font = QFont()
                no_events_font.setPointSize(12)
                no_events_font.setItalic(True)
                no_events_label.setFont(no_events_font)
                self.events_layout.insertWidget(0, no_events_label)
                self.update_label.setText("")
        except Exception as e:
            logger.error(f"Error refreshing lightning panel: {e}", exc_info=True)
            self.city_label.setText("Fel vid laddning")
            error_label = QLabel(f"Fel vid laddning av data: {e}")
            error_label.setAlignment(Qt.AlignCenter)
            error_font = QFont()
            error_font.setPointSize(12)
            error_font.setItalic(True)
            error_label.setFont(error_font)
            self.events_layout.insertWidget(0, error_label)
            self.update_label.setText("")
    
    def set_city(self, city_id: int):
        """Set current city."""
        self.current_city_id = city_id
        self.refresh()
