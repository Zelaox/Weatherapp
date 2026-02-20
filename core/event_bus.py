"""Event bus for sensor updates."""

from PyQt5.QtCore import QObject, pyqtSignal
from typing import Dict, Any


class EventBus(QObject):
    """Event bus for sensor updates."""
    
    sensor_updated = pyqtSignal(int)  # sensor_id
    sensor_error = pyqtSignal(int, str)  # sensor_id, error_message
    sensor_enabled = pyqtSignal(int)  # sensor_id
    sensor_disabled = pyqtSignal(int)  # sensor_id
    
    def __init__(self, parent=None):
        """Initialize event bus."""
        super().__init__(parent)
    
    def emit(self, event_type: str, **kwargs):
        """
        Emit event.
        
        Args:
            event_type: Event type ('sensor_updated', 'sensor_error', etc.)
            **kwargs: Event data
        """
        if event_type == 'sensor_updated':
            if 'sensor_id' in kwargs:
                self.sensor_updated.emit(kwargs['sensor_id'])
        elif event_type == 'sensor_error':
            if 'sensor_id' in kwargs and 'error' in kwargs:
                self.sensor_error.emit(kwargs['sensor_id'], kwargs['error'])
        elif event_type == 'sensor_enabled':
            if 'sensor_id' in kwargs:
                self.sensor_enabled.emit(kwargs['sensor_id'])
        elif event_type == 'sensor_disabled':
            if 'sensor_id' in kwargs:
                self.sensor_disabled.emit(kwargs['sensor_id'])
