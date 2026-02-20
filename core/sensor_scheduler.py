"""Per-sensor scheduler with async queue to prevent overlapping calls."""

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from typing import Dict, Set
from core.sensor_registry import SensorRegistry
from core.provider_registry import ProviderRegistry
import logging

logger = logging.getLogger("WeatherApp.core.sensor_scheduler")


class SensorScheduler(QObject):
    """Per-sensor scheduler - each sensor has its own interval."""
    
    sensor_update_due = pyqtSignal(int)  # sensor_id
    
    def __init__(self, sensor_registry: SensorRegistry, provider_registry: ProviderRegistry, parent=None):
        """
        Initialize sensor scheduler.
        
        Args:
            sensor_registry: Sensor registry
            provider_registry: Provider registry
            parent: Parent QObject
        """
        super().__init__(parent)
        self.sensor_registry = sensor_registry
        self.provider_registry = provider_registry
        self.timers: Dict[int, QTimer] = {}  # sensor_id -> QTimer
        self.processing: Set[int] = set()  # Track sensors currently being processed
    
    def start(self):
        """Start scheduling all active sensors."""
        sensors = self.sensor_registry.get_active_sensors()
        logger.info(f"Starting scheduler for {len(sensors)} active sensors")
        for sensor in sensors:
            self._schedule_sensor(sensor)
    
    def stop(self):
        """Stop all sensor timers."""
        for timer in self.timers.values():
            timer.stop()
        self.timers.clear()
        self.processing.clear()
        logger.info("Sensor scheduler stopped")
    
    def _schedule_sensor(self, sensor: Dict):
        """
        Schedule a single sensor based on its interval.
        
        Args:
            sensor: Sensor dict with id and interval_seconds
        """
        sensor_id = sensor['id']
        interval_ms = sensor.get('interval_seconds', 600) * 1000
        
        # Remove existing timer if any
        if sensor_id in self.timers:
            self.timers[sensor_id].stop()
            del self.timers[sensor_id]
        
        # Create new timer
        timer = QTimer()
        timer.setSingleShot(False)
        timer.setInterval(interval_ms)
        # Use lambda with sensor_id capture to avoid closure issues
        timer.timeout.connect(lambda checked=False, sid=sensor_id: self._on_sensor_due(sid))
        timer.start()
        
        self.timers[sensor_id] = timer
        logger.debug(f"Scheduled sensor {sensor_id} with interval {interval_ms}ms")
    
    def _on_sensor_due(self, sensor_id: int):
        """
        Handle sensor update due - check if already processing.
        
        Args:
            sensor_id: Sensor ID
        """
        # Prevent overlapping calls
        if sensor_id in self.processing:
            logger.debug(f"Sensor {sensor_id} already processing, skipping")
            return  # Skip if already processing
        
        # Mark as processing
        self.processing.add(sensor_id)
        
        # Emit signal (will be handled by async queue)
        self.sensor_update_due.emit(sensor_id)
        logger.debug(f"Emitted sensor_update_due signal for sensor {sensor_id}")
    
    def mark_sensor_complete(self, sensor_id: int):
        """
        Mark sensor as complete (called by async queue).
        
        Args:
            sensor_id: Sensor ID
        """
        self.processing.discard(sensor_id)
        logger.debug(f"Marked sensor {sensor_id} as complete")
    
    def update_sensor_schedule(self, sensor_id: int):
        """
        Update schedule for a sensor (e.g., after config change).
        
        Args:
            sensor_id: Sensor ID
        """
        sensor = self.sensor_registry.get_sensor(sensor_id)
        if sensor and sensor.get('enabled'):
            self._schedule_sensor(sensor)
        elif sensor_id in self.timers:
            # Sensor disabled, stop timer
            self.timers[sensor_id].stop()
            del self.timers[sensor_id]
