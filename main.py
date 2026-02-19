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
from controllers.weather_controller import WeatherController
from controllers.update_scheduler import UpdateScheduler
from gui.main_window import MainWindow
from utils.logger import WeatherLogger


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
        
        # Initialize controller
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
        
        # Connect scheduler to window refresh
        def refresh_on_update():
            """Safely refresh GUI from main thread."""
            try:
                logger.debug("Uppdaterar GUI efter scheduler trigger")
                window.refresh_all()
            except Exception as e:
                logger.error(f"Fel vid GUI-uppdatering: {e}")
        
        scheduler.update_triggered.connect(refresh_on_update)
        logger.info("Scheduler kopplad till GUI refresh")
        
        # Add scheduler methods to controller for GUI access
        controller.start_auto_update = scheduler.start
        controller.stop_auto_update = scheduler.stop
        def safe_manual_update():
            """Safely trigger manual update."""
            try:
                controller.update_all_cities()
                # Refresh GUI after a short delay to let data update
                QTimer.singleShot(500, window.refresh_all)
            except Exception as e:
                logger.error(f"Fel vid manuell uppdatering: {e}")
        
        controller.manual_update = safe_manual_update
        logger.info("Scheduler-metoder kopplade till controller")
        
        # Auto-update is off by default - user can enable it via toolbar button
        # scheduler.start()  # Not started by default
        logger.info("Auto-uppdatering är av som standard (använd knappen i verktygsfältet för att aktivera)")
        
        # Show window
        logger.info("Visar huvudfönster...")
        window.show()
        logger.info("Huvudfönster visas")
        
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
        exit_code = app.exec_()
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
