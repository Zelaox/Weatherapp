"""Main entry point for weather application."""

import sys
import os
from pathlib import Path

# Create logs directory first
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Set environment variable to disable pyqtgraph if it causes issues
os.environ.setdefault('PYQTGRAPH_QT_LIB', 'PyQt5')

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
import asyncio
from controllers.weather_controller import WeatherController
from controllers.update_scheduler import UpdateScheduler
from gui.main_window import MainWindow
from utils.logger import WeatherLogger

# qasync for Qt + asyncio integration
try:
    from qasync import QEventLoop
    HAS_QASYNC = True
except ImportError:
    HAS_QASYNC = False
    logger = WeatherLogger()
    logger.warning("qasync not installed - sensor engine async features will not work")
    logger.warning("Install with: pip install qasync")

# New sensor engine imports
from database.db_manager import DatabaseManager
from core.sensor_registry import SensorRegistry
from core.provider_registry import ProviderRegistry
from core.sensor_scheduler import SensorScheduler
from core.async_queue import AsyncSensorQueue
from core.data_pipeline import DataPipeline
from core.write_queue import WriteQueue
from core.event_bus import EventBus
from core.validation_layer import ValidationLayer
from core.security_middleware import SecurityMiddleware
from ui.map_renderer import MapRenderer


