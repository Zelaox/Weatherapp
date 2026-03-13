"""OpenWeatherMap API provider."""

import requests
import time
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Optional, Any, List
from providers.base_provider import WeatherProvider
from utils.logger import WeatherLogger
from utils.rate_limiter import RateLimiter
from utils.unit_conversion import convert_parameter_unit

# CET timezone for all operations
CET = ZoneInfo("Europe/Stockholm")


class OpenWeatherProvider(WeatherProvider):
    """OpenWeatherMap API provider."""
    
    BASE_URL_V2 = "https://api.openweathermap.org/data/2.5"
    BASE_URL_V3 = "https://api.openweathermap.org/data/3.0"
    
    def __init__(self, api_key: str, logger: Optional[WeatherLogger] = None, db_manager: Optional[Any] = None):
        """
        Initialize OpenWeather provider.
        
        Args:
            api_key: OpenWeatherMap API key
            logger: Optional logger instance
            db_manager: Optional DatabaseManager for dynamic parameter discovery
        """
        if not api_key:
            raise ValueError("OpenWeatherMap API key is required")
        
        self.api_key = api_key
        self.logger = logger
        self.db_manager = db_manager
        self._available = True
        self._api_version = None  # Will be detected dynamically
        self._parameter_mappings = {}
        
        # Rate limiter: 60 requests/minute, 2000 requests/hour (conservative)
        # OpenWeather free tier: 60/min, 1M/month (monthly limit is very high)
        self.rate_limiter = RateLimiter(requests_per_minute=60, requests_per_hour=2000)
        
        # Load parameter mappings if db_manager is available
        if self.db_manager:
            self._parameter_mappings = self._load_parameter_mappings()
    
    @property
    def name(self) -> str:
        """Provider name."""
        return "openweather"
    
    def _load_parameter_mappings(self) -> Dict[str, str]:
        """
        Dynamiskt ladda parameter mappings från parameter_registry.
        
        Returns:
            Dict med parameter_name -> openweather_field_name mappings
        """
        mappings = {}
        
        if self.db_manager:
            try:
                conn = self.db_manager.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT parameter_name, provider_mappings 
                    FROM parameter_registry 
                    WHERE provider_mappings IS NOT NULL AND provider_mappings != ''
                """)
                rows = cursor.fetchall()
                
                for row in rows:
                    param_name = row[0]
                    provider_mappings_json = row[1]
                    try:
                        provider_mappings = json.loads(provider_mappings_json)
                        if 'openweather' in provider_mappings:
                            mappings[param_name] = provider_mappings['openweather']
                            if self.logger:
                                self.logger.debug(f"OpenWeather: Laddade mapping {param_name} -> {provider_mappings['openweather']}")
                    except (json.JSONDecodeError, KeyError) as e:
                        if self.logger:
                            self.logger.debug(f"OpenWeather: Kunde inte parsa provider_mappings för {param_name}: {e}")
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"OpenWeather: Kunde inte ladda parameter mappings från databas: {e}")
        
        if self.logger:
            self.logger.debug(f"OpenWeather: Laddade {len(mappings)} parameter mappings")
        
        return mappings
    
    def _detect_api_version(self) -> str:
        """
        Dynamiskt detektera vilken OpenWeather API version som är tillgänglig.
        
        Returns:
            "3.0" om One Call API 3.0 är tillgänglig, annars "2.5"
        """
        if self._api_version is not None:
            return self._api_version
        
        # Test One Call API 3.0 endpoint with minimal request
        test_url = f"{self.BASE_URL_V3}/onecall"
        test_params = {
            "lat": 59.3293,  # Stockholm coordinates for test
            "lon": 18.0686,
            "appid": self.api_key,
            "exclude": "minutely,hourly,daily,alerts"  # Only get current
        }
        
        try:
            if self.logger:
                self.logger.debug("OpenWeather: Testar One Call API 3.0 access...")
            
            response = requests.get(test_url, params=test_params, timeout=5)
            
            if response.status_code == 200:
                self._api_version = "3.0"
                if self.logger:
                    self.logger.info("OpenWeather: One Call API 3.0 är tillgänglig")
                return "3.0"
            elif response.status_code in [401, 403]:
                self._api_version = "2.5"
                if self.logger:
                    self.logger.info("OpenWeather: One Call API 3.0 inte tillgänglig, använder API 2.5")
                return "2.5"
            else:
                # Other error, default to 2.5
                self._api_version = "2.5"
                if self.logger:
                    self.logger.warning(f"OpenWeather: One Call API 3.0 test returnerade {response.status_code}, använder API 2.5")
                return "2.5"
        except Exception as e:
            # On error, default to 2.5
            self._api_version = "2.5"
            if self.logger:
                self.logger.debug(f"OpenWeather: Kunde inte testa One Call API 3.0: {e}, använder API 2.5")
            return "2.5"
    
    def _get_parameters_from_registry(self, categories: List[str]) -> List[str]:
        """
        Dynamiskt hämta parametrar från parameter_registry baserat på kategorier.
        
        Args:
            categories: Lista av kategorier att hämta (t.ex. ['weather', 'solar', 'storm'])
        
        Returns:
            Lista av parameter_names som finns i databas och har OpenWeather mappings
        """
        if not self.db_manager:
            return []
        
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            # Build query with placeholders
            placeholders = ','.join(['?' for _ in categories])
            param_placeholders = ','.join(['?' for _ in self._parameter_mappings.keys()]) if self._parameter_mappings else '?'
            param_values = list(categories)
            if self._parameter_mappings:
                param_values.extend(list(self._parameter_mappings.keys()))
            
            cursor.execute(f"""
                SELECT DISTINCT parameter_name 
                FROM parameter_registry 
                WHERE category IN ({placeholders})
                AND parameter_name IN ({param_placeholders})
            """, param_values)
            
            rows = cursor.fetchall()
            param_names = [row[0] for row in rows]
            
            if self.logger:
                self.logger.debug(f"OpenWeather: Hittade {len(param_names)} parametrar från registry för kategorier {categories}")
            
            return param_names
        except Exception as e:
            if self.logger:
                self.logger.debug(f"OpenWeather: Kunde inte hämta parametrar från registry: {e}")
            return []
    
    def get_current_weather(self, latitude: float, longitude: float) -> Optional[Dict]:
        """Get current weather data."""
        try:
            # Dynamiskt detektera API version
            api_version = self._detect_api_version()
            
            if api_version == "3.0":
                # Use One Call API 3.0
                return self._get_current_weather_v3(latitude, longitude)
            else:
                # Use API 2.5 (existing implementation)
                return self._get_current_weather_v2(latitude, longitude)
        except Exception as e:
            if self.logger:
                self.logger.error(f"OpenWeather oväntat fel i get_current_weather: {e}")
            return None
    
    def _get_current_weather_v2(self, latitude: float, longitude: float) -> Optional[Dict]:
        """Get current weather data using API 2.5."""
        try:
            url = f"{self.BASE_URL_V2}/weather"
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
            
            # Explicit handling for invalid API key
            if response.status_code == 401:
                if self.logger:
                    self.logger.error(
                        "OpenWeather: 401 Unauthorized från /weather. "
                        "Kontrollera API-nyckeln i config.json och att kontot är aktiverat."
                    )
                # Mark provider as unavailable to avoid repeated failing calls
                self._available = False
                return None

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
            
            # Convert wind speed to databasenhet via central unit converter
            wind_speed_raw = wind.get("speed", 0)
            wind_speed_converted = None
            try:
                if self.db_manager is not None and wind_speed_raw is not None:
                    wind_speed_converted = convert_parameter_unit(
                        self.db_manager,
                        "wind_speed",
                        float(wind_speed_raw),
                        self.name,
                        logger=self.logger,
                    )
                else:
                    wind_speed_converted = float(wind_speed_raw)
            except Exception as e:
                if self.logger:
                    self.logger.warning(
                        f"OpenWeather: Kunde inte konvertera wind_speed-värde {wind_speed_raw} "
                        f"för ({latitude}, {longitude}): {e}"
                    )
                wind_speed_converted = None

            if self.logger and wind_speed_converted is not None:
                self.logger.debug(
                    f"[UNITS] OpenWeather: wind.speed raw={wind_speed_raw} -> stored wind_speed={wind_speed_converted:.2f} "
                    f"(provider={self.name})"
                )

            result = {
                "temperature": float(main.get("temp", 0)),
                "humidity": float(main.get("humidity", 0)),
                "wind_speed": wind_speed_converted,
                "aqi": aqi,
                "timestamp": timestamp,
                "measurement_timestamp": measurement_timestamp,  # Include for controller
                "source": self.name
            }
            
            if self.logger:
                self.logger.debug(f"OpenWeather: Retrieved weather for ({latitude}, {longitude}) via API 2.5")
            
            return result
            
        except (KeyError, ValueError, TypeError) as e:
            if self.logger:
                self.logger.error(f"OpenWeather parsing error: {e}")
            return None
        except Exception as e:
            if self.logger:
                self.logger.error(f"OpenWeather oväntat fel: {e}")
            return None
    
    def _get_current_weather_v3(self, latitude: float, longitude: float) -> Optional[Dict]:
        """Get current weather data using One Call API 3.0."""
        try:
            # Dynamiskt hämta parametrar från parameter_registry
            weather_params = self._get_parameters_from_registry(['weather'])
            solar_params = self._get_parameters_from_registry(['solar'])
            
            # Build exclude parameter based on what we don't need
            # One Call API 3.0 returns current, minutely, hourly, daily, alerts
            # We only need current for get_current_weather
            exclude_params = ['minutely', 'hourly', 'daily', 'alerts']
            
            url = f"{self.BASE_URL_V3}/onecall"
            params = {
                "lat": latitude,
                "lon": longitude,
                "appid": self.api_key,
                "units": "metric",
                "exclude": ','.join(exclude_params)
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
            
            # Explicit handling for invalid API key
            if response.status_code == 401:
                if self.logger:
                    self.logger.error(
                        "OpenWeather: 401 Unauthorized från One Call API 3.0. "
                        "Kontrollera API-nyckeln i config.json och att kontot har access till One Call API 3.0."
                    )
                # Mark provider as unavailable to avoid repeated failing calls
                self._available = False
                return None
            
            response.raise_for_status()
            data = response.json()
            
            if "current" not in data:
                return None
            
            current = data["current"]
            
            # Extract timestamp
            measurement_timestamp = None
            if "dt" in current:
                try:
                    dt_unix = current["dt"]
                    measurement_timestamp = datetime.fromtimestamp(dt_unix, tz=CET)
                except (ValueError, TypeError, OSError):
                    pass
            
            timestamp = measurement_timestamp if measurement_timestamp else datetime.now(CET)
            
            # Dynamiskt mappa parametrar från One Call API 3.0 response
            result = {
                "temperature": None,
                "humidity": None,
                "wind_speed": None,
                "timestamp": timestamp,
                "measurement_timestamp": measurement_timestamp,
                "source": self.name
            }
            
            # Map weather parameters
            if 'temperature' in self._parameter_mappings:
                api_field = self._parameter_mappings['temperature']
                if api_field == 'temp' and 'temp' in current:
                    result["temperature"] = float(current["temp"])
            
            if 'humidity' in self._parameter_mappings:
                api_field = self._parameter_mappings['humidity']
                if api_field == 'humidity' and 'humidity' in current:
                    result["humidity"] = float(current["humidity"])
            
            if 'wind_speed' in self._parameter_mappings:
                api_field = self._parameter_mappings['wind_speed']
                if api_field == 'wind_speed' and 'wind_speed' in current:
                    result["wind_speed"] = float(current["wind_speed"])
            
            # Map solar parameters
            if 'uv_index' in self._parameter_mappings:
                api_field = self._parameter_mappings['uv_index']
                if api_field == 'uvi' and 'uvi' in current:
                    result["uv_index"] = float(current["uvi"])
            
            # Get air quality separately (One Call API 3.0 doesn't include it in current)
            air_quality_result = self.get_air_quality(latitude, longitude)
            if air_quality_result:
                pollutants = air_quality_result.get("pollutants", {})
                result["pm25"] = pollutants.get("pm25")
                result["pm10"] = pollutants.get("pm10")
                result["no2"] = pollutants.get("no2")
                result["o3"] = pollutants.get("o3")
            
            if self.logger:
                self.logger.debug(f"OpenWeather: Retrieved weather for ({latitude}, {longitude}) via One Call API 3.0")
            
            return result
            
        except (KeyError, ValueError, TypeError) as e:
            if self.logger:
                self.logger.error(f"OpenWeather One Call API 3.0 parsing error: {e}")
            return None
        except Exception as e:
            if self.logger:
                self.logger.error(f"OpenWeather One Call API 3.0 oväntat fel: {e}")
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
                status_code = None
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    try:
                        error_data = e.response.json()
                        error_details = f" - {error_data.get('message', str(error_data)[:200])}"
                    except Exception:
                        error_details = f" - Status {status_code}"
                if self.logger:
                    self.logger.info(f"OpenWeather AQI request error för ({latitude}, {longitude}): {e}{error_details}")
                    if status_code == 401:
                        self.logger.error(
                            "OpenWeather: 401 Unauthorized från /air_pollution. "
                            "Kontrollera API-nyckeln i config.json och att kontot är aktiverat."
                        )
                # If 401, mark provider unavailable to avoid hammering invalid key
                if status_code == 401:
                    self._available = False
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
