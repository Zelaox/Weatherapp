"""Open-Meteo weather API provider."""

import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Optional, Any
from providers.base_provider import WeatherProvider
from utils.logger import WeatherLogger

# CET timezone for all operations
CET = ZoneInfo("Europe/Stockholm")


class OpenMeteoProvider(WeatherProvider):
    """Open-Meteo API provider (no API key required)."""
    
    BASE_URL = "https://api.open-meteo.com/v1"
    
    def __init__(self, logger: Optional[WeatherLogger] = None):
        """
        Initialize Open-Meteo provider.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger
        self._available = True
    
    @property
    def name(self) -> str:
        """Provider name."""
        return "openmeteo"
    
    def get_current_weather(self, latitude: float, longitude: float) -> Optional[Dict]:
        """Get current weather data."""
        try:
            # Current weather
            weather_url = f"{self.BASE_URL}/forecast"
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
                "timezone": "auto"
            }
            
            try:
                response = requests.get(weather_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.Timeout:
                if self.logger:
                    self.logger.warning(f"Open-Meteo timeout för ({latitude}, {longitude})")
                return None
            except requests.exceptions.ConnectionError as e:
                if self.logger:
                    self.logger.warning(f"Open-Meteo anslutningsfel: {e}")
                return None
            except requests.exceptions.RequestException as e:
                if self.logger:
                    self.logger.warning(f"Open-Meteo request-fel: {e}")
                return None
            
            if "current" not in data:
                return None
            
            current = data["current"]
            
            # Get air quality (raw pollutants)
            # NOTE: This may cause duplicate API calls if controller also calls get_air_quality() separately
            # Consider removing this and letting controller handle air quality separately
            if self.logger:
                self.logger.debug(f"Open-Meteo: Anropar get_air_quality() från get_current_weather() för ({latitude}, {longitude})")
            air_quality_result = self.get_air_quality(latitude, longitude)
            
            # Extract pollutants and measurement timestamp
            pollutants = {}
            measurement_timestamp = None
            if air_quality_result:
                pollutants = air_quality_result.get("pollutants", {})
                measurement_timestamp = air_quality_result.get("measurement_timestamp")
            
            # Extract timestamp from current weather data if available
            current_time_str = current.get("time")
            if current_time_str and not measurement_timestamp:
                try:
                    measurement_timestamp = datetime.fromisoformat(current_time_str)
                    if measurement_timestamp.tzinfo is None:
                        measurement_timestamp = measurement_timestamp.replace(tzinfo=CET)
                    else:
                        measurement_timestamp = measurement_timestamp.astimezone(CET)
                except (ValueError, TypeError):
                    pass
            
            # Use measurement timestamp if available, otherwise use collector timestamp
            timestamp = measurement_timestamp if measurement_timestamp else datetime.now(CET)
            
            result = {
                "temperature": float(current.get("temperature_2m", 0)),
                "humidity": float(current.get("relative_humidity_2m", 0)),
                "wind_speed": float(current.get("wind_speed_10m", 0)),
                "pm25": pollutants.get("pm25") if pollutants else None,
                "pm10": pollutants.get("pm10") if pollutants else None,
                "no2": pollutants.get("no2") if pollutants else None,
                "o3": pollutants.get("o3") if pollutants else None,
                "timestamp": timestamp,
                "measurement_timestamp": measurement_timestamp,  # Include for controller
                "source": self.name
            }
            
            if self.logger:
                self.logger.debug(f"Open-Meteo: Retrieved weather for ({latitude}, {longitude})")
            
            return result
            
        except (KeyError, ValueError, TypeError) as e:
            if self.logger:
                self.logger.error(f"Open-Meteo parsing error: {e}")
            return None
        except Exception as e:
            if self.logger:
                self.logger.error(f"Open-Meteo oväntat fel: {e}")
            return None
    
    def get_air_quality(self, latitude: float, longitude: float) -> Optional[Dict[str, Any]]:
        """
        Get raw pollutant values.
        
        Open-Meteo primarily provides european_aqi, not raw pollutant values.
        Returns None if only AQI is available (we don't convert AQI back to PM2.5).
        
        Returns:
            Dictionary with:
            - "pollutants": Dict with pm25, pm10, no2, o3 (all None for Open-Meteo)
            - "measurement_timestamp": datetime or None (if available in response)
            Returns None if no data
        """
        try:
            # Open-Meteo uses /v1/forecast endpoint with current=european_aqi
            aqi_url = f"{self.BASE_URL}/forecast"
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current": "european_aqi",
                "timezone": "auto"
            }
            
            if self.logger:
                self.logger.info(f"Open-Meteo: Hämtar AQI för ({latitude}, {longitude}) via /forecast endpoint")
            
            try:
                response = requests.get(aqi_url, params=params, timeout=10)
                if self.logger:
                    self.logger.info(f"Open-Meteo AQI response status: {response.status_code}")
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.Timeout:
                if self.logger:
                    self.logger.info(f"Open-Meteo AQI timeout för ({latitude}, {longitude})")
                return None
            except requests.exceptions.ConnectionError as e:
                if self.logger:
                    self.logger.info(f"Open-Meteo AQI connection error för ({latitude}, {longitude}): {e}")
                return None
            except requests.exceptions.RequestException as e:
                if self.logger:
                    self.logger.info(f"Open-Meteo AQI request error för ({latitude}, {longitude}): {e}")
                return None
            
            # Log response summary for debugging
            if self.logger:
                has_current = "current" in data
                if has_current:
                    current = data.get("current", {})
                    current_keys = list(current.keys()) if isinstance(current, dict) else []
                    has_aqi = "european_aqi" in current
                    aqi_value = current.get("european_aqi")
                    self.logger.info(f"Open-Meteo AQI response för ({latitude}, {longitude}): has_current={has_current}, current_keys={current_keys[:10]}, has_european_aqi={has_aqi}, value={aqi_value}")
                    
                    # Log full current structure for debugging (first time)
                    if isinstance(current, dict):
                        import json
                        sample = {k: v for k, v in list(current.items())[:5]}
                        self.logger.debug(f"Open-Meteo current sample: {json.dumps(sample, indent=2)}")
                else:
                    self.logger.info(f"Open-Meteo AQI response för ({latitude}, {longitude}): has_current=False")
            
            # Extract measurement timestamp if available
            measurement_timestamp = None
            if "current" in data:
                current = data["current"]
                # Open-Meteo may have "time" field in current
                time_str = current.get("time")
                if time_str:
                    try:
                        measurement_timestamp = datetime.fromisoformat(time_str)
                        if measurement_timestamp.tzinfo is None:
                            # If naive, assume CET (Open-Meteo uses timezone from params)
                            measurement_timestamp = measurement_timestamp.replace(tzinfo=CET)
                        else:
                            measurement_timestamp = measurement_timestamp.astimezone(CET)
                        if self.logger:
                            self.logger.debug(f"Open-Meteo: Extraherade measurement timestamp: {measurement_timestamp}")
                    except (ValueError, TypeError) as e:
                        if self.logger:
                            self.logger.debug(f"Open-Meteo: Kunde inte parsa timestamp {time_str}: {e}")
            
            # Open-Meteo doesn't provide raw pollutant values in the forecast endpoint
            # It only provides european_aqi, which we can't convert back to PM2.5
            # Return structure with None pollutants but include timestamp if available
            if self.logger:
                self.logger.info(f"Open-Meteo: Ingen rådata för pollutant-värden tillgänglig (endast european_aqi)")
            
            # Return structure matching OpenAQ format
            return {
                "pollutants": {
                    "pm25": None,
                    "pm10": None,
                    "no2": None,
                    "o3": None
                },
                "measurement_timestamp": measurement_timestamp
            }
            
        except (KeyError, ValueError, TypeError) as e:
            if self.logger:
                self.logger.info(f"Open-Meteo AQI parsing error för ({latitude}, {longitude}): {e}")
            return None
        except Exception as e:
            if self.logger:
                self.logger.info(f"Open-Meteo AQI unexpected error för ({latitude}, {longitude}): {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if provider is available."""
        return self._available
