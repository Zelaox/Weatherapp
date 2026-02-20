"""UI layer - completely decoupled from providers."""

from core.sensor_registry import SensorRegistry
from core.event_bus import EventBus
import logging

logger = logging.getLogger("WeatherApp.ui.map_renderer")


class MapRenderer:
    """UI layer - completely decoupled from providers."""
    
    def __init__(self, sensor_registry: SensorRegistry, event_bus: EventBus):
        """
        Initialize map renderer.
        
        Args:
            sensor_registry: Sensor registry
            event_bus: Event bus
        """
        self.sensor_registry = sensor_registry
        self.event_bus = event_bus
        
        # Connect to events
        self.event_bus.sensor_updated.connect(self._on_sensor_updated)
        self.event_bus.sensor_error.connect(self._on_sensor_error)
    
    def render_sensors(self):
        """
        Render all active sensors based on visibility_mode.
        
        This is a placeholder - actual rendering depends on the map library used.
        """
        sensors = self.sensor_registry.get_active_sensors()
        logger.debug(f"Rendering {len(sensors)} sensors")
        
        for sensor in sensors:
            visibility_mode = sensor.get('visibility_mode', 'marker')
            
            if visibility_mode == 'marker':
                self._render_marker(sensor)
            elif visibility_mode == 'heatmap':
                # Don't render here, heatmap reads from DB
                pass
    
    def _render_marker(self, sensor: Dict):
        """
        Render a marker for a sensor.
        
        Args:
            sensor: Sensor dict
        """
        # Placeholder - actual implementation depends on map library
        logger.debug(f"Rendering marker for sensor {sensor.get('id')}")
    
    def _on_sensor_updated(self, sensor_id: int):
        """
        Update single sensor on map (event-driven).
        
        Args:
            sensor_id: Sensor ID
        """
        sensor = self.sensor_registry.get_sensor(sensor_id)
        if sensor:
            self._update_sensor_marker(sensor)
            logger.debug(f"Updated marker for sensor {sensor_id}")
    
    def _update_sensor_marker(self, sensor: Dict):
        """
        Update marker for a sensor.
        
        Args:
            sensor: Sensor dict
        """
        # Placeholder - actual implementation depends on map library
        logger.debug(f"Updating marker for sensor {sensor.get('id')}")
    
    def _on_sensor_error(self, sensor_id: int, error: str):
        """
        Handle sensor error event.
        
        Args:
            sensor_id: Sensor ID
            error: Error message
        """
        logger.warning(f"Sensor {sensor_id} error: {error}")
        # Could update marker to show error state
