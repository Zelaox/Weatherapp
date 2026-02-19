"""OpenWeatherMap API provider."""

import requests
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Optional, Any
from providers.base_provider import WeatherProvider
from utils.logger import WeatherLogger
from utils.rate_limiter import RateLimiter

# CET timezone for all operations
CET = ZoneInfo("Europe/Stockholm")


class OpenWeatherProvider(WeatherProvider):
    """OpenWeatherMap API provider."""
    
    BASE_URL = "https://api.openweathermap.org/data/2.5"
    
    def __init__(self, api_key: str, logger: Optional[WeatherLogger] = None):
        """
        Initialize OpenWeather provider.
        
        Args:
            api_key: OpenWeatherMap API key
            logger: Optional logger instance
        """
        if not api_key:
            raise ValueError("OpenWeatherMap API key is required")
        
        self.api_key = api_key
        self.logger = logger
        self._available = True
        
        # Rate limiter: 60 requests/minute, 2000 requests/hour (conservative)
        # OpenWeather free tier: 60/min, 1M/month (monthly limit is very high)
        self.rate_limiter = RateLimiter(requests_per_minute=60, requests_per_hour=2000)
    
    @property
    def name(self) -> str:
        """Provider name."""
        return "openweather"
    
    def get_current_weather(self, latitude: float, longitude: float) -> Optional[Dict]:
        """Get current weather data."""
        try:
            url = f"{self.BASE_URL}/weather"
            params = {
                "lat": latitude,
                "lon": longitude,
                "appid": self.api_key,
                "units": "metric"
            }
            
            # Check rate limits before making request
            if self.rate_limiter.should_wait():
                wait_time = self.rate_limiter.wait_if_needed()
                if wait_time > 0 and self.logger:
                    self.logger.debug(f"OpenWeather: Väntade {wait_time:.1f}s för rate limit")
            
            response = requests.get(url, params=params, timeout=10)
            
            # Update rate limiter from response headers (if available)
            self.rate_limiter.update_from_headers(response.headers)
            self.rate_limiter.record_request()
            
            # Handle 429 Too Many Requests
            if response.status_code == 429:
                retry_after = response.headers.get('Retry-After')
                wait_time = 60  # Default to 60 seconds
                if retry_after:
                    try:
                        wait_time = int(retry_after)
                    except (ValueError, TypeError):
                        pass
                
                if self.logger:
                    self.logger.warning(f"OpenWeather: Rate limit nådd (429). Väntar {wait_time}s...")
                time.sleep(wait_time)
                
                # Retry once after waiting
                response = requests.get(url, params=params, timeout=10)
                self.rate_limiter.update_from_headers(response.headers)
                self.rate_limiter.record_request()
                
                if self.logger:
                    self.logger.info(f"OpenWeather: Retry efter rate limit - status: {response.status_code}")
            
            response.raise_for_status()
            data = response.json()
            
            if "main" not in data or "wind" not in data:
                return None
            
            main = data["main"]
            wind = data.get("wind", {})
            
            # Extract timestamp from weather data if available
            measurement_timestamp = None
            if "dt" in data:
                try:
                    # OpenWeather uses Unix timestamp (seconds since epoch)
                    dt_unix = data["dt"]
                    measurement_timestamp = datetime.fromtimestamp(dt_unix, tz=CET)
                except (ValueError, TypeError, OSError):
                    pass
            
            # Get air quality
            # NOTE: This may cause duplicate API calls if controller also calls get_air_quality() separately
            # Consider removing this and letting controller handle air quality separately
            if self.logger:
                self.logger.debug(f"OpenWeather: Anropar get_air_quality() från get_current_weather() för ({latitude}, {longitude})")
            air_quality_result = self.get_air_quality(latitude, longitude)
            
            # Extract measurement timestamp from air quality if not in weather data
            if air_quality_result and not measurement_timestamp:
                measurement_timestamp = air_quality_result.get("measurement_timestamp")
            
            # Use measurement timestamp if available, otherwise use collector timestamp
            timestamp = measurement_timestamp if measurement_timestamp else datetime.now(CET)
            
            # Extract AQI from air quality result (if available)
            aqi = None
            if air_quality_result:
                # OpenWeather doesn't return raw pollutants, so no AQI calculation possible
                aqi = None
            
            result = {
                "temperature": float(main.get("temp", 0)),
                "humidity": float(main.get("humidity", 0)),
                "wind_speed": float(wind.get("speed", 0)),
                "aqi": aqi,
                "timestamp": timestamp,
                "measurement_timestamp": measurement_timestamp,  # Include for controller
                "source": self.name
            }
            
            if self.logger:
                self.logger.debug(f"OpenWeather: Retrieved weather for ({latitude}, {longitude})")
            
            return result
            
        except (KeyError, ValueError, TypeError) as e:
            if self.logger:
                self.logger.error(f"OpenWeather parsing error: {e}")
            return None
        except Exception as e:
            if self.logger:
                self.logger.error(f"OpenWeather oväntat fel: {e}")
            return None
    
    def get_air_quality(self, latitude: float, longitude: float) -> Optional[Dict[str, Any]]:
        """
        Get raw pollutant values.
        
        OpenWeather only provides categorical AQI (1-5 scale), not raw pollutant values.
        Returns None as we can't extract PM2.5/PM10 from categories.
        
        Returns:
            Dictionary with:
            - "pollutants": Dict with pm25, pm10, no2, o3 (all None for OpenWeather)
            - "measurement_timestamp": datetime or None (if available in response)
            Returns None if no data
        """
        try:
            url = f"{self.BASE_URL}/air_pollution"
            params = {
                "lat": latitude,
                "lon": longitude,
                "appid": self.api_key
            }
            
            try:
                # Check rate limits before making request
                if self.rate_limiter.should_wait():
                    wait_time = self.rate_limiter.wait_if_needed()
                    if wait_time > 0 and self.logger:
                        self.logger.debug(f"OpenWeather: Väntade {wait_time:.1f}s för rate limit (AQI)")
                
                response = requests.get(url, params=params, timeout=10)
                
                # Update rate limiter
                self.rate_limiter.update_from_headers(response.headers)
                self.rate_limiter.record_request()
                
                # Log rate limit status
                if self.logger:
                    status = self.rate_limiter.get_status()
                    self.logger.debug(f"OpenWeather rate limit: {status['requests_last_minute']}/{status['limit_per_minute']} per min, "
                                    f"{status['requests_last_hour']}/{status['limit_per_hour']} per hour")
                
                if self.logger:
                    self.logger.info(f"OpenWeather AQI response status: {response.status_code}")
                
                # Handle 429 Too Many Requests
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After')
                    wait_time = 60
                    if retry_after:
                        try:
                            wait_time = int(retry_after)
                        except (ValueError, TypeError):
                            pass
                    
                    if self.logger:
                        self.logger.warning(f"OpenWeather: Rate limit nådd vid AQI (429). Väntar {wait_time}s...")
                    time.sleep(wait_time)
                    
                    # Retry once
                    response = requests.get(url, params=params, timeout=10)
                    self.rate_limiter.update_from_headers(response.headers)
                    self.rate_limiter.record_request()
                    
                    if self.logger:
                        self.logger.info(f"OpenWeather: Retry AQI efter rate limit - status: {response.status_code}")
                
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.Timeout:
                if self.logger:
                    self.logger.info(f"OpenWeather AQI timeout för ({latitude}, {longitude})")
                return None
            except requests.exceptions.ConnectionError as e:
                if self.logger:
                    self.logger.info(f"OpenWeather AQI connection error för ({latitude}, {longitude}): {e}")
                return None
            except requests.exceptions.RequestException as e:
                error_details = ""
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_data = e.response.json()
                        error_details = f" - {error_data.get('message', str(error_data)[:200])}"
                    except:
                        error_details = f" - Status {e.response.status_code}"
                if self.logger:
                    self.logger.info(f"OpenWeather AQI request error för ({latitude}, {longitude}): {e}{error_details}")
                return None
            
            # Log response summary
            if self.logger:
                has_list = "list" in data
                list_len = len(data.get("list", [])) if has_list else 0
                self.logger.info(f"OpenWeather AQI response för ({latitude}, {longitude}): has_list={has_list}, list_length={list_len}")
            
            measurement_timestamp = None
            
            if "list" in data and len(data["list"]) > 0:
                aqi_data = data["list"][0]
                
                # Log full response structure for debugging (first time only)
                if self.logger:
                    import json
                    # Log keys in aqi_data
                    aqi_keys = list(aqi_data.keys()) if isinstance(aqi_data, dict) else []
                    self.logger.debug(f"OpenWeather AQI response keys: {aqi_keys}")
                    # Log if components exist
                    has_components = "components" in aqi_data if isinstance(aqi_data, dict) else False
                    self.logger.debug(f"OpenWeather AQI has 'components': {has_components}")
                
                # Extract timestamp if available
                if "dt" in aqi_data:
                    try:
                        # OpenWeather uses Unix timestamp (seconds since epoch)
                        dt_unix = aqi_data["dt"]
                        measurement_timestamp = datetime.fromtimestamp(dt_unix, tz=CET)
                        if self.logger:
                            self.logger.debug(f"OpenWeather: Extraherade measurement timestamp: {measurement_timestamp} (från Unix: {dt_unix})")
                    except (ValueError, TypeError, OSError) as e:
                        if self.logger:
                            self.logger.debug(f"OpenWeather: Kunde inte konvertera Unix timestamp {dt_unix}: {e}")
                
                # Extract raw pollutant values from components field
                pollutants = {
                    "pm25": None,
                    "pm10": None,
                    "no2": None,
                    "o3": None
                }
                
                if "components" in aqi_data:
                    components = aqi_data.get("components", {})
                    if isinstance(components, dict):
                        # Map API field names to our internal names
                        # OpenWeather uses pm2_5, we use pm25
                        pollutants["pm25"] = components.get("pm2_5")
                        pollutants["pm10"] = components.get("pm10")
                        pollutants["no2"] = components.get("no2")
                        pollutants["o3"] = components.get("o3")
                        
                        if self.logger:
                            found = [k for k, v in pollutants.items() if v is not None]
                            if found:
                                self.logger.info(f"OpenWeather: Extraherade rådata från components: {found}")
                                for param, value in pollutants.items():
                                    if value is not None:
                                        self.logger.debug(f"OpenWeather: {param.upper()}={value} µg/m³")
                            else:
                                self.logger.info(f"OpenWeather: 'components' finns men innehåller inga kända pollutant-värden")
                
                if "main" in aqi_data and "aqi" in aqi_data["main"]:
                    # OpenWeather uses 1-5 scale
                    aqi_scale = aqi_data["main"]["aqi"]
                    
                    # NO FALLBACKS - if scale is not 1-5, return None
                    if aqi_scale not in [1, 2, 3, 4, 5]:
                        if self.logger:
                            self.logger.info(f"OpenWeather AQI: Okänd skala {aqi_scale} för ({latitude}, {longitude})")
                        return None
                    
                    if self.logger:
                        category_names = {1: "Good", 2: "Fair", 3: "Moderate", 4: "Poor", 5: "Very Poor"}
                        self.logger.info(f"OpenWeather AQI kategori: {aqi_scale} ({category_names.get(aqi_scale, 'Unknown')}) för ({latitude}, {longitude})")
                    
                    # Return pollutants dict (may contain None values if components missing)
                    # NO FALLBACK - return actual values or None
                    return {
                        "pollutants": pollutants,
                        "measurement_timestamp": measurement_timestamp
                    }
                else:
                    if self.logger:
                        self.logger.info(f"OpenWeather AQI: Saknar 'main.aqi' i response för ({latitude}, {longitude})")
            else:
                if self.logger:
                    self.logger.info(f"OpenWeather AQI: Tom 'list' i response för ({latitude}, {longitude})")
            
            return None
            
        except (KeyError, ValueError, TypeError) as e:
            if self.logger:
                self.logger.info(f"OpenWeather AQI parsing error för ({latitude}, {longitude}): {e}")
            return None
        except Exception as e:
            if self.logger:
                self.logger.info(f"OpenWeather AQI unexpected error för ({latitude}, {longitude}): {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if provider is available."""
        return self._available
