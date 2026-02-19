"""Base provider interface for weather APIs."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Optional


class WeatherProvider(ABC):
    """Abstract base class for weather API providers."""
    
    @abstractmethod
    def get_current_weather(self, latitude: float, longitude: float) -> Optional[Dict]:
        """
        Get current weather data for given coordinates.
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            
        Returns:
            Dictionary with standardized structure:
            {
                'temperature': float,
                'humidity': float,
                'wind_speed': float,
                'aqi': float | None,
                'timestamp': datetime,
                'source': str
            }
            or None if error
        """
        pass
    
    @abstractmethod
    def get_air_quality(self, latitude: float, longitude: float) -> Optional[Dict[str, Optional[float]]]:
        """
        Get raw pollutant values for given coordinates.
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            
        Returns:
            Dictionary with keys: pm25, pm10, no2, o3 (all in µg/m³)
            Values can be None if not available
            Returns None if no data available at all
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if provider is available/healthy.
        
        Returns:
            True if available, False otherwise
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass
