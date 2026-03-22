"""Open-Meteo weather API provider."""

import json
import threading
import requests
from requests import Response
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Optional, Any, List
from providers.base_provider import WeatherProvider
from providers.openmeteo_hourly_groups import (
    build_hourly_groups_for_parameters,
    hourly_groups_to_comma_string,
)
from utils.logger import WeatherLogger
from utils.unit_conversion import convert_parameter_unit

# CET timezone for all operations
CET = ZoneInfo("Europe/Stockholm")

# After HTTP 429 or JSON {"error":true,"reason":"Daily API request limit ..."} from Open-Meteo,
# skip all HTTP calls to their API until next midnight Europe/Stockholm (process-wide).
_openmeteo_429_until: Optional[datetime] = None
_openmeteo_429_lock = threading.Lock()


def _openmeteo_json_is_daily_limit_error(payload: Any) -> bool:
    """
    Open-Meteo returns e.g.:
    {"reason":"Daily API request limit exceeded. Please try again tomorrow.","error":true}
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("error") is not True:
        return False
    reason = payload.get("reason")
    if not isinstance(reason, str):
        return False
    rl = reason.lower()
    return "daily" in rl and "limit" in rl


def _openmeteo_error_reason_from_response(resp: Optional[Response]) -> Optional[str]:
    if resp is None:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if isinstance(data, dict) and isinstance(data.get("reason"), str):
        return data["reason"]
    return None


def _next_midnight_cet() -> datetime:
    now = datetime.now(CET)
    next_day = now.date() + timedelta(days=1)
    return datetime.combine(next_day, datetime.min.time(), tzinfo=CET)


def _openmeteo_arm_daily_limit_backoff(
    logger: Optional[WeatherLogger],
    *,
    detail: Optional[str] = None,
) -> None:
    """Arm daily backoff after 429 or JSON daily-limit error; log once when entering the window."""
    global _openmeteo_429_until
    new_until = _next_midnight_cet()
    now = datetime.now(CET)
    should_log = False
    with _openmeteo_429_lock:
        prev = _openmeteo_429_until
        if prev is None or now >= prev:
            _openmeteo_429_until = new_until
            should_log = True
    if should_log and logger:
        suffix = f" API: {detail}" if detail else ""
        logger.warning(
            "Open-Meteo: daglig hastighets-/kvotgräns — inga fler anrop till API tills nästa dygn "
            f"(Europe/Stockholm). Återupptas efter {new_until.isoformat()}.{suffix}"
        )


def _openmeteo_should_skip_requests() -> bool:
    """True if we are inside the daily-limit backoff window (after 429 or JSON daily-limit error)."""
    global _openmeteo_429_until
    with _openmeteo_429_lock:
        until = _openmeteo_429_until
    if until is None:
        return False
    now = datetime.now(CET)
    if now >= until:
        with _openmeteo_429_lock:
            if _openmeteo_429_until is not None and datetime.now(CET) >= _openmeteo_429_until:
                _openmeteo_429_until = None
        return False
    return True


class OpenMeteoProvider(WeatherProvider):
    """Open-Meteo API provider (no API key required)."""
    
    BASE_URL = "https://api.open-meteo.com/v1"

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
        self._mappings_revision: int = -1
        self._parameter_mappings = self._load_parameter_mappings()
        if db_manager is not None:
            self._mappings_revision = db_manager.parameter_registry_revision
    
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

        if not mappings and self.logger:
            self.logger.warning(
                "Open-Meteo: inga provider_mappings (openmeteo) i parameter_registry — konfigurera databasen"
            )

        if self.logger:
            self.logger.debug(f"Open-Meteo: Laddade {len(mappings)} parameter mappings från DB")

        return mappings

    def _refresh_parameter_mappings_if_stale(self) -> None:
        if not self.db_manager:
            return
        rev = self.db_manager.parameter_registry_revision
        if rev != self._mappings_revision:
            self._parameter_mappings = self._load_parameter_mappings()
            self._mappings_revision = rev
    
    def _get_parameter_names_for_categories(self, categories: List[str]) -> List[str]:
        """
        Hämta parameter_name från parameter_registry där provider_mappings innehåller openmeteo.
        Ingen hårdkodad parameterlista — endast DB.
        """
        if not self.db_manager or not categories:
            return []

        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(categories))
            cursor.execute(
                f"""
                SELECT parameter_name, provider_mappings
                FROM parameter_registry
                WHERE category IN ({placeholders})
                  AND provider_mappings IS NOT NULL
                  AND TRIM(provider_mappings) != ''
                """,
                tuple(categories),
            )
            param_names: List[str] = []
            for row in cursor.fetchall():
                pname, raw = row[0], row[1]
                try:
                    pm = json.loads(raw)
                    if isinstance(pm, dict) and "openmeteo" in pm and pm["openmeteo"]:
                        param_names.append(pname)
                except (json.JSONDecodeError, TypeError):
                    continue
            if self.logger:
                self.logger.debug(
                    f"Open-Meteo: {len(param_names)} parametrar med openmeteo-mapping för kategorier {categories}"
                )
            return param_names
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Open-Meteo: Kunde inte läsa parameter_registry: {e}")
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
    
    def _merge_current_endpoint_fields_into_result(
        self,
        result: Dict[str, Any],
        current: Dict[str, Any],
        current_param_names: List[str],
    ) -> None:
        """
        Fill result with any parameter_name in current_param_names that has an Open-Meteo mapping
        and a value in `current`, using unit conversion. Skips core fields already handled explicitly.
        """
        if not self.db_manager:
            return
        # temperature / humidity / wind_speed: explicit conversion paths
        skip = {"temperature", "humidity", "wind_speed"}
        for pname in current_param_names:
            if pname in skip:
                continue
            if pname not in self._parameter_mappings:
                continue
            api_field = self._parameter_mappings[pname]
            raw = current.get(api_field)
            if raw is None:
                continue
            try:
                fv = float(raw)
                val = convert_parameter_unit(
                    self.db_manager,
                    pname,
                    fv,
                    self.name,
                    logger=self.logger,
                )
                result[pname] = val
            except (TypeError, ValueError) as e:
                if self.logger:
                    self.logger.debug(f"Open-Meteo: kunde inte sätta {pname} från current: {e}")

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
            # air_quality: pm2_5, gases, etc. from same forecast current= when mapped in registry
            categories = ['weather', 'solar', 'air_quality']
        elif endpoint == 'hourly':
            categories = ['storm']
        else:
            return []
        
        if db_manager:
            self.db_manager = db_manager
            self._refresh_parameter_mappings_if_stale()

        params = self._get_parameter_names_for_categories(categories)
        
        if self.logger:
            self.logger.debug(f"Open-Meteo: Upptäckte {len(params)} tillgängliga parametrar för {endpoint} endpoint")
        
        return params
    
    def get_current_weather(self, latitude: float, longitude: float) -> Optional[Dict]:
        """Get current weather data."""
        try:
            self._refresh_parameter_mappings_if_stale()
            if _openmeteo_should_skip_requests():
                if self.logger:
                    self.logger.debug(
                        "Open-Meteo: hoppar get_current_weather (429 — väntar till nästa dygn CET)"
                    )
                return None
            weather_url = f"{self.BASE_URL}/forecast"

            current_param_names = self._discover_available_parameters("current")
            if self.logger:
                self.logger.debug(
                    f"Open-Meteo: current parametrar från registry: {current_param_names}"
                )

            if not current_param_names:
                if self.logger:
                    self.logger.warning(
                        "Open-Meteo: inga current-parametrar i parameter_registry (openmeteo mappings) — avbryter"
                    )
                return None
            
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
            
            response = None
            try:
                if self.logger:
                    self.logger.debug(f"Open-Meteo: Gör request till {weather_url} med params: {current_params}")
                response = requests.get(weather_url, params=current_params, timeout=10)
                if self.logger:
                    self.logger.debug(f"Open-Meteo response status: {response.status_code}")
                response.raise_for_status()
                data = response.json()
                if _openmeteo_json_is_daily_limit_error(data):
                    rsn = data.get("reason")
                    _openmeteo_arm_daily_limit_backoff(
                        self.logger,
                        detail=rsn if isinstance(rsn, str) else None,
                    )
                    return None

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
                resp = getattr(e, "response", None) or response
                if resp is not None and resp.status_code == 429:
                    _openmeteo_arm_daily_limit_backoff(
                        self.logger,
                        detail=_openmeteo_error_reason_from_response(resp),
                    )
                    return None
                if resp is not None and resp.status_code == 400:
                    # Log response body for debugging
                    try:
                        error_body = resp.text[:500]  # First 500 chars
                        if self.logger:
                            self.logger.error(f"Open-Meteo 400 Bad Request: {error_body}")
                    except Exception:
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

            storm_params = {
                "cape": None,
                "precipitation_probability": None,
                "convective_precipitation": None,
            }

            hourly_param_names = self._discover_available_parameters("hourly")
            self._refresh_parameter_mappings_if_stale()

            if self.db_manager and hourly_param_names:
                groups = build_hourly_groups_for_parameters(
                    self.db_manager,
                    endpoint_profile="forecast-api",
                    parameter_names=hourly_param_names,
                    openmeteo_mappings=self._parameter_mappings,
                )
            else:
                groups = []

            if not groups:
                if self.logger:
                    self.logger.warning(
                        "Open-Meteo: inga hourly-grupper från DB (storm + variable_family) — storm-fält kan bli tomma"
                    )
            else:
                for group in groups:
                    if _openmeteo_should_skip_requests():
                        if self.logger:
                            self.logger.debug(
                                "Open-Meteo: avbryter hourly-grupper (429 — väntar till nästa dygn CET)"
                            )
                        break
                    hourly_str = hourly_groups_to_comma_string(group)
                    if not hourly_str:
                        continue
                    hourly_req = {
                        "latitude": latitude,
                        "longitude": longitude,
                        "hourly": hourly_str,
                        "timezone": "auto",
                    }
                    try:
                        if self.logger:
                            self.logger.debug(
                                f"Open-Meteo: hourly group family={group.family_key} hourly={hourly_str}"
                            )
                        hourly_response = requests.get(weather_url, params=hourly_req, timeout=10)
                        if hourly_response.status_code == 400:
                            if self.logger:
                                self.logger.warning(
                                    f"Open-Meteo hourly 400 Bad Request: {hourly_response.text[:500]}"
                                )
                            continue
                        hourly_response.raise_for_status()
                        hourly_data = hourly_response.json()
                        if _openmeteo_json_is_daily_limit_error(hourly_data):
                            rsn = hourly_data.get("reason")
                            _openmeteo_arm_daily_limit_backoff(
                                self.logger,
                                detail=rsn if isinstance(rsn, str) else None,
                            )
                            break
                        hourly = hourly_data.get("hourly") or {}
                        times = hourly.get("time") or []
                        if not times:
                            continue
                        for param_name in group.parameter_names:
                            if param_name not in self._parameter_mappings:
                                continue
                            api_field = self._parameter_mappings[param_name]
                            param_vals = hourly.get(api_field, [])
                            if param_vals and len(param_vals) > 0:
                                storm_params[param_name] = param_vals[0]
                                if self.logger:
                                    self.logger.debug(
                                        f"Open-Meteo: {param_name}={param_vals[0]} från hourly[{api_field}]"
                                    )
                    except requests.exceptions.HTTPError as e:
                        hresp = getattr(e, "response", None)
                        if hresp is not None and hresp.status_code == 429:
                            _openmeteo_arm_daily_limit_backoff(
                                self.logger,
                                detail=_openmeteo_error_reason_from_response(hresp),
                            )
                            break
                        if self.logger:
                            self.logger.warning(f"Open-Meteo hourly group HTTP-fel: {e}")
                    except Exception as e:
                        if self.logger:
                            self.logger.warning(f"Open-Meteo hourly group misslyckades: {e}")
            
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
            
            # Basic weather (raw from API)
            temperature = current.get("temperature_2m")
            humidity_val = current.get("relative_humidity_2m")
            wind_speed_raw = current.get("wind_speed_10m")
            
            # Log raw wind_speed_10m value from API for debugging (API doc: km/h by default)
            if self.logger:
                if wind_speed_raw is not None:
                    self.logger.debug(
                        f"Open-Meteo: Råa wind_speed_10m från API för ({latitude:.4f}, {longitude:.4f}): {wind_speed_raw}"
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
            
            # Convert wind_speed to databasenhet via central unit converter
            wind_speed_converted = None
            if wind_speed_raw is not None:
                try:
                    if self.db_manager is not None:
                        wind_speed_converted = convert_parameter_unit(
                            self.db_manager,
                            "wind_speed",
                            float(wind_speed_raw),
                            self.name,
                            logger=self.logger,
                        )
                    else:
                        # No DB available for units: assume raw value is already in target unit
                        wind_speed_converted = float(wind_speed_raw)
                except Exception as e:
                    if self.logger:
                        self.logger.warning(
                            f"Open-Meteo: Kunde inte konvertera wind_speed-värde {wind_speed_raw} "
                            f"för ({latitude:.4f}, {longitude:.4f}): {e}"
                        )
                    wind_speed_converted = None
            
            if self.logger and wind_speed_converted is not None:
                self.logger.debug(
                    f"[UNITS] Open-Meteo: wind_speed_10m raw={wind_speed_raw} "
                    f"-> stored wind_speed={wind_speed_converted:.2f} (provider={self.name})"
                )
                if float(wind_speed_converted) > 20.0:
                    self.logger.warning(
                        f"Open-Meteo: Högt wind_speed-värde efter konvertering: {wind_speed_converted:.2f} m/s "
                        f"för ({latitude:.4f}, {longitude:.4f}) – verifiera enheter och data."
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
            self._merge_current_endpoint_fields_into_result(result, current, current_param_names)
            
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
            if _openmeteo_should_skip_requests():
                if self.logger:
                    self.logger.debug(
                        "Open-Meteo: hoppar get_air_quality (429 — väntar till nästa dygn CET)"
                    )
                return None
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
                if _openmeteo_json_is_daily_limit_error(data):
                    rsn = data.get("reason")
                    _openmeteo_arm_daily_limit_backoff(
                        self.logger,
                        detail=rsn if isinstance(rsn, str) else None,
                    )
                    return None
            except requests.exceptions.HTTPError as e:
                resp = getattr(e, "response", None)
                if resp is not None and resp.status_code == 429:
                    _openmeteo_arm_daily_limit_backoff(
                        self.logger,
                        detail=_openmeteo_error_reason_from_response(resp),
                    )
                    return None
                if self.logger:
                    self.logger.info(
                        f"Open-Meteo AQI HTTP-fel för ({latitude}, {longitude}): {e}"
                    )
                return None
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
        if not self._available:
            return False
        if _openmeteo_should_skip_requests():
            return False
        return True