def main():
    """Main application entry point."""
    # Initialize logger first
    logger = WeatherLogger()
    logger.info("=" * 60)
    logger.info("Startar väderapplikation")
    logger.info("=" * 60)
    
    try:
        # Create application
        logger.info("Skapar QApplication...")
        app = QApplication(sys.argv)
        app.setApplicationName("Väderapplikation")
        logger.info("QApplication skapad")
        
        # Setup asyncio event loop for Qt integration (required for sensor engine)
        loop = None
        if HAS_QASYNC:
            loop = QEventLoop(app)
            asyncio.set_event_loop(loop)
            logger.info("qasync event loop konfigurerad för Qt + asyncio integration")
        else:
            logger.warning("qasync saknas - sensor engine async features kommer inte fungera")
        
        # Initialize database (shared instance)
        logger.info("Initialiserar databas...")
        db = DatabaseManager()
        logger.info("Databas initialiserad")
        
        # Initialize controller (pass shared DB instance if possible)
        logger.info("Initialiserar controller...")
        controller = WeatherController()
        logger.info("Controller initialiserad")
        
        # Initialize scheduler
        logger.info("Initialiserar scheduler...")
        scheduler = UpdateScheduler(controller)
        logger.info("Scheduler initialiserad")
        
        # Create main window
        logger.info("Skapar huvudfönster...")
        window = MainWindow(controller)
        logger.info("Huvudfönster skapat")
        
        # Note: UI refresh is now event-driven via controller.data_updated signal
        # The scheduler's update_triggered signal is not connected to refresh
        # because we only want to refresh when data is actually saved, not when update starts
        logger.info("UI refresh är event-driven (endast vid faktisk datainsättning)")
        
        # Add scheduler methods to controller for GUI access
        controller.start_auto_update = scheduler.start
        controller.stop_auto_update = scheduler.stop
        def safe_manual_update():
            """Safely trigger manual update."""
            try:
                controller.update_all_cities()
                # UI will refresh automatically via data_updated signal when data is saved
                # No need for timer-based refresh - event-driven is better
            except Exception as e:
                logger.error(f"Fel vid manuell uppdatering: {e}")
        
        controller.manual_update = safe_manual_update
        logger.info("Scheduler-metoder kopplade till controller")
        
        # Auto-update is off by default - user can enable it via toolbar button
        # scheduler.start()  # Not started by default
        logger.info("Auto-uppdatering är av som standard (använd knappen i verktygsfältet för att aktivera)")
        
        # Initialize new sensor engine system (optional, can be enabled separately)
        sensor_engine = None
        if HAS_QASYNC:
            try:
                logger.info("Initialiserar sensor engine system...")
                # Use shared DB instance (already initialized above)
                
                # Initialize components
                sensor_registry = SensorRegistry(db)
                provider_registry = ProviderRegistry()  # Auto-discovers providers
                event_bus = EventBus()
                validation_layer = ValidationLayer()
                security_middleware = SecurityMiddleware()
                write_queue = WriteQueue(db)
                
                data_pipeline = DataPipeline(
                    sensor_registry, 
                    provider_registry, 
                    db, 
                    event_bus, 
                    validation_layer,
                    write_queue
                )
                
                async_queue = AsyncSensorQueue(data_pipeline, max_concurrent=10)
                scheduler_engine = SensorScheduler(sensor_registry, provider_registry)
                
                # Connect signals: scheduler → async queue
                # With qasync, we can directly use asyncio in Qt event loop
                def on_sensor_due(sensor_id: int):
                    """Handle sensor update due signal."""
                    # With qasync, event loop is already running, so we can create tasks directly
                    try:
                        event_loop = asyncio.get_event_loop()
                        if event_loop.is_running():
                            asyncio.create_task(async_queue.enqueue(sensor_id))
                        else:
                            # Fallback: schedule via QTimer
                            QTimer.singleShot(0, lambda: asyncio.create_task(async_queue.enqueue(sensor_id)))
                    except Exception as e:
                        logger.warning(f"Error scheduling sensor {sensor_id} update: {e}")
                
                scheduler_engine.sensor_update_due.connect(on_sensor_due)
                
                # Start components
                write_queue.start()
                async_queue.start()
                # Note: scheduler_engine.start() can be called later to activate sensors
                
                # Create map renderer (optional, for UI integration)
                map_renderer = MapRenderer(sensor_registry, event_bus)
                
                sensor_engine = {
                    'scheduler': scheduler_engine,
                    'async_queue': async_queue,
                    'write_queue': write_queue,
                    'event_bus': event_bus,
                    'map_renderer': map_renderer,
                    'sensor_registry': sensor_registry,
                    'provider_registry': provider_registry
                }
                
                logger.info("Sensor engine system initialiserat")
                logger.info(f"Tillgängliga providers: {provider_registry.get_available_types()}")
                
            except Exception as e:
                logger.warning(f"Kunde inte initialisera sensor engine system: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                # Continue without sensor engine - it's optional
        else:
            logger.info("Sensor engine system hoppas över (qasync saknas)")
        
        # Initial update is DISABLED by default
        # User must manually trigger update or enable auto-update
        # If you want initial data load, uncomment below:
        # logger.info("Schemalägger initial uppdatering (2 sekunder delay)...")
        # def safe_update():
        #     """Safely trigger update from main thread."""
        #     try:
        #         logger.debug("Utlöser initial uppdatering...")
        #         controller.update_all_cities()
        #     except Exception as e:
        #         logger.error(f"Fel vid initial uppdatering: {e}")
        #         import traceback
        #         logger.error(traceback.format_exc())
        # QTimer.singleShot(2000, safe_update)
        logger.info("Ingen automatisk initial uppdatering - använd manuell uppdatering eller aktivera auto-update")
        
        # Run application
        logger.info("Startar applikationsloop...")
        logger.info("=" * 60)
        
        try:
            if HAS_QASYNC and loop is not None:
                # Run with qasync event loop
                with loop:
                    window.show()
                    logger.info("Huvudfönster visas (med qasync event loop)")
                    exit_code = loop.run_forever()
            else:
                # Run without qasync (sensor engine won't work)
                window.show()
                logger.info("Huvudfönster visas (utan qasync)")
                exit_code = app.exec_()
        finally:
            # Cleanup sensor engine if it was initialized
            if sensor_engine:
                try:
                    logger.info("Stänger ner sensor engine system...")
                    sensor_engine['scheduler'].stop()
                    sensor_engine['async_queue'].stop()
                    sensor_engine['write_queue'].stop()
                    logger.info("Sensor engine system stängt")
                except Exception as e:
                    logger.warning(f"Fel vid stängning av sensor engine: {e}")
        
        logger.info("=" * 60)
        logger.info(f"Applikation avslutas med kod: {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        import traceback
        error_msg = f"Kritiskt fel vid start: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        print(f"Fel vid start: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
