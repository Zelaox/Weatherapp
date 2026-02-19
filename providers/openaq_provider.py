"""OpenAQ API provider for air quality data."""

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


class OpenAQProvider(WeatherProvider):
    """OpenAQ API provider (specialized for air quality)."""
    
    BASE_URL = "https://api.openaq.org/v3"
    
    def __init__(self, api_key: str, logger: Optional[WeatherLogger] = None):
        """
        Initialize OpenAQ provider.
        
        Args:
            api_key: OpenAQ API key
            logger: Optional logger instance
        """
        if not api_key:
            raise ValueError("OpenAQ API key is required")
        
        self.api_key = api_key
        self.logger = logger
        self._available = True
        self._headers = {
            "X-API-Key": api_key
        }
        
        # Rate limiter: 60 requests/minute, 2000 requests/hour
        self.rate_limiter = RateLimiter(requests_per_minute=60, requests_per_hour=2000)
        
        # Cache for sensor parameter mappings to reduce API calls
        self._sensor_cache = {}
    
    @property
    def name(self) -> str:
        """Provider name."""
        return "openaq"
    
    def get_current_weather(self, latitude: float, longitude: float) -> Optional[Dict]:
        """
        Get current weather data.
        Note: OpenAQ primarily provides air quality data, not weather.
        """
        # OpenAQ doesn't provide temperature/humidity/wind
        # Return None to indicate we only provide air quality
        air_quality_result = self.get_air_quality(latitude, longitude)
        
        if air_quality_result is not None:
            pollutants = air_quality_result.get("pollutants", {})
            measurement_timestamp = air_quality_result.get("measurement_timestamp")
            
            # Use measurement timestamp if available, otherwise use collector timestamp
            timestamp = measurement_timestamp if measurement_timestamp else datetime.now(CET)
            
            # Return minimal structure with pollutant values
            return {
                "temperature": None,
                "humidity": None,
                "wind_speed": None,
                "pm25": pollutants.get("pm25"),
                "pm10": pollutants.get("pm10"),
                "no2": pollutants.get("no2"),
                "o3": pollutants.get("o3"),
                "timestamp": timestamp,
                "measurement_timestamp": measurement_timestamp,  # Include for controller
                "source": self.name
            }
        
        return None
    
    def get_air_quality(self, latitude: float, longitude: float) -> Optional[Dict[str, Any]]:
        """
        Get raw pollutant values from nearest station.
        
        OpenAQ API v3 structure:
        1. Search for locations near coordinates
        2. Get location ID
        3. Get latest measurements from that location using /v3/locations/{id}/latest
        
        Returns:
            Dictionary with:
            - "pollutants": Dict with pm25, pm10, no2, o3 (all in µg/m³)
            - "measurement_timestamp": datetime or None (measurement timestamp from API)
            Returns None if no data
        """
        try:
            # Step 1: Search for locations near coordinates
            # OpenAQ v3 locations endpoint with coordinates search
            locations_url = f"{self.BASE_URL}/locations"
            
            # Try different parameter formats that OpenAQ might accept
            # Format 1: coordinates as "lat,lon"
            params1 = {
                "coordinates": f"{latitude},{longitude}",
                "radius": 10000,  # 10km in meters
                "limit": 1
            }
            
            if self.logger:
                self.logger.info(f"OpenAQ: Söker locations för ({latitude}, {longitude}) med params: {params1}")
            
            response = None
            data = None
            
            try:
                response = requests.get(
                    locations_url,
                    params=params1,
                    headers=self._headers,
                    timeout=10
                )
                
                if self.logger:
                    self.logger.info(f"OpenAQ: Location lookup response status: {response.status_code}")
                
                # If 422, try alternative format
                if response.status_code == 422:
                    # Format 2: separate lat/lon parameters
                    params2 = {
                        "lat": latitude,
                        "lon": longitude,
                        "radius": 10000,
                        "limit": 1
                    }
                    if self.logger:
                        self.logger.info(f"OpenAQ: Försöker alternativ format med params: {params2}")
                    
                    # Check rate limits before retry
                    if self.rate_limiter.should_wait():
                        wait_time = self.rate_limiter.wait_if_needed()
                        if wait_time > 0 and self.logger:
                            self.logger.info(f"OpenAQ: Väntade {wait_time:.1f}s för rate limit (retry)")
                    
                    response = requests.get(
                        locations_url,
                        params=params2,
                        headers=self._headers,
                        timeout=10
                    )
                    
                    # Update rate limiter
                    self.rate_limiter.update_from_headers(response.headers)
                    self.rate_limiter.record_request()
                    
                    if self.logger:
                        self.logger.info(f"OpenAQ: Alternativ format response status: {response.status_code}")
                    
                    # Handle 429 on retry
                    if response.status_code == 429:
                        retry_after = response.headers.get('Retry-After')
                        wait_time = 60
                        if retry_after:
                            try:
                                wait_time = int(retry_after)
                            except (ValueError, TypeError):
                                pass
                        if self.logger:
                            self.logger.warning(f"OpenAQ: Rate limit nådd vid retry (429). Väntar {wait_time}s...")
                        time.sleep(wait_time)
                        return None  # Give up after retry
                
                # Handle known error codes
                if response.status_code in [410, 404, 422]:
                    error_msg = ""
                    try:
                        error_data = response.json()
                        error_msg = f" - {error_data.get('message', '')}" if isinstance(error_data, dict) else ""
                    except:
                        pass
                    if self.logger:
                        self.logger.info(f"OpenAQ: Kunde inte hitta location för ({latitude}, {longitude}) - status {response.status_code}{error_msg}")
                    return None
                
                response.raise_for_status()
                data = response.json()
                
            except requests.exceptions.HTTPError as e:
                if e.response and e.response.status_code in [410, 404, 422]:
                    error_msg = ""
                    try:
                        error_data = e.response.json()
                        error_msg = f" - {error_data.get('message', '')}" if isinstance(error_data, dict) else ""
                    except:
                        pass
                    if self.logger:
                        self.logger.info(f"OpenAQ: Location lookup misslyckades ({e.response.status_code}){error_msg}")
                    return None
                if self.logger:
                    self.logger.info(f"OpenAQ HTTP-fel vid location lookup: {e}")
                return None
            except requests.exceptions.Timeout:
                if self.logger:
                    self.logger.info(f"OpenAQ timeout för ({latitude}, {longitude})")
                return None
            except requests.exceptions.ConnectionError as e:
                if self.logger:
                    self.logger.info(f"OpenAQ anslutningsfel: {e}")
                return None
            except requests.exceptions.RequestException as e:
                if self.logger:
                    self.logger.info(f"OpenAQ request-fel: {e}")
                return None
            
            # Parse location response
            if not data:
                return None
            
            # Response structure: {"results": [{"id": 2178, ...}, ...]}
            results = data.get("results", [])
            if not results or len(results) == 0:
                if self.logger:
                    self.logger.info(f"OpenAQ: Inga locations hittades nära ({latitude}, {longitude})")
                return None
            
            location = results[0]
            location_id = location.get("id")
            
            if not location_id:
                if self.logger:
                    self.logger.info("OpenAQ: Location saknar ID")
                return None
            
            # Store location coordinates for sensor data
            location_coords = None
            if "coordinates" in location:
                coords = location.get("coordinates")
                if isinstance(coords, dict):
                    location_coords = {
                        "latitude": coords.get("latitude"),
                        "longitude": coords.get("longitude")
                    }
                else:
                    # Try alternative format
                    location_coords = {
                        "latitude": location.get("latitude"),
                        "longitude": location.get("longitude")
                    }
            else:
                # Fallback to location-level coordinates
                location_coords = {
                    "latitude": location.get("latitude"),
                    "longitude": location.get("longitude")
                }
            
            if self.logger:
                self.logger.info(f"OpenAQ: Hittade location {location_id} för ({latitude}, {longitude})")
            
            # Step 2: Get latest measurements from this location
            # Format: GET /v3/locations/{location_id}/latest
            latest_url = f"{self.BASE_URL}/locations/{location_id}/latest"
            
            try:
                # Check rate limits before making request
                if self.rate_limiter.should_wait():
                    wait_time = self.rate_limiter.wait_if_needed()
                    if wait_time > 0 and self.logger:
                        self.logger.info(f"OpenAQ: Väntade {wait_time:.1f}s för rate limit (measurements)")
                
                latest_response = requests.get(
                    latest_url,
                    headers=self._headers,
                    timeout=10
                )
                
                # Update rate limiter from response headers
                self.rate_limiter.update_from_headers(latest_response.headers)
                self.rate_limiter.record_request()
                
                # Handle 429 Too Many Requests
                if latest_response.status_code == 429:
                    retry_after = latest_response.headers.get('Retry-After')
                    wait_time = 60
                    if retry_after:
                        try:
                            wait_time = int(retry_after)
                        except (ValueError, TypeError):
                            pass
                    
                    if self.logger:
                        self.logger.warning(f"OpenAQ: Rate limit nådd vid measurements (429). Väntar {wait_time}s...")
                    time.sleep(wait_time)
                    
                    # Retry once
                    latest_response = requests.get(
                        latest_url,
                        headers=self._headers,
                        timeout=10
                    )
                    self.rate_limiter.update_from_headers(latest_response.headers)
                    self.rate_limiter.record_request()
                    
                    if self.logger:
                        self.logger.info(f"OpenAQ: Retry measurements efter rate limit - status: {latest_response.status_code}")
                
                if latest_response.status_code in [410, 404, 422]:
                    error_msg = ""
                    try:
                        error_data = latest_response.json()
                        error_msg = f" - {error_data.get('message', '')}" if isinstance(error_data, dict) else ""
                    except:
                        pass
                    if self.logger:
                        self.logger.info(f"OpenAQ: Kunde inte hämta measurements för location {location_id} - status {latest_response.status_code}{error_msg}")
                    return None
                
                latest_response.raise_for_status()
                latest_data = latest_response.json()
                
            except requests.exceptions.HTTPError as e:
                if e.response and e.response.status_code in [410, 404, 422]:
                    error_msg = ""
                    try:
                        error_data = e.response.json()
                        error_msg = f" - {error_data.get('message', '')}" if isinstance(error_data, dict) else ""
                    except:
                        pass
                    if self.logger:
                        self.logger.info(f"OpenAQ: Measurements lookup misslyckades ({e.response.status_code}){error_msg}")
                    return None
                if self.logger:
                    self.logger.info(f"OpenAQ HTTP-fel vid measurements lookup: {e}")
                return None
            except Exception as e:
                if self.logger:
                    self.logger.info(f"OpenAQ fel vid measurements: {e}")
                return None
            
            # Log response summary for debugging
            if self.logger:
                results_count = len(latest_data.get("results", [])) if isinstance(latest_data.get("results"), list) else 0
                self.logger.info(f"OpenAQ: Fick {results_count} measurement-resultat för location {location_id}")
                
                # Log structure of first result to understand format
                if results_count > 0:
                    first_result = latest_data["results"][0]
                    if isinstance(first_result, dict):
                        keys = list(first_result.keys())[:10]  # First 10 keys
                        self.logger.info(f"OpenAQ: Första resultat-nycklar: {keys}")
                        # Log sample of first result (truncated)
                        import json
                        sample = {k: v for k, v in list(first_result.items())[:5]}
                        self.logger.info(f"OpenAQ: Första resultat-exempel: {json.dumps(sample, indent=2)}")
            
            # Parse measurements response
            # OpenAQ v3 /latest returns: {"results": [{"sensorsId": 123, "value": 12.5, "date": {...}, ...}, ...]}
            # We need to fetch sensor info to get parameterId
            # Also extract measurement timestamp from "date" field
            measurements = []
            measurement_timestamp = None  # Extract from first measurement with date
            
            if "results" in latest_data:
                results_list = latest_data["results"]
                if isinstance(results_list, list) and len(results_list) > 0:
                    # Extract measurement timestamp from first item that has "date" field
                    for item in results_list:
                        if isinstance(item, dict) and "date" in item:
                            date_obj = item.get("date")
                            if isinstance(date_obj, dict):
                                # Try UTC first, then local
                                date_utc = date_obj.get("utc")
                                date_local = date_obj.get("local")
                                
                                if date_utc:
                                    try:
                                        # Parse UTC timestamp and convert to CET
                                        measurement_timestamp = datetime.fromisoformat(date_utc.replace('Z', '+00:00'))
                                        if measurement_timestamp.tzinfo is None:
                                            # If naive, assume UTC
                                            from datetime import timezone
                                            measurement_timestamp = measurement_timestamp.replace(tzinfo=timezone.utc)
                                        # Convert to CET
                                        measurement_timestamp = measurement_timestamp.astimezone(CET)
                                        if self.logger:
                                            self.logger.debug(f"OpenAQ: Extraherade measurement timestamp: {measurement_timestamp} (från UTC: {date_utc})")
                                        break
                                    except (ValueError, TypeError) as e:
                                        if self.logger:
                                            self.logger.debug(f"OpenAQ: Kunde inte parsa UTC timestamp {date_utc}: {e}")
                                
                                if measurement_timestamp is None and date_local:
                                    try:
                                        # Parse local timestamp
                                        measurement_timestamp = datetime.fromisoformat(date_local)
                                        if measurement_timestamp.tzinfo is None:
                                            # If naive, assume CET
                                            measurement_timestamp = measurement_timestamp.replace(tzinfo=CET)
                                        else:
                                            # Convert to CET if different timezone
                                            measurement_timestamp = measurement_timestamp.astimezone(CET)
                                        if self.logger:
                                            self.logger.debug(f"OpenAQ: Extraherade measurement timestamp: {measurement_timestamp} (från local: {date_local})")
                                        break
                                    except (ValueError, TypeError) as e:
                                        if self.logger:
                                            self.logger.debug(f"OpenAQ: Kunde inte parsa local timestamp {date_local}: {e}")
                    
                    # Fetch parameter info for each sensor
                    sensor_param_cache = {}  # Cache sensor -> parameterId mapping
                    
                    for item in results_list:
                        if isinstance(item, dict) and "sensorsId" in item and "value" in item:
                            sensor_id = item.get("sensorsId")
                            value = item.get("value")
                            
                            # Get parameterId from sensor (use cache to avoid repeated API calls)
                            # Check both in-memory cache and this request's cache
                            if sensor_id not in sensor_param_cache:
                                # Check persistent cache first
                                if sensor_id in self._sensor_cache:
                                    sensor_param_cache[sensor_id] = self._sensor_cache[sensor_id]
                                    if self.logger:
                                        self.logger.debug(f"OpenAQ: Använder cached parameterId {self._sensor_cache[sensor_id]} för sensor {sensor_id}")
                                else:
                                    try:
                                        # Check rate limits before making request
                                        if self.rate_limiter.should_wait():
                                            wait_time = self.rate_limiter.wait_if_needed()
                                            if wait_time > 0 and self.logger:
                                                self.logger.debug(f"OpenAQ: Väntade {wait_time:.1f}s för rate limit (sensor {sensor_id})")
                                        
                                        sensor_url = f"{self.BASE_URL}/sensors/{sensor_id}"
                                        sensor_response = requests.get(
                                            sensor_url,
                                            headers=self._headers,
                                            timeout=5
                                        )
                                        
                                        # Update rate limiter
                                        self.rate_limiter.update_from_headers(sensor_response.headers)
                                        self.rate_limiter.record_request()
                                        
                                        # Handle 429
                                        if sensor_response.status_code == 429:
                                            if self.logger:
                                                self.logger.warning(f"OpenAQ: Rate limit nådd vid sensor lookup (429). Hoppar över sensor {sensor_id}")
                                            continue
                                        
                                        if sensor_response.status_code == 200:
                                            sensor_data = sensor_response.json()
                                            # Sensor response structure: {"results": [{"parameter": {"id": 2, "name": "pm25"}, ...}]}
                                            # OR: {"parameter": {"id": 2, ...}} (direct)
                                            param_id = None
                                            if "results" in sensor_data and len(sensor_data["results"]) > 0:
                                                # Array response
                                                sensor_obj = sensor_data["results"][0]
                                                if "parameter" in sensor_obj:
                                                    param_obj = sensor_obj["parameter"]
                                                    if isinstance(param_obj, dict):
                                                        param_id = param_obj.get("id")
                                                    else:
                                                        param_id = param_obj
                                            elif "parameter" in sensor_data:
                                                # Direct response
                                                param_obj = sensor_data["parameter"]
                                                if isinstance(param_obj, dict):
                                                    param_id = param_obj.get("id")
                                                else:
                                                    param_id = param_obj
                                            
                                            # Fallback: try parameterId directly
                                            if not param_id:
                                                param_id = sensor_data.get("parameterId") or sensor_data.get("parameter")
                                            
                                            if param_id:
                                                sensor_param_cache[sensor_id] = param_id
                                                # Cache for future requests
                                                self._sensor_cache[sensor_id] = param_id
                                                if self.logger:
                                                    self.logger.debug(f"OpenAQ: Sensor {sensor_id} har parameterId {param_id} (cached)")
                                        else:
                                            if self.logger:
                                                self.logger.info(f"OpenAQ: Kunde inte hämta sensor {sensor_id} info (status {sensor_response.status_code})")
                                    except Exception as e:
                                        if self.logger:
                                            self.logger.info(f"OpenAQ: Fel vid hämtning av sensor {sensor_id} info: {e}")
                                        continue
                            
                            # If we have parameterId, create measurement object
                            if sensor_id in sensor_param_cache:
                                param_id = sensor_param_cache[sensor_id]
                                measurement = {
                                    "sensorId": sensor_id,  # Include sensor_id for sensor data collection
                                    "sensorsId": sensor_id,  # Also include as sensorsId for compatibility
                                    "parameterId": param_id,
                                    "parameter": param_id,  # Use ID as parameter name too
                                    "value": value
                                }
                                measurements.append(measurement)
                            else:
                                # Try to infer from value range (PM2.5 is typically < 100, PM10 < 200)
                                # This is a fallback, but we should prefer sensor info
                                if self.logger:
                                    self.logger.info(f"OpenAQ: Ingen parameterId för sensor {sensor_id}, hoppar över")
            
            if self.logger:
                self.logger.info(f"OpenAQ: Parsade {len(measurements)} measurements från location {location_id}")
                if len(measurements) > 0:
                    # Log first measurement structure
                    first_meas = measurements[0]
                    meas_keys = list(first_meas.keys())[:10]
                    self.logger.info(f"OpenAQ: Första measurement-nycklar: {meas_keys}")
            
            # Collect all available pollutant values
            # Parameter IDs: 2=PM2.5, 1=PM10, 5=NO2, 3=O3
            pollutants = {
                "pm25": None,
                "pm10": None,
                "no2": None,
                "o3": None
            }
            
            for measurement in measurements:
                parameter = measurement.get("parameter")
                parameter_id = measurement.get("parameterId")
                value = measurement.get("value")
                
                # Handle different parameter name formats
                if not value:
                    # Try alternative field names
                    value = measurement.get("average") or measurement.get("latestValue") or measurement.get("lastValue")
                
                if value is None:
                    continue
                
                try:
                    value_float = float(value)
                    
                    # Map parameter ID to pollutant type
                    if parameter_id == 2 or (isinstance(parameter, (int, str)) and str(parameter).lower() in ["pm2.5", "pm25", "pm2_5", "2"]):
                        if pollutants["pm25"] is None:
                            pollutants["pm25"] = value_float
                            if self.logger:
                                self.logger.info(f"OpenAQ: Hittade PM2.5={value_float} µg/m³ för location {location_id}")
                    elif parameter_id == 1 or (isinstance(parameter, (int, str)) and str(parameter).lower() in ["pm10", "1"]):
                        if pollutants["pm10"] is None:
                            pollutants["pm10"] = value_float
                            if self.logger:
                                self.logger.info(f"OpenAQ: Hittade PM10={value_float} µg/m³ för location {location_id}")
                    elif parameter_id == 5 or (isinstance(parameter, (int, str)) and str(parameter).lower() in ["no2", "5"]):
                        # Check units - we want µg/m³, not ppm
                        if pollutants["no2"] is None:
                            pollutants["no2"] = value_float
                            if self.logger:
                                self.logger.info(f"OpenAQ: Hittade NO2={value_float} µg/m³ för location {location_id}")
                    elif parameter_id == 3 or (isinstance(parameter, (int, str)) and str(parameter).lower() in ["o3", "3"]):
                        # Check units - we want µg/m³, not ppm
                        if pollutants["o3"] is None:
                            pollutants["o3"] = value_float
                            if self.logger:
                                self.logger.info(f"OpenAQ: Hittade O3={value_float} µg/m³ för location {location_id}")
                except (ValueError, TypeError) as e:
                    if self.logger:
                        self.logger.info(f"OpenAQ: Fel vid konvertering av värde: {e} (value={value}, type={type(value)})")
                    continue
            
            # Return pollutants dict with measurement timestamp if we have at least one value
            if any(v is not None for v in pollutants.values()):
                if self.logger:
                    found = [k for k, v in pollutants.items() if v is not None]
                    self.logger.info(f"OpenAQ: Returnerar pollutant-värden för ({latitude}, {longitude}): {found}")
                    if measurement_timestamp:
                        self.logger.info(f"OpenAQ: Measurement timestamp: {measurement_timestamp}")
                    else:
                        # Log detailed structure to debug missing timestamp
                        self.logger.warning(f"OpenAQ: Ingen measurement timestamp hittades i API response")
                        if "results" in latest_data:
                            results_list = latest_data["results"]
                            if isinstance(results_list, list) and len(results_list) > 0:
                                first_result = results_list[0]
                                if isinstance(first_result, dict):
                                    self.logger.debug(f"OpenAQ: Första resultat-nycklar: {list(first_result.keys())[:10]}")
                                    if "date" in first_result:
                                        date_obj = first_result["date"]
                                        self.logger.debug(f"OpenAQ: 'date' objekt typ: {type(date_obj)}, innehåll: {date_obj}")
                                    else:
                                        self.logger.debug(f"OpenAQ: 'date' nyckel saknas i första resultat")
                
                # Collect sensor data for return
                sensors_list = []
                # Use location coordinates for all sensors at this location
                sensor_lat = location_coords.get("latitude") if location_coords else None
                sensor_lon = location_coords.get("longitude") if location_coords else None
                
                # Track unique sensors to avoid duplicates
                seen_sensors = set()
                
                for measurement in measurements:
                    sensor_id = measurement.get("sensorId") or measurement.get("sensorsId")
                    parameter_id = measurement.get("parameterId")
                    parameter_name = measurement.get("parameter")
                    value = measurement.get("value")
                    
                    # Skip if we've already seen this sensor+parameter combination
                    sensor_key = (sensor_id, parameter_id)
                    if sensor_key in seen_sensors:
                        continue
                    seen_sensors.add(sensor_key)
                    
                    if sensor_id and sensor_lat is not None and sensor_lon is not None:
                        sensors_list.append({
                            "sensor_id": sensor_id,
                            "parameter": parameter_name,
                            "parameter_id": parameter_id,
                            "value": value,
                            "coordinates": {
                                "latitude": sensor_lat,
                                "longitude": sensor_lon
                            }
                        })
                
                # Ensure timestamp is included in return value
                return {
                    "pollutants": pollutants,
                    "measurement_timestamp": measurement_timestamp,  # May be None, but explicitly included
                    "sensors": sensors_list  # List of sensor data
                }
            else:
                if self.logger:
                    param_names = [m.get("parameter", "unknown") for m in measurements[:5]]  # First 5 for logging
                    self.logger.info(f"OpenAQ: Inga kända pollutant-parametrar hittades för location {location_id}. Tillgängliga parametrar: {param_names}")
                return None
            
        except (KeyError, ValueError, TypeError) as e:
            if self.logger:
                self.logger.info(f"OpenAQ parsing-fel: {e}")
            return None
        except Exception as e:
            if self.logger:
                self.logger.info(f"OpenAQ oväntat fel: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if provider is available."""
        return self._available



