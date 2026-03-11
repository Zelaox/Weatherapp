"""Logging system for weather application."""

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

# Lock to prevent multiple WeatherLogger instances from interfering
_logger_lock = threading.Lock()
_logger_initialized = False


class LevelFilter(logging.Filter):
    """Filter to allow only specific log levels."""
    
    def __init__(self, allowed_levels):
        """
        Initialize filter.
        
        Args:
            allowed_levels: List of log levels to allow (e.g., [logging.ERROR, logging.CRITICAL])
        """
        super().__init__()
        self.allowed_levels = allowed_levels
    
    def filter(self, record):
        """Filter log records by level."""
        return record.levelno in self.allowed_levels


class WeatherLogger:
    """Centralized logging for weather application."""
    
    def __init__(self, log_dir: str = "logs", log_level: int = logging.INFO):
        """
        Initialize logger.
        
        Args:
            log_dir: Directory for log files
            log_level: Logging level
        """
        global _logger_initialized
        
        # Use lock to prevent multiple instances from interfering
        with _logger_lock:
            self.log_dir = Path(log_dir)
            # Create log directory if it doesn't exist
            try:
                self.log_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"Warning: Could not create log directory {log_dir}: {e}")
            
            # Get date string for log filenames
            date_str = datetime.now().strftime('%Y%m%d')
            
            # Formatter
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            # Configure root logger to catch all loggers (including WeatherApp.*)
            root_logger = logging.getLogger()
            root_logger.setLevel(log_level)
            
            # Only clear and reconfigure if not already initialized
            # This prevents deadlocks when multiple WeatherLogger instances are created
            if not _logger_initialized:
                # Clear any existing handlers to avoid duplicates
                # Use try-except to handle case where handlers might be in use
                try:
                    root_logger.handlers.clear()
                except Exception as e:
                    # If clearing fails, just log a warning and continue
                    # This can happen if handlers are being used during import
                    print(f"Warning: Could not clear existing handlers: {e}")
        
            # Only add handlers if not already initialized
            if not _logger_initialized:
                # Main log file (INFO, WARNING, ERROR, CRITICAL)
                main_log_file = self.log_dir / f"weather_{date_str}.log"
                main_file_handler = logging.FileHandler(main_log_file, encoding='utf-8')
                main_file_handler.setLevel(logging.INFO)  # INFO and above
                main_file_handler.addFilter(LevelFilter([logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]))
                main_file_handler.setFormatter(formatter)
                root_logger.addHandler(main_file_handler)
                
                # Error log file (ERROR and CRITICAL only)
                error_log_file = self.log_dir / f"weather_error_{date_str}.log"
                error_file_handler = logging.FileHandler(error_log_file, encoding='utf-8')
                error_file_handler.setLevel(logging.ERROR)  # ERROR and above
                error_file_handler.addFilter(LevelFilter([logging.ERROR, logging.CRITICAL]))
                error_file_handler.setFormatter(formatter)
                root_logger.addHandler(error_file_handler)
                
                # Debug log file (DEBUG only)
                debug_log_file = self.log_dir / f"weather_debug_{date_str}.log"
                debug_file_handler = logging.FileHandler(debug_log_file, encoding='utf-8')
                debug_file_handler.setLevel(logging.DEBUG)  # DEBUG and above
                debug_file_handler.addFilter(LevelFilter([logging.DEBUG]))
                debug_file_handler.setFormatter(formatter)
                root_logger.addHandler(debug_file_handler)
                
                # Console handler (all levels)
                console_handler = logging.StreamHandler()
                console_handler.setLevel(log_level)
                console_handler.setFormatter(formatter)
                root_logger.addHandler(console_handler)
                
                _logger_initialized = True
            
            # Create WeatherApp logger (for backward compatibility with WeatherLogger class)
            self.logger = logging.getLogger("WeatherApp")
            self.logger.setLevel(log_level)
            # Ensure it propagates to root logger
            self.logger.propagate = True
            
            # Explicitly configure child loggers to ensure they propagate correctly
            # This ensures all WeatherApp.* loggers inherit the configuration
            for namespace in ['WeatherApp.analytics', 'WeatherApp.gui', 'WeatherApp.database', 
                             'WeatherApp.core', 'WeatherApp.providers', 'WeatherApp.ui', 'WeatherApp.utils']:
                child_logger = logging.getLogger(namespace)
                child_logger.setLevel(log_level)
                child_logger.propagate = True  # Propagate to root logger
                child_logger.handlers = []  # Don't add handlers directly, use parent
            
            # Log startup message to verify logging works (only first time)
            if _logger_initialized:
                test_logger = logging.getLogger("WeatherApp")
                test_logger.info("Logging system initialized successfully")
                test_logger.debug("Debug logging enabled")
        
        # Store log messages for GUI
        self.log_messages = []
        self.max_log_messages = 1000
    
    def info(self, message: str):
        """Log info message."""
        self.logger.info(message)
        self._add_to_gui_logs("INFO", message)
    
    def warning(self, message: str, exc_info=None):
        """Log warning message."""
        if exc_info:
            self.logger.warning(message, exc_info=exc_info)
        else:
            self.logger.warning(message)
        self._add_to_gui_logs("WARNING", message)
    
    def error(self, message: str, exc_info=None):
        """Log error message."""
        if exc_info:
            self.logger.error(message, exc_info=exc_info)
        else:
            self.logger.error(message)
        self._add_to_gui_logs("ERROR", message)
    
    def critical(self, message: str, exc_info=None):
        """Log critical message."""
        if exc_info:
            self.logger.critical(message, exc_info=exc_info)
        else:
            self.logger.critical(message)
        self._add_to_gui_logs("CRITICAL", message)
    
    def debug(self, message: str):
        """Log debug message."""
        self.logger.debug(message)
        self._add_to_gui_logs("DEBUG", message)
    
    def _add_to_gui_logs(self, level: str, message: str):
        """Add log message to GUI log list."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] {message}"
        self.log_messages.append(log_entry)
        
        # Keep only last N messages
        if len(self.log_messages) > self.max_log_messages:
            self.log_messages = self.log_messages[-self.max_log_messages:]
    
    def get_log_messages(self, limit: Optional[int] = None) -> list:
        """
        Get log messages for GUI.
        
        Args:
            limit: Maximum number of messages to return
            
        Returns:
            List of log messages
        """
        if limit:
            return self.log_messages[-limit:]
        return self.log_messages.copy()
    
    def clear_logs(self):
        """Clear GUI log messages."""
        self.log_messages.clear()
