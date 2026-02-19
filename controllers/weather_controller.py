"""Main weather controller (MVC pattern)."""

import threading
from typing import List, Dict, Optional
from database.db_manager import DatabaseManager
from utils.config_loader import ConfigLoader
from utils.logger import WeatherLogger
from providers.openmeteo_provider import OpenMeteoProvider
from providers.openweather_provider import OpenWeatherProvider
from providers.openaq_provider import OpenAQProvider
from analytics.analyzer import WeatherAnalyzer


class WeatherController:
    """Main controller connecting GUI, providers, database and analytics."""
    
    def __init__(self):
        """Initialize controller."""
        # Load configuration
        self.config = ConfigLoader()
        
        # Initialize logger
        self.logger = WeatherLogger()
        self.logger.info("Initialiserar väderapplikation...")
        
        # Initialize database
        self.db = DatabaseManager()
        self.logger.info("Databas initialiserad")
        
        # Initialize providers
        # Priority order: OpenAQ > Open-Meteo > OpenWeather
        # (OpenWeather only provides categories, not real AQI values)
        self.providers = []
        
        # OpenAQ (best AQI data - real measurements)
        try:
            api_key = self.config.get_api_key("openaq")
            if api_key:
                self.openaq = OpenAQProvider(api_key, self.logger)
                self.providers.append(self.openaq)
                self.logger.info("OpenAQ provider initialiserad")
            else:
                self.logger.warning("OpenAQ API-nyckel saknas")
                self.openaq = None
        except Exception as e:
            self.logger.error(f"Kunde inte initialisera OpenAQ: {e}")
            self.openaq = None
        
        # Open-Meteo (good AQI data - european_aqi)
        try:
            self.openmeteo = OpenMeteoProvider(self.logger)
            self.providers.append(self.openmeteo)
            self.logger.info("Open-Meteo provider initialiserad")
        except Exception as e:
            self.logger.error(f"Kunde inte initialisera Open-Meteo: {e}")
            self.openmeteo = None
        
        # OpenWeatherMap (only categories, not real AQI - use for weather only)
        try:
            api_key = self.config.get_api_key("openweather")
            if api_key:
                self.openweather = OpenWeatherProvider(api_key, self.logger)
                self.providers.append(self.openweather)
                self.logger.info("OpenWeatherMap provider initialiserad (används endast för väder, inte AQI)")
            else:
                self.logger.warning("OpenWeatherMap API-nyckel saknas")
                self.openweather = None
        except Exception as e:
            self.logger.error(f"Kunde inte initialisera OpenWeatherMap: {e}")
            self.openweather = None
        
        # Initialize analytics
        self.analyzer = WeatherAnalyzer(self.db)
        
        # Current selection
        self.current_city_id = None
        
        self.logger.info("Controller initialiserad")
    
    # City operations
    def add_city(self, name: str, latitude: float, longitude: float) -> int:
        """
        Add a city.
        
        Args:
            name: City name
            latitude: Latitude
            longitude: Longitude
            
        Returns:
            City ID
        """
        city_id = self.db.add_city(name, latitude, longitude)
        self.logger.info(f"Lade till stad: {name} ({latitude}, {longitude})")
        return city_id
    
    def add_multiple_cities(self, cities: List[Dict]) -> int:
        """
        Add multiple cities at once.
        
        Args:
            cities: List of dicts with 'name', 'latitude', 'longitude'
            
        Returns:
            Number of cities successfully added
        """
        added_count = 0
        for city in cities:
            try:
                name = city['name']
                lat = city.get('lat') or city.get('latitude')
                lon = city.get('lon') or city.get('longitude')
                if lat is None or lon is None:
                    self.logger.warning(f"Saknar koordinater för {name}, hoppar över")
                    continue
                self.add_city(name, lat, lon)
                added_count += 1
            except ValueError as e:
                # City already exists, skip
                self.logger.debug(f"Stad {city.get('name', 'okänd')} finns redan: {e}")
                continue
            except Exception as e:
                self.logger.error(f"Fel vid tillägg av stad {city.get('name', 'okänd')}: {e}")
                continue
        self.logger.info(f"Lade till {added_count} av {len(cities)} städer")
        return added_count
    
    def remove_city(self, city_id: int):
        """Remove a city."""
        city = self.db.get_city(city_id)
        if city:
            self.db.delete_city(city_id)
            self.logger.info(f"Tog bort stad: {city['name']}")
            if self.current_city_id == city_id:
                self.current_city_id = None
    
    def get_all_cities(self) -> List[Dict]:
        """Get all cities."""
        return self.db.get_all_cities()
    
    def get_city(self, city_id: int) -> Optional[Dict]:
        """Get city by ID."""
        return self.db.get_city(city_id)
    
    def select_city(self, city_id: int):
        """Select a city."""
        self.current_city_id = city_id
        # Trigger GUI update if needed
        if hasattr(self, '_gui_update_callback'):
            self._gui_update_callback()
    
    # Weather operations
    def get_city_weather(self, city_id: int) -> Optional[Dict]:
        """Get latest weather for a city."""
        return self.db.get_latest_weather(city_id)
    
    def update_all_cities(self):
        """Update weather for all cities."""
        cities = self.get_all_cities()
        if not cities:
            self.logger.info("Inga städer att uppdatera")
            return
        
        self.logger.info(f"Uppdaterar väder för {len(cities)} städer...")
        
        # Update in separate thread to avoid blocking GUI
        # Use a safer approach with exception handling
        try:
            thread = threading.Thread(target=self._update_cities_thread, args=(cities,), daemon=True)
            thread.start()
        except Exception as e:
            self.logger.error(f"Kunde inte starta uppdateringstråd: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
    
    def _update_cities_thread(self, cities: List[Dict]):
        """Thread function for updating cities."""
        try:
            self.logger.debug(f"Tråd startad för uppdatering av {len(cities)} städer")
            for city in cities:
                try:
                    city_name = city.get('name', 'okänd stad')
                    self.logger.debug(f"Bearbetar stad: {city_name}")
                    self._update_city_weather(city)
                except KeyboardInterrupt:
                    self.logger.warning("Uppdatering avbruten av användare")
                    break
                except SystemExit:
                    self.logger.warning("System avslutas")
                    break
                except Exception as e:
                    import traceback
                    error_msg = str(e)
                    self.logger.error(f"Fel vid uppdatering av {city.get('name', 'okänd stad')}: {error_msg}")
                    # Only log full traceback in debug mode to avoid spam
                    if self.logger.logger.level <= 10:  # DEBUG level
                        self.logger.debug(f"Traceback: {traceback.format_exc()}")
                    # Continue with next city
                    continue
            
            self.logger.info("Alla städer uppdaterade")
        except Exception as e:
            import traceback
            self.logger.error(f"Kritiskt fel i uppdateringstråd: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
    
    def _update_city_weather(self, city: Dict):
        """Update weather for a single city."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        lat = city['latitude']
        lon = city['longitude']
        city_id = city['id']
        city_name = city['name']
        
        # Log function call with timestamp for debugging duplicate calls
        call_timestamp = datetime.now(ZoneInfo("Europe/Stockholm"))
        self.logger.info(f"[DEBUG] _update_city_weather() anropad för {city_name} (ID: {city_id}) kl {call_timestamp}")
        self.logger.debug(f"Uppdaterar väder för {city_name} ({lat}, {lon})")
        
        # Try all providers and aggregate data
        weather_data = None
        merged_pollutants = {
            "pm25": None,
            "pm10": None,
            "no2": None,
            "o3": None
        }
        pollutant_measurement_timestamp = None  # Track measurement timestamp for pollutants
        providers_tried = []
        
        # Priority for weather: Open-Meteo > OpenWeather > OpenAQ
        # Priority for pollutants: OpenAQ > Open-Meteo > OpenWeather
        provider_priority = {'openaq': 0, 'openmeteo': 1, 'openweather': 2}
        
        for provider in self.providers:
            try:
                if not hasattr(provider, 'name'):
                    continue
                    
                provider_name = provider.name
                providers_tried.append(provider_name)
                self.logger.info(f"[DEBUG] Anropar {provider_name}.get_current_weather() för {city_name}")
                self.logger.debug(f"Försöker hämta data från {provider_name}...")
                
                # Check availability safely
                try:
                    is_available = provider.is_available()
                except Exception as avail_error:
                    self.logger.debug(f"{provider_name}: Kunde inte kontrollera tillgänglighet: {avail_error}")
                    is_available = False
                
                if not is_available:
                    self.logger.info(f"{provider_name} är inte tillgänglig, försöker hämta pollutant-data ändå...")
                    # Try to get pollutants separately even if provider reports unavailable
                    try:
                        air_quality_result = provider.get_air_quality(lat, lon)
                        if air_quality_result and isinstance(air_quality_result, dict):
                            pollutants = air_quality_result.get("pollutants", {})
                            # Extract measurement timestamp if available
                            if pollutant_measurement_timestamp is None:
                                pollutant_measurement_timestamp = air_quality_result.get("measurement_timestamp")
                            
                            # Merge pollutants (keep best available value for each parameter)
                            for param in ['pm25', 'pm10', 'no2', 'o3']:
                                if pollutants.get(param) is not None:
                                    # Use value if we don't have one, or if this provider has higher priority
                                    current_priority = provider_priority.get(provider_name, 99)
                                    if merged_pollutants[param] is None:
                                        merged_pollutants[param] = pollutants.get(param)
                                        self.logger.info(f"{provider_name}: Fick {param}={pollutants.get(param)} separat")
                    except Exception as poll_error:
                        self.logger.info(f"{provider_name}: Kunde inte hämta pollutant-data: {poll_error}")
                    continue
                
                # Try to get weather data
                try:
                    data = provider.get_current_weather(lat, lon)
                    if data and isinstance(data, dict):
                        # Use first available weather data
                        if weather_data is None and data.get('temperature') is not None:
                            weather_data = data
                            self.logger.debug(f"{provider_name}: Fick väderdata (temp={data.get('temperature')}°C)")
                        
                        # Collect pollutant values from weather data
                        for param in ['pm25', 'pm10', 'no2', 'o3']:
                            if data.get(param) is not None:
                                # Use value if we don't have one, or if this provider has higher priority
                                if merged_pollutants[param] is None:
                                    merged_pollutants[param] = data.get(param)
                                    self.logger.info(f"{provider_name}: Fick {param}={data.get(param)} från get_current_weather")
                        
                        # Extract measurement timestamp from weather data if available
                        if pollutant_measurement_timestamp is None:
                            pollutant_measurement_timestamp = data.get("measurement_timestamp")
                        
                        # Also try get_air_quality separately for pollutants
                        # NOTE: This may cause duplicate API calls if get_current_weather() already calls get_air_quality()
                        # We should check if get_current_weather() already returned pollutants before calling this
                        try:
                            self.logger.info(f"[DEBUG] Anropar {provider_name}.get_air_quality() separat för {city_name}")
                            air_quality_result = provider.get_air_quality(lat, lon)
                            if air_quality_result and isinstance(air_quality_result, dict):
                                pollutants = air_quality_result.get("pollutants", {})
                                # Extract measurement timestamp if available
                                if pollutant_measurement_timestamp is None:
                                    pollutant_measurement_timestamp = air_quality_result.get("measurement_timestamp")
                                
                                # Save sensors to database if OpenAQ returned sensor data
                                if provider_name == "openaq" and "sensors" in air_quality_result:
                                    sensors_data = air_quality_result.get("sensors", [])
                                    if sensors_data:
                                        self.logger.debug(f"Sparar {len(sensors_data)} sensorer för {city_name}")
                                        for sensor in sensors_data:
                                            try:
                                                sensor_id = sensor.get("sensor_id")
                                                parameter = sensor.get("parameter")
                                                coords = sensor.get("coordinates", {})
                                                sensor_lat = coords.get("latitude")
                                                sensor_lon = coords.get("longitude")
                                                value = sensor.get("value")
                                                
                                                if sensor_id and sensor_lat is not None and sensor_lon is not None:
                                                    # Map parameter ID or name to standard format
                                                    # Parameter IDs: 2=PM2.5, 1=PM10, 5=NO2, 3=O3
                                                    param_id_map = {
                                                        2: "PM2.5",
                                                        1: "PM10",
                                                        5: "NO2",
                                                        3: "O3"
                                                    }
                                                    param_name_map = {
                                                        "pm2.5": "PM2.5",
                                                        "pm25": "PM2.5",
                                                        "pm10": "PM10",
                                                        "no2": "NO2",
                                                        "o3": "O3"
                                                    }
                                                    
                                                    # Try parameter ID first, then parameter name
                                                    if isinstance(parameter, int):
                                                        param_name = param_id_map.get(parameter, f"Parameter_{parameter}")
                                                    else:
                                                        param_name = param_name_map.get(str(parameter).lower(), str(parameter))
                                                    
                                                    self.db.add_sensor(
                                                        city_id=city_id,
                                                        sensor_id=sensor_id,
                                                        parameter=param_name,
                                                        latitude=sensor_lat,
                                                        longitude=sensor_lon,
                                                        last_value=value,
                                                        last_updated=pollutant_measurement_timestamp,
                                                        is_custom=0,
                                                        custom_info=None
                                                    )
                                                    self.logger.debug(f"Sparade sensor {sensor_id} ({param_name}) för {city_name}")
                                            except Exception as sensor_err:
                                                self.logger.warning(f"Fel vid sparande av sensor för {city_name}: {sensor_err}")
                                
                                # Merge pollutants (keep best available value for each parameter)
                                for param in ['pm25', 'pm10', 'no2', 'o3']:
                                    if pollutants.get(param) is not None:
                                        # Use value if we don't have one
                                        if merged_pollutants[param] is None:
                                            merged_pollutants[param] = pollutants.get(param)
                                            self.logger.info(f"{provider_name}: Fick {param}={pollutants.get(param)} separat")
                        except Exception as poll_err:
                            self.logger.info(f"{provider_name}: Fel vid separat pollutant-hämtning: {poll_err}")
                except Exception as weather_error:
                    error_msg = str(weather_error)
                    self.logger.info(f"{provider_name}: Fel vid hämtning av väderdata: {error_msg}")
                    # Try to get pollutants separately as fallback
                    try:
                        air_quality_result = provider.get_air_quality(lat, lon)
                        if air_quality_result and isinstance(air_quality_result, dict):
                            pollutants = air_quality_result.get("pollutants", {})
                            # Extract measurement timestamp if available
                            if pollutant_measurement_timestamp is None:
                                pollutant_measurement_timestamp = air_quality_result.get("measurement_timestamp")
                            
                            # Save sensors to database if OpenAQ returned sensor data
                            if provider_name == "openaq" and "sensors" in air_quality_result:
                                sensors_data = air_quality_result.get("sensors", [])
                                if sensors_data:
                                    self.logger.debug(f"Sparar {len(sensors_data)} sensorer för {city_name} (efter väderdata-fel)")
                                    for sensor in sensors_data:
                                        try:
                                            sensor_id = sensor.get("sensor_id")
                                            parameter = sensor.get("parameter")
                                            coords = sensor.get("coordinates", {})
                                            sensor_lat = coords.get("latitude")
                                            sensor_lon = coords.get("longitude")
                                            value = sensor.get("value")
                                            
                                            if sensor_id and sensor_lat is not None and sensor_lon is not None:
                                                # Map parameter ID or name to standard format
                                                param_id_map = {
                                                    2: "PM2.5",
                                                    1: "PM10",
                                                    5: "NO2",
                                                    3: "O3"
                                                }
                                                param_name_map = {
                                                    "pm2.5": "PM2.5",
                                                    "pm25": "PM2.5",
                                                    "pm10": "PM10",
                                                    "no2": "NO2",
                                                    "o3": "O3"
                                                }
                                                
                                                if isinstance(parameter, int):
                                                    param_name = param_id_map.get(parameter, f"Parameter_{parameter}")
                                                else:
                                                    param_name = param_name_map.get(str(parameter).lower(), str(parameter))
                                                
                                                self.db.add_sensor(
                                                    city_id=city_id,
                                                    sensor_id=sensor_id,
                                                    parameter=param_name,
                                                    latitude=sensor_lat,
                                                    longitude=sensor_lon,
                                                    last_value=value,
                                                    last_updated=pollutant_measurement_timestamp,
                                                    is_custom=0,
                                                    custom_info=None
                                                )
                                        except Exception as sensor_err:
                                            self.logger.warning(f"Fel vid sparande av sensor för {city_name}: {sensor_err}")
                            
                            for param in ['pm25', 'pm10', 'no2', 'o3']:
                                if pollutants.get(param) is not None and merged_pollutants[param] is None:
                                    merged_pollutants[param] = pollutants.get(param)
                                    self.logger.info(f"{provider_name}: Fick {param}={pollutants.get(param)} efter väderdata-fel")
                    except Exception as poll_err:
                        self.logger.info(f"{provider_name}: Fel vid pollutant-hämtning efter väderdata-fel: {poll_err}")
            except KeyboardInterrupt:
                self.logger.warning("Uppdatering avbruten")
                break
            except SystemExit:
                self.logger.warning("System avslutas")
                break
            except Exception as e:
                error_msg = str(e)
                provider_name = provider.name if hasattr(provider, 'name') else 'okänd'
                self.logger.debug(f"Provider {provider_name} oväntat fel: {error_msg}")
                continue
        
        # Log collected pollutants
        found_pollutants = [k for k, v in merged_pollutants.items() if v is not None]
        if found_pollutants:
            self.logger.info(f"Samlade pollutant-värden för {city_name}: {found_pollutants}")
        else:
            self.logger.info(f"Inga pollutant-värden hittades för {city_name}. Providers försökte: {', '.join(providers_tried)}")
        
        # Combine data
        if weather_data:
            try:
                
                # Validate data before saving
                temp = weather_data.get('temperature')
                humidity = weather_data.get('humidity')
                wind_speed = weather_data.get('wind_speed')
                source = weather_data.get('source', 'unknown')
                
                if temp is None or humidity is None or wind_speed is None:
                    self.logger.warning(f"Ofullständig väderdata för {city_name}, hoppar över")
                    return
                
                # Separate weather data from pollutant data
                # Weather data: Save always (no timestamp check)
                # Pollutant data: Check timestamp before saving
                
                # Check if we have any pollutants
                has_pollutants = any(v is not None for v in merged_pollutants.values())
                
                # For pollutants: Check if measurement timestamp already exists
                should_save_pollutants = True
                if has_pollutants:
                    if pollutant_measurement_timestamp is not None:
                        # Check if this measurement timestamp already exists in DB
                        if self.db.has_measurement_timestamp(city_id, pollutant_measurement_timestamp):
                            should_save_pollutants = False
                            self.logger.info(f"Skipping duplicate measurement timestamp {pollutant_measurement_timestamp} för {city_name}")
                        else:
                            self.logger.debug(f"Measurement timestamp {pollutant_measurement_timestamp} är ny för {city_name}, kommer spara")
                    else:
                        # No measurement timestamp from API - check if values are identical to last saved
                        # This prevents saving the same model values repeatedly
                        latest_pollutants = self.db.get_latest_pollutant_values(city_id)
                        if latest_pollutants:
                            # Check if all non-None values are identical
                            values_identical = True
                            for param in ['pm25', 'pm10', 'no2', 'o3']:
                                new_val = merged_pollutants.get(param)
                                old_val = latest_pollutants.get(param)
                                if new_val is not None and old_val is not None:
                                    # Compare with small tolerance for floating point
                                    if abs(new_val - old_val) > 0.001:
                                        values_identical = False
                                        break
                                elif new_val is not None or old_val is not None:
                                    # One is None, other is not - not identical
                                    values_identical = False
                                    break
                            
                            if values_identical:
                                should_save_pollutants = False
                                self.logger.info(f"Skipping identical pollutant values för {city_name} (no measurement timestamp, values unchanged)")
                            else:
                                self.logger.debug(f"Pollutant values changed för {city_name}, kommer spara (no measurement timestamp)")
                        else:
                            # No previous data, save anyway
                            self.logger.debug(f"No previous pollutant data för {city_name}, kommer spara (no measurement timestamp)")
                
                # Save weather data (always save, use collector timestamp)
                self.logger.debug(f"Sparar väderdata för {city_name} till databas...")
                try:
                    # Save weather data with pollutants only if timestamp is new
                    if should_save_pollutants:
                        # Save with measurement timestamp if available, otherwise collector timestamp
                        self.db.add_weather_data(
                            city_id=city_id,
                            temperature=float(temp),
                            humidity=float(humidity),
                            wind_speed=float(wind_speed),
                            pm25=merged_pollutants.get('pm25'),
                            pm10=merged_pollutants.get('pm10'),
                            no2=merged_pollutants.get('no2'),
                            o3=merged_pollutants.get('o3'),
                            source=str(source),
                            measurement_timestamp=pollutant_measurement_timestamp
                        )
                    else:
                        # Save only weather data (no pollutants) with collector timestamp
                        self.db.add_weather_data(
                            city_id=city_id,
                            temperature=float(temp),
                            humidity=float(humidity),
                            wind_speed=float(wind_speed),
                            pm25=None,
                            pm10=None,
                            no2=None,
                            o3=None,
                            source=str(source)
                        )
                    
                    # Log saved pollutants
                    poll_display = []
                    for param, value in merged_pollutants.items():
                        if value is not None:
                            poll_display.append(f"{param.upper()}={value:.1f}")
                    poll_str = ", ".join(poll_display) if poll_display else "Inga pollutant-värden"
                    
                    if should_save_pollutants or not has_pollutants:
                        self.logger.info(f"Uppdaterade väder för {city_name}: {temp:.1f}°C, {poll_str}")
                    else:
                        self.logger.info(f"Uppdaterade väder för {city_name}: {temp:.1f}°C (pollutants hoppades över - duplicate timestamp)")
                        
                except Exception as db_error:
                    self.logger.error(f"Fel vid sparande till databas för {city_name}: {db_error}")
            except Exception as combine_error:
                self.logger.error(f"Fel vid kombination av väderdata för {city_name}: {combine_error}")
        else:
            self.logger.warning(f"Kunde inte hämta väderdata för {city_name} (providers försökte: {', '.join(providers_tried)})")
    
    # Analytics operations
    def get_rankings(self, timeframe: str = '24h') -> Dict:
        """Get rankings."""
        return self.analyzer.get_rankings(timeframe)
    
    def get_city_trend(self, city_id: int, hours: int = 24) -> List[Dict]:
        """Get city trend data."""
        return self.analyzer.get_city_trend(city_id, hours)
    
    def get_all_cities_averages(self, timeframe: str = 'latest') -> Dict:
        """Get average values across all cities."""
        return self.analyzer.get_all_cities_averages(timeframe)
    
    def get_national_warning_status(self) -> Dict:
        """Get national warning status."""
        return self.analyzer.get_national_warning_status()
    
    def get_regional_warnings(self) -> List[Dict]:
        """Get regional warnings."""
        return self.analyzer.get_regional_warnings()
    
    def get_max_pm25_cities(self, limit: int = 10) -> List[Dict]:
        """Get cities with highest PM2.5."""
        return self.analyzer.get_max_pm25_cities(limit)
    
    def get_warning_statistics(self) -> Dict:
        """Get warning statistics."""
        return self.analyzer.get_warning_statistics()
    
    # Provider status
    def get_provider_status(self) -> Dict:
        """Get status of all providers."""
        status = {}
        
        if self.openmeteo:
            status['openmeteo'] = {
                'available': self.openmeteo.is_available(),
                'has_key': False
            }
        
        if self.openweather:
            status['openweather'] = {
                'available': self.openweather.is_available(),
                'has_key': bool(self.config.get_api_key("openweather"))
            }
        
        if self.openaq:
            status['openaq'] = {
                'available': self.openaq.is_available(),
                'has_key': bool(self.config.get_api_key("openaq"))
            }
        
        return status
    
    # Log operations
    def get_logs(self, limit: Optional[int] = None) -> List[str]:
        """Get log messages."""
        return self.logger.get_log_messages(limit)
    
    def clear_logs(self):
        """Clear logs."""
        self.logger.clear_logs()
