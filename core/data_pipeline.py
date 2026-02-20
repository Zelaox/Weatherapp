"""Data pipeline: fetch → validate → store → emit."""

from core.sensor_registry import SensorRegistry
from core.provider_registry import ProviderRegistry
from core.sensor_provider import SensorReading
from database.db_manager import DatabaseManager
from core.event_bus import EventBus
from core.validation_layer import ValidationLayer
from core.write_queue import WriteQueue
import json
import logging

logger = logging.getLogger("WeatherApp.core.data_pipeline")


class DataPipeline:
    """Data pipeline: fetch → validate → store → emit."""
    
    def __init__(self, sensor_registry: SensorRegistry, provider_registry: ProviderRegistry, 
                 db: DatabaseManager, event_bus: EventBus, validation_layer: ValidationLayer, 
                 write_queue: WriteQueue):
        """
        Initialize data pipeline.
        
        Args:
            sensor_registry: Sensor registry
            provider_registry: Provider registry
            db: Database manager
            event_bus: Event bus
            validation_layer: Validation layer
            write_queue: Write queue for batched writes
        """
        self.sensor_registry = sensor_registry
        self.provider_registry = provider_registry
        self.db = db
        self.event_bus = event_bus
        self.validation_layer = validation_layer
        self.write_queue = write_queue  # Batched write queue
    
    async def process_sensor(self, sensor_id: int):
        """
        Process a single sensor: fetch, validate, store, emit.
        
        Args:
            sensor_id: Sensor ID to process
        """
        # 1. Get sensor from registry
        sensor = self.sensor_registry.get_sensor(sensor_id)
        if not sensor or not sensor.get('enabled'):
            logger.debug(f"Sensor {sensor_id} not found or disabled")
            return
        
        # 2. Get provider
        provider_type = sensor.get('provider_type')
        if not provider_type:
            self._mark_error(sensor_id, "No provider_type specified")
            return
        
        config = sensor.get('config_json', {})
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except json.JSONDecodeError:
                self._mark_error(sensor_id, "Invalid config_json format")
                return
        
        provider = self.provider_registry.get_provider(provider_type, logger=logger)
        if not provider:
            self._mark_error(sensor_id, f"Provider {provider_type} not found")
            return
        
        # 3. Validate config
        is_valid, error = provider.validate_config(config)
        if not is_valid:
            self._mark_error(sensor_id, f"Invalid config: {error}")
            return
        
        # 4. Fetch data
        try:
            reading = await provider.fetch(config)
            if not reading:
                self._mark_error(sensor_id, "Provider returned None")
                return
        except Exception as e:
            logger.error(f"Error fetching data for sensor {sensor_id}: {e}")
            self._mark_error(sensor_id, str(e))
            return
        
        # 5. Validate reading
        is_valid, error = self.validation_layer.validate_reading(reading)
        if not is_valid:
            self._mark_error(sensor_id, f"Invalid reading: {error}")
            return
        
        # 6. Queue write (batched, not immediate)
        await self.write_queue.enqueue_reading(
            sensor_id=sensor_id,
            value=reading.value,
            parameter=reading.parameter,
            timestamp=reading.timestamp
        )
        
        # 7. Update sensor last_value (also queued)
        await self.write_queue.enqueue_sensor_update(
            sensor_id=sensor_id,
            last_value=reading.value,
            last_updated=reading.timestamp
        )
        
        # 8. Emit event (after successful validation)
        self.event_bus.emit('sensor_updated', sensor_id=sensor_id)
        
        # 9. Clear error status
        self.sensor_registry.update_sensor_status(sensor_id, error=None)
        
        logger.debug(f"Successfully processed sensor {sensor_id}")
    
    def _mark_error(self, sensor_id: int, error: str):
        """
        Mark sensor as error state.
        
        Args:
            sensor_id: Sensor ID
            error: Error message
        """
        logger.warning(f"Sensor {sensor_id} error: {error}")
        self.sensor_registry.update_sensor_status(sensor_id, error=error)
        self.event_bus.emit('sensor_error', sensor_id=sensor_id, error=error)
