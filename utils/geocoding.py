"""Geocoding utility for converting city names to coordinates."""

import requests
from typing import Optional, Tuple
from utils.logger import WeatherLogger


class Geocoder:
    """Geocoding service using Nominatim (OpenStreetMap)."""
    
    BASE_URL = "https://nominatim.openstreetmap.org/search"
    
    def __init__(self, logger: Optional[WeatherLogger] = None):
        """
        Initialize geocoder.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger
    
    def geocode(self, city_name: str, country: Optional[str] = None) -> Optional[Tuple[float, float]]:
        """
        Geocode city name to coordinates.
        
        Args:
            city_name: Name of the city
            country: Optional country code (e.g., 'SE' for Sweden)
            
        Returns:
            Tuple of (latitude, longitude) or None if not found
        """
        if self.logger:
            self.logger.info(f"Försöker geokoda '{city_name}'...")
        
        try:
            query = city_name
            if country:
                query = f"{city_name}, {country}"
            
            params = {
                "q": query,
                "format": "json",
                "limit": 1,
                "addressdetails": 1
            }
            
            headers = {
                "User-Agent": "WeatherApp/1.0"
            }
            
            if self.logger:
                self.logger.debug(f"Skickar geocoding request: {query}")
            
            response = requests.get(self.BASE_URL, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data and len(data) > 0:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                
                if self.logger:
                    self.logger.info(f"Geokodade '{city_name}' till ({lat}, {lon})")
                
                return (lat, lon)
            else:
                if self.logger:
                    self.logger.warning(f"Kunde inte hitta koordinater för '{city_name}'")
                return None
                
        except requests.RequestException as e:
            if self.logger:
                self.logger.error(f"Geocoding-fel för '{city_name}': {e}")
            return None
        except (KeyError, ValueError, IndexError) as e:
            if self.logger:
                self.logger.error(f"Ogiltigt geocoding-svar för '{city_name}': {e}")
            return None
