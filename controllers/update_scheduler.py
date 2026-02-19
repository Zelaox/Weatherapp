"""Update scheduler for automatic weather updates."""

from PyQt5.QtCore import QTimer, QObject, pyqtSignal
from controllers.weather_controller import WeatherController


class UpdateScheduler(QObject):
    """Scheduler for automatic weather updates."""
    
    update_triggered = pyqtSignal()
    
    def __init__(self, controller: WeatherController):
        """
        Initialize scheduler.
        
        Args:
            controller: Weather controller instance
        """
        super().__init__()
        self.controller = controller
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_timeout)
        
        # Get interval from config
        interval_minutes = controller.config.get_setting("auto_update_interval_minutes", 10)
        self.set_interval(interval_minutes)
    
    def set_interval(self, minutes: int):
        """
        Set update interval.
        
        Args:
            minutes: Interval in minutes
        """
        self.interval_ms = minutes * 60 * 1000
        if self.timer.isActive():
            self.timer.setInterval(self.interval_ms)
    
    def start(self):
        """Start automatic updates."""
        if not self.timer.isActive():
            self.timer.start(self.interval_ms)
            interval_min = self.interval_ms // 60000
            self.controller.logger.info(f"Auto-uppdatering startad (intervall: {interval_min} minuter)")
        else:
            self.controller.logger.debug("Auto-uppdatering redan aktiv")
    
    def stop(self):
        """Stop automatic updates."""
        if self.timer.isActive():
            self.timer.stop()
            self.controller.logger.info("Auto-uppdatering stoppad")
        else:
            self.controller.logger.debug("Auto-uppdatering redan stoppad")
    
    def is_active(self) -> bool:
        """Check if scheduler is active."""
        return self.timer.isActive()
    
    def _on_timeout(self):
        """Handle timer timeout."""
        try:
            self.controller.logger.info("Auto-uppdatering utlöst")
            # Emit signal first to notify GUI
            self.update_triggered.emit()
            # Then trigger update
            self.controller.update_all_cities()
        except Exception as e:
            self.controller.logger.error(f"Fel i auto-uppdatering timeout: {e}")
            import traceback
            self.controller.logger.error(traceback.format_exc())
