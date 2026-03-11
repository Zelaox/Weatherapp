"""Open-Meteo weather API provider."""

import requests
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Optional, Any, List
from providers.base_provider import WeatherProvider
from utils.logger import WeatherLogger

# CET timezone for all operations
CET = ZoneInfo("Europe/Stockholm")


class OpenMeteoProvider(WeatherProvider):
    """Open-Meteo API provider (no API key required)."""
    
    BASE_URL = "https://api.open-meteo.com/v1"
    
    # Known parameter mappings for Open-Meteo (dynamically loaded from parameter_registry if available)
    # These are fallback mappings if parameter_registry is not available
    PARAMETER_MAPPINGS = {
        'temperature': 'temperature_2m',
        'humidity': 'relative_humidity_2m',
        'wind_speed': 'wind_speed_10m',
        'solar_radiation': 'shortwave_radiation',
        'uv_index': 'uv_index',
        'direct_radiation': 'direct_radiation',
        'diffuse_radiation': 'diffuse_radiation',
        'sunshine_duration': 'sunshine_duration',
        'cape': 'cape',
        'precipitation_probability': 'precipitation_probability',
        'convective_precipitation': 'convective_precipitation'
    }
    
    def __init__(self, logger: Optional[WeatherLogger] = None, db_manager: Optional[Any] = None):
        """
        Initialize Open-Meteo provider.
        
        Args:
            logger: Optional logger instance
            db_manager: Optional DatabaseManager for dynamic parameter discovery
        """
        self.logger = logger
        self.db_manager = db_manager
        self._available = True
        self._parameter_mappings = self._load_parameter_mappings()
    
    @property
    def name(self) -> str:
        """Provider name."""
        return "openmeteo"
    
    def _load_parameter_mappings(self) -> Dict[str, str]:
        """
        Dynamiskt ladda parameter mappings från parameter_registry.
        
        Returns:
            Dict med parameter_name -> openmeteo_field_name mappings
        """
        mappings = {}
        
        if self.db_manager:
            try:
                # Query parameter_registry för provider_mappings
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
                        if 'openmeteo' in provider_mappings:
                            mappings[param_name] = provider_mappings['openmeteo']
                            if self.logger:
                                self.logger.debug(f"Open-Meteo: Laddade mapping {param_name} -> {provider_mappings['openmeteo']}")
                    except (json.JSONDecodeError, KeyError) as e:
                        if self.logger:
                            self.logger.debug(f"Open-Meteo: Kunde inte parsa provider_mappings för {param_name}: {e}")
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"Open-Meteo: Kunde inte ladda parameter mappings från databas: {e}")
        
        # Merge with fallback mappings (use fallback if not in database)
        for param, api_field in self.PARAMETER_MAPPINGS.items():
            if param not in mappings:
                mappings[param] = api_field
        
        if self.logger:
            self.logger.debug(f"Open-Meteo: Laddade {len(mappings)} parameter mappings")
        
        return mappings
    
    def _get_parameters_from_registry(self, categories: List[str]) -> List[str]:
        """
        Dynamiskt hämta parametrar från parameter_registry baserat på kategorier.
        
        Args:
            categories: Lista av kategorier att hämta (t.ex. ['weather', 'solar', 'storm'])
        
        Returns:
            Lista av parameter_names som finns i databas och har Open-Meteo mappings
        """
        if not self.db_manager:
            return []
        
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            # Build query with placeholders
            placeholders = ','.join(['?' for _ in categories])
            cursor.execute(f"""
                SELECT DISTINCT parameter_name 
                FROM parameter_registry 
                WHERE category IN ({placeholders})
                AND parameter_name IN ({','.join(['?' for _ in self._parameter_mappings.keys()])})
            """, list(categories) + list(self._parameter_mappings.keys()))
            
            rows = cursor.fetchall()
            param_names = [row[0] for row in rows]
            
            if self.logger:
                self.logger.debug(f"Open-Meteo: Hittade {len(param_names)} parametrar från registry för kategorier {categories}")
            
            return param_names
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Open-Meteo: Kunde inte hämta parametrar från registry: {e}")
            return []
    
    def _build_parameter_string(self, parameters: List[str], endpoint: str) -> str:
        """
        Bygg parameter-sträng dynamiskt baserat på Open-Meteo format.
        
        Args:
            parameters: Lista av parameter_names från databas
            endpoint: 'current' eller 'hourly'
        
        Returns:
            Komma-separerad sträng av Open-Meteo fält-namn
        """
        api_fields = []
        for param in parameters:
            if param in self._parameter_mappings:
                api_field = self._parameter_mappings[param]
                api_fields.append(api_field)
                if self.logger:
                    self.logger.debug(f"Open-Meteo: Mappade {param} -> {api_field} för {endpoint}")
            else:
                if self.logger:
                    self.logger.debug(f"Open-Meteo: Ingen mapping för {param}, hoppar över")
        
        result = ','.join(api_fields)
        if self.logger:
            self.logger.debug(f"Open-Meteo: Byggde parameter-sträng för {endpoint}: {result}")
        return result
    
    def _handle_400_error(self, response: requests.Response, requested_params: List[str]) -> List[str]:
        """
        Parse 400 error response och returnera lista av giltiga parametrar.
        
        Args:
            response: HTTP response med 400 status
            requested_params: Lista av parametrar som skickades i request
        
        Returns:
            Lista av parametrar som INTE orsakade felet (kan vara tom om alla orsakade fel)
        """
        valid_params = requested_params.copy()
        
        try:
            error_text = response.text
            if self.logger:
                self.logger.warning(f"Open-Meteo 400-fel response: {error_text[:500]}")
            
            # Try to parse error response for specific parameter names
            # Open-Meteo may return error with parameter names mentioned
            # For now, we'll use a conservative approach: if 400, try removing parameters one by one
            # This is a simplified version - in production, you'd parse the actual error message
            
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Open-Meteo: Kunde inte parsa 400-fel response: {e}")
        
        return valid_params
    
    def _discover_available_parameters(self, endpoint: str, db_manager: Optional[Any] = None) -> List[str]:
        """
        Dynamiskt upptäcka vilka parametrar som finns i Open-Meteo endpoint.
        
        Args:
            endpoint: 'current' eller 'hourly'
            db_manager: DatabaseManager för att query parameter_registry
        
        Returns:
            Lista av parameter_names som finns i både databas OCH API endpoint
        """
        # Determine which categories to query based on endpoint
        if endpoint == 'current':
            categories = ['weather', 'solar']
        elif endpoint == 'hourly':
            categories = ['storm']
        else:
            return []
        
        # Get parameters from registry
        if db_manager:
            self.db_manager = db_manager
            self._parameter_mappings = self._load_parameter_mappings()
        
        params = self._get_parameters_from_registry(categories)
        
        if self.logger:
            self.logger.debug(f"Open-Meteo: Upptäckte {len(params)} tillgängliga parametrar för {endpoint} endpoint")
        
        return params
    
    def get_current_weather(self, latitude: float, longitude: float) -> Optional[Dict]:
        """Get current weather data."""
        try:
            weather_url = f"{self.BASE_URL}/forecast"
            
            # Dynamiskt hämta parametrar från parameter_registry för current endpoint
            current_param_names = self._discover_available_parameters('current')
            if self.logger:
                self.logger.debug(f"Open-Meteo: _discover_available_parameters('current') returnerade: {current_param_names}")
            
            if not current_param_names:
                # Fallback: använd grundläggande parametrar om registry inte är tillgänglig
                current_param_names = ['temperature', 'humidity', 'wind_speed', 'solar_radiation', 'uv_index', 
                                     'direct_radiation', 'diffuse_radiation', 'sunshine_duration']
                if self.logger:
                    self.logger.info(f"Open-Meteo: Använder fallback-parametrar för current endpoint: {current_param_names}")
            else:
                # Ensure solar parameters are included even if not in registry
                solar_params = ['solar_radiation', 'uv_index', 'direct_radiation', 'diffuse_radiation', 'sunshine_duration']
                for param in solar_params:
                    if param not in current_param_names:
                        current_param_names.append(param)
                        if self.logger:
                            self.logger.debug(f"Open-Meteo: Lade till solar-parameter {param} till current_param_names")
            
            # Bygg parameter-sträng dynamiskt
            current_param_string = self._build_parameter_string(current_param_names, 'current')
            
            if self.logger:
                self.logger.debug(f"Open-Meteo: Byggde parameter-sträng för current: '{current_param_string}' från {len(current_param_names)} parametrar")
            
            if not current_param_string:
                if self.logger:
                    self.logger.warning(f"Open-Meteo: Inga parametrar att hämta för current endpoint (param_names={current_param_names}, mappings={self._parameter_mappings})")
                return None
            
            # Request 1: Basic weather and solar parameters (current endpoint)
            current_params = {
                "latitude": latitude,
                "longitude": longitude,
                "current": current_param_string,
                "timezone": "auto",
            }
            
            if self.logger:
                self.logger.debug(f"Open-Meteo: Hämtar {len(current_param_names)} parametrar från current endpoint: {current_param_string}")
            
            if self.logger:
                self.logger.debug(f"Open-Meteo: Hämtar grundläggande väderdata från current endpoint för ({latitude}, {longitude})")
            
            try:
                if self.logger:
                    self.logger.debug(f"Open-Meteo: Gör request till {weather_url} med params: {current_params}")
                response = requests.get(weather_url, params=current_params, timeout=10)
                if self.logger:
                    self.logger.debug(f"Open-Meteo response status: {response.status_code}")
                response.raise_for_status()
                data = response.json()
                
                # Log what we got from API
                if self.logger and "current" in data:
                    current_data = data["current"]
                    solar_vals = {
                        'solar_radiation': current_data.get('shortwave_radiation'),
                        'uv_index': current_data.get('uv_index'),
                        'direct_radiation': current_data.get('direct_radiation'),
                        'diffuse_radiation': current_data.get('diffuse_radiation'),
                        'sunshine_duration': current_data.get('sunshine_duration')
                    }
                    non_none_solar = {k: v for k, v in solar_vals.items() if v is not None}
                    if non_none_solar:
                        self.logger.info(f"Open-Meteo: Fick solar-data från API: {non_none_solar}")
                    else:
                        self.logger.warning(f"Open-Meteo: Inga solar-värden i API response (alla None): {solar_vals}")
            except requests.exceptions.HTTPError as e:
                if response.status_code == 400:
                    # Log response body for debugging
                    try:
                        error_body = response.text[:500]  # First 500 chars
                        if self.logger:
                            self.logger.error(f"Open-Meteo 400 Bad Request: {error_body}")
                    except:
                        pass
                if self.logger:
                    self.logger.warning(f"Open-Meteo HTTP-fel: {e}")
                return None
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
            
            # Request 2: Advanced storm parameters (hourly endpoint, take first hour)
            # Dynamiskt hämta parametrar från parameter_registry för hourly endpoint
            hourly_param_names = self._discover_available_parameters('hourly')
            if self.logger:
                self.logger.debug(f"Open-Meteo: _discover_available_parameters('hourly') returnerade: {hourly_param_names}")
            
            # Initialize storm parameters as None
            storm_params = {}
            for param in ['cape', 'precipitation_probability', 'convective_precipitation']:
                storm_params[param] = None
            
            # Fallback: använd storm-parametrar om registry inte är tillgänglig
            if not hourly_param_names:
                hourly_param_names = ['cape', 'precipitation_probability', 'convective_precipitation']
                if self.logger:
                    self.logger.info(f"Open-Meteo: Använder fallback-parametrar för hourly endpoint: {hourly_param_names}")
            else:
                # Ensure all storm parameters are included even if not in registry
                storm_fallback = ['cape', 'precipitation_probability', 'convective_precipitation']
                for param in storm_fallback:
                    if param not in hourly_param_names:
                        hourly_param_names.append(param)
                        if self.logger:
                            self.logger.debug(f"Open-Meteo: Lade till storm-parameter {param} till hourly_param_names")
            
            if hourly_param_names:
                # Bygg parameter-sträng dynamiskt
                hourly_param_string = self._build_parameter_string(hourly_param_names, 'hourly')
                
                if self.logger:
                    self.logger.debug(f"Open-Meteo: Byggde parameter-sträng för hourly: '{hourly_param_string}' från {len(hourly_param_names)} parametrar")
                
                if hourly_param_string:
                    hourly_params = {
                        "latitude": latitude,
                        "longitude": longitude,
                        "hourly": hourly_param_string,
                        "timezone": "auto",
                    }
                    
                    if self.logger:
                        self.logger.debug(f"Open-Meteo: Hämtar {len(hourly_param_names)} storm-parametrar från hourly endpoint: {hourly_param_string}")
                    
                    try:
                        if self.logger:
                            self.logger.debug(f"Open-Meteo: Gör hourly request till {weather_url} med params: {hourly_params}")
                        hourly_response = requests.get(weather_url, params=hourly_params, timeout=10)
                        
                        if self.logger:
                            self.logger.debug(f"Open-Meteo hourly response status: {hourly_response.status_code}")
                        
                        if hourly_response.status_code == 400:
                            # Handle 400 error dynamically
                            try:
                                error_body = hourly_response.text[:500]
                                if self.logger:
                                    self.logger.warning(f"Open-Meteo hourly 400 Bad Request: {error_body}")
                                
                                # Try to remove problematic parameters and retry
                                # For now, we'll skip hourly if 400 (conservative approach)
                                if self.logger:
                                    self.logger.debug("Open-Meteo: Skippar hourly request p.g.a. 400-fel, fortsätter med current data")
                            except:
                                pass
                        else:
                            hourly_response.raise_for_status()
                            hourly_data = hourly_response.json()
                            
                            if "hourly" in hourly_data and "time" in hourly_data["hourly"]:
                                hourly = hourly_data["hourly"]
                                times = hourly.get("time", [])
                                if times:
                                    if self.logger:
                                        self.logger.debug(f"Open-Meteo: Hourly data har {len(times)} tidsstämplar, använder första: {times[0] if times else 'N/A'}")
                                    
                                    # Dynamiskt extrahera värden baserat på vilka parametrar som finns
                                    for param_name in hourly_param_names:
                                        if param_name in self._parameter_mappings:
                                            api_field = self._parameter_mappings[param_name]
                                            param_vals = hourly.get(api_field, [])
                                            if param_vals and len(param_vals) > 0:
                                                storm_params[param_name] = param_vals[0]
                                                if self.logger:
                                                    self.logger.debug(f"Open-Meteo: Extraherade {param_name}={param_vals[0]} från hourly[{api_field}]")
                                            else:
                                                if self.logger:
                                                    self.logger.debug(f"Open-Meteo: Ingen data för {param_name} (api_field={api_field}, param_vals={param_vals})")
                                    
                                    if self.logger:
                                        retrieved = {k: v for k, v in storm_params.items() if v is not None}
                                        missing = {k: v for k, v in storm_params.items() if v is None}
                                        if retrieved:
                                            self.logger.info(f"Open-Meteo: Fick storm-parametrar från hourly: {retrieved}")
                                        if missing:
                                            self.logger.warning(f"Open-Meteo: Saknade storm-parametrar från hourly: {missing}")
                                else:
                                    if self.logger:
                                        self.logger.warning(f"Open-Meteo: Hourly data saknar 'time' array eller den är tom")
                            else:
                                if self.logger:
                                    self.logger.warning(f"Open-Meteo: Hourly response saknar 'hourly' eller 'time' key")
                    except requests.exceptions.HTTPError as e:
                        # Continue with current data even if hourly fails
                        if self.logger:
                            self.logger.debug(f"Open-Meteo hourly request misslyckades, fortsätter med current data: {e}")
                    except Exception as e:
                        # Continue with current data even if hourly fails
                        if self.logger:
                            self.logger.debug(f"Open-Meteo hourly request misslyckades, fortsätter med current data: {e}")
                else:
                    if self.logger:
                        self.logger.debug("Open-Meteo: Ingen hourly parameter-sträng kunde byggas")
            else:
                if self.logger:
                    self.logger.debug("Open-Meteo: Inga storm-parametrar hittades i registry för hourly endpoint")
            
            # Extract storm parameters from dict
            cape = storm_params.get('cape')
            precip_prob = storm_params.get('precipitation_probability')
            conv_precip = storm_params.get('convective_precipitation')
            
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
            
            # Basic weather
            temperature = current.get("temperature_2m")
            humidity_val = current.get("relative_humidity_2m")
            wind_speed_val = current.get("wind_speed_10m")
            
            # Log raw wind_speed_10m value from API for debugging
            if self.logger:
                if wind_speed_val is not None:
                    self.logger.debug(
                        f"Open-Meteo: Råa wind_speed_10m från API för ({latitude:.4f}, {longitude:.4f}): {wind_speed_val} m/s"
                    )
                    # Log warning if value is unusually high (>20 m/s)
                    if float(wind_speed_val) > 20.0:
                        self.logger.warning(
                            f"Open-Meteo: Ovanligt högt wind_speed_10m-värde från API: {wind_speed_val} m/s "
                            f"för ({latitude:.4f}, {longitude:.4f})"
                        )
                else:
                    self.logger.debug(
                        f"Open-Meteo: wind_speed_10m är None från API för ({latitude:.4f}, {longitude:.4f})"
                    )

            # Solar parameters
            solar_radiation = current.get("shortwave_radiation")
            uv_index = current.get("uv_index")
            direct_radiation = current.get("direct_radiation")
            diffuse_radiation = current.get("diffuse_radiation")
            sunshine_duration = current.get("sunshine_duration")
            
            if self.logger:
                solar_extracted = {
                    'solar_radiation': solar_radiation,
                    'uv_index': uv_index,
                    'direct_radiation': direct_radiation,
                    'diffuse_radiation': diffuse_radiation,
                    'sunshine_duration': sunshine_duration
                }
                non_none_solar = {k: v for k, v in solar_extracted.items() if v is not None}
                if non_none_solar:
                    self.logger.info(f"Open-Meteo: Extraherade solar-parametrar från current: {non_none_solar}")
                else:
                    self.logger.warning(f"Open-Meteo: Alla solar-parametrar är None från current: {solar_extracted}")

            # Storm parameters (from hourly request, already extracted above)
            # cape, precip_prob, conv_precip are set from hourly request

            # Convert wind_speed_val to float and log the converted value
            wind_speed_converted = float(wind_speed_val) if wind_speed_val is not None else None
            if self.logger and wind_speed_converted is not None:
                self.logger.debug(
                    f"Open-Meteo: Konverterat wind_speed-värde för ({latitude:.4f}, {longitude:.4f}): "
                    f"{wind_speed_converted:.2f} m/s (från wind_speed_10m={wind_speed_val})"
                )
            
            result = {
                "temperature": float(temperature) if temperature is not None else None,
                "humidity": float(humidity_val) if humidity_val is not None else None,
                "wind_speed": wind_speed_converted,
                "pm25": pollutants.get("pm25") if pollutants else None,
                "pm10": pollutants.get("pm10") if pollutants else None,
                "no2": pollutants.get("no2") if pollutants else None,
                "o3": pollutants.get("o3") if pollutants else None,
                "timestamp": timestamp,
                "measurement_timestamp": measurement_timestamp,  # Include for controller
                "source": self.name,
                # Solar / storm analytics inputs
                "solar_radiation": float(solar_radiation) if solar_radiation is not None else None,
                "uv_index": float(uv_index) if uv_index is not None else None,
                "direct_radiation": float(direct_radiation) if direct_radiation is not None else None,
                "diffuse_radiation": float(diffuse_radiation) if diffuse_radiation is not None else None,
                "sunshine_duration": float(sunshine_duration) if sunshine_duration is not None else None,
                "cape": float(cape) if cape is not None else None,
                "precipitation_probability": float(precip_prob) if precip_prob is not None else None,
                "convective_precipitation": float(conv_precip) if conv_precip is not None else None,
            }
            
            if self.logger:
                temp_val = result["temperature"] if result["temperature"] is not None else float("nan")
                hum_val = result["humidity"] if result["humidity"] is not None else float("nan")
                wind_val = result["wind_speed"] if result["wind_speed"] is not None else float("nan")
                solar_val = result['solar_radiation'] if result['solar_radiation'] is not None else None
                uv_val = result['uv_index'] if result['uv_index'] is not None else None
                cape_val = result['cape'] if result['cape'] is not None else None
                
                self.logger.info(
                    f"Open-Meteo: Retrieved weather for ({latitude:.4f}, {longitude:.4f}) - "
                    f"temp={temp_val:.2f}°C, hum={hum_val:.1f}%, wind={wind_val:.2f}m/s, "
                    f"solar={solar_val}W/m², uv={uv_val}, cape={cape_val}J/kg"
                )
                
                # Log summary of what we got
                has_solar = any(v is not None for v in [result['solar_radiation'], result['uv_index'], 
                                                         result['direct_radiation'], result['diffuse_radiation'], 
                                                         result['sunshine_duration']])
                has_storm = any(v is not None for v in [result['cape'], result['precipitation_probability'], 
                                                        result['convective_precipitation']])
                
                if not has_solar:
                    self.logger.warning(f"Open-Meteo: ⚠️ Inga solar-parametrar hämtades för ({latitude:.4f}, {longitude:.4f})")
                if not has_storm:
                    self.logger.warning(f"Open-Meteo: ⚠️ Inga storm-parametrar hämtades för ({latitude:.4f}, {longitude:.4f})")
            
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
