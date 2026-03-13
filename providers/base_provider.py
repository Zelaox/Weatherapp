"""Base provider interface for weather APIs."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Optional, List, Any


class WeatherProvider(ABC):
    """Abstract base class for weather API providers."""
    
    def get_supported_parameters(self, db_manager: Any) -> Dict[str, List[str]]:
        """
        Dynamiskt hämta vilka parametrar denna provider stödjer.
        
        Args:
            db_manager: DatabaseManager instance för att query parameter_registry
        
        Returns:
            Dict med keys: 'weather', 'solar', 'storm', 'pollutants'
            Varje value är lista av parameter_names från parameter_registry
        """
        try:
            # Query parameter_registry för att hitta parametrar per kategori
            weather_params = db_manager.get_parameters_by_category('weather')
            solar_params = db_manager.get_parameters_by_category('solar') if hasattr(db_manager, 'get_parameters_by_category') else []
            storm_params = db_manager.get_parameters_by_category('storm') if hasattr(db_manager, 'get_parameters_by_category') else []
            pollutant_params = db_manager.get_parameters_by_category('air_quality')
            
            # Extract parameter_name from each dict
            return {
                'weather': [p.get('parameter_name') for p in weather_params if p.get('parameter_name')],
                'solar': [p.get('parameter_name') for p in solar_params if p.get('parameter_name')],
                'storm': [p.get('parameter_name') for p in storm_params if p.get('parameter_name')],
                'pollutants': [p.get('parameter_name') for p in pollutant_params if p.get('parameter_name')]
            }
        except Exception as e:
            # No fallback - return empty dict if error
            return {
                'weather': [],
                'solar': [],
                'storm': [],
                'pollutants': []
            }
    
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
