"""Main weather controller (MVC pattern)."""

import threading
from typing import List, Dict, Optional, Tuple
from PyQt5.QtCore import QObject, pyqtSignal
from database.db_manager import DatabaseManager, WEATHER_DATA_EXTENDED_OPTIONAL_COLUMNS
from utils.config_loader import ConfigLoader
from utils.logger import WeatherLogger
from providers.openmeteo_provider import OpenMeteoProvider
from providers.openaq_provider import OpenAQProvider
import math
from analytics.analyzer import WeatherAnalyzer
from analytics.derived_metrics import DerivedMetricsCalculator, ANALYTICAL_INPUTS
from utils.parameter_formatter import format_parameter_name
from pathlib import Path
from utils import log_analyzer


def _extended_weather_field_kwargs(data: Optional[Dict]) -> Dict:
    """Non-None extended columns present on provider dict (matches weather_data schema)."""
    if not data:
        return {}
    return {
        k: data[k]
        for k in WEATHER_DATA_EXTENDED_OPTIONAL_COLUMNS
        if k in data and data[k] is not None
    }


class WeatherController(QObject):
    """Main controller connecting GUI, providers, database and analytics."""
    
    # Signal emitted when new data is saved to database
    # Parameters: (city_id: int, data_id: int)
    data_updated = pyqtSignal(int, int)
    
    def __init__(self):
        """Initialize controller."""
        super().__init__()  # Initialize QObject
        # Load configuration
        self.config = ConfigLoader()
        
        # Initialize logger
        self.logger = WeatherLogger()
        self.logger.info("Initialiserar väderapplikation...")
        
        # Initialize database
        self.db = DatabaseManager()
        self.logger.info("Databas initialiserad")
        
        # Initialize providers
        # Priority order: OpenAQ > Open-Meteo
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
            self.openmeteo = OpenMeteoProvider(self.logger, self.db)
            self.providers.append(self.openmeteo)
            self.logger.info("Open-Meteo provider initialiserad")
        except Exception as e:
            self.logger.error(f"Kunde inte initialisera Open-Meteo: {e}")
            self.openmeteo = None
        
        # Initialize analytics
        self.analyzer = WeatherAnalyzer(self.db)
        self.derived_metrics = DerivedMetricsCalculator(self.db)
        
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

    def get_pm25_for_city_or_nearest(
        self, city_id: int, hours: int = 24
    ) -> Tuple[Optional[float], Optional[str], Optional[float]]:
        """
        Get PM2.5 value for a city: own 24h average if available, else nearest station within radius.
        Returns (value, source_label, distance_km). source_label is e.g. "Göteborg (42 km)" when fallback is used.
        """
        value, src_id, src_name, dist_km = self.db.get_parameter_for_city_or_nearest(
            city_id, "pm25", hours=hours
        )
        if value is None:
            return (None, None, None)
        if dist_km is not None and dist_km > 0 and src_name:
            source_label = f"{src_name} ({dist_km:.0f} km)"
        else:
            source_label = None
        return (value, source_label, dist_km)
    
    def update_all_cities(self):
        """Update weather for all cities."""
        cities = self.get_all_cities()
        if not cities:
            self.logger.info("Inga städer att uppdatera")
            return
        
        self.logger.info("=" * 60)
        self.logger.info(f"API-UPPDATERING: Hämtar data för {len(cities)} städer från API:erna...")
        self.logger.info(f"Tillgängliga providers: {[p.name for p in self.providers if hasattr(p, 'name')]}")
        self.logger.info("=" * 60)
        
        # Update in separate thread to avoid blocking GUI
        # Use a safer approach with exception handling
        try:
            thread = threading.Thread(target=self._update_cities_thread, args=(cities,), daemon=True)
            thread.start()
            self.logger.info(f"Uppdateringstråd startad (tråd-ID: {thread.ident})")
        except Exception as e:
            self.logger.error(f"Kunde inte starta uppdateringstråd: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
    
    def _update_cities_thread(self, cities: List[Dict]):
        """Thread function for updating cities."""
        try:
            self.logger.info("=" * 60)
            self.logger.info(f"[TRÅD] Uppdateringstråd startad för {len(cities)} städer")
            self.logger.info(f"[TRÅD] Hämtar data från API:erna (Open-Meteo, OpenAQ, etc.)...")
            self.logger.info("=" * 60)
            
            # Check if batch requests are enabled
            use_batch = self.db.get_calibration_parameter('use_batch_requests')
            use_batch = use_batch is not None and use_batch > 0.5
            
            # Try batch request if enabled and provider supports it
            if use_batch and self.openmeteo and self.openmeteo.supports_batch():
                try:
                    # Get chunk size from calibration_parameters
                    chunk_size = self.db.get_calibration_parameter('batch_chunk_size')
                    if chunk_size is None:
                        chunk_size = 10  # Default
                    else:
                        chunk_size = int(chunk_size)
                    
                    self.logger.info(f"[API] Använder batch request för {len(cities)} städer (chunk size: {chunk_size})")
                    self.logger.info(f"[API] Hämtar data från Open-Meteo API nu...")
                    batch_data = self.openmeteo.get_batch_weather(cities, chunk_size=chunk_size)
                    self.logger.info(f"[API] ✓ Batch request klar, fick data för {len(batch_data)} städer")
                    
                    # Process batch results - SAVE TO DATABASE
                    saved_count = 0
                    for city in cities:
                        city_id = city['id']
                        city_name = city.get('name', 'okänd stad')
                        
                        if city_id in batch_data:
                            data = batch_data[city_id]
                            # Save data directly to database
                            try:
                                self.logger.info(f"[SPARA] Sparar batch data för {city_name} till databas...")
                                self._save_weather_data_from_dict(city, data)
                                saved_count += 1
                            except Exception as e:
                                self.logger.error(f"Fel vid sparande av batch data för {city_name}: {e}")
                        else:
                            self.logger.warning(f"Inga batch data för {city_name}, försöker individuell request")
                            # Fallback to individual request
                            try:
                                self._update_city_weather(city)
                            except Exception as e:
                                self.logger.error(f"Fel vid individuell uppdatering av {city_name}: {e}")
                    
                    self.logger.info("Batch uppdatering klar")
                    return
                except Exception as e:
                    self.logger.warning(f"Batch request misslyckades, fallback till individuella requests: {e}")
            
            # Individual requests (fallback or if batch disabled)
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
            
            self.logger.info("=" * 60)
            self.logger.info("API-UPPDATERING KLAR: Alla städer uppdaterade från API:erna")
            self.logger.info("=" * 60)

            # Update lightning events after all cities have been refreshed
            try:
                self.logger.info("Uppdaterar lightning events efter väderuppdatering...")
                self._update_lightning_events()
            except Exception as e:
                import traceback
                self.logger.error(f"Fel vid uppdatering av lightning events: {e}")
                self.logger.error(f"Traceback: {traceback.format_exc()}")

        except Exception as e:
            import traceback
            self.logger.error(f"Kritiskt fel i uppdateringstråd: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
    
    def _save_weather_data_from_dict(self, city: Dict, data: Dict):
        """
        Save weather data from a dictionary (used by batch requests).
        
        Args:
            city: City dictionary with 'id', 'name', 'latitude', 'longitude'
            data: Weather data dictionary from provider
        """
        city_id = city['id']
        city_name = city.get('name', 'okänd stad')
        lat = city.get('latitude')
        lon = city.get('longitude')
        
        # Extract data
        temp = data.get('temperature')
        humidity = data.get('humidity')
        wind_speed = data.get('wind_speed')
        source = data.get('source', 'unknown')
        
        if temp is None or humidity is None or wind_speed is None:
            self.logger.warning(f"Ofullständig väderdata för {city_name}, hoppar över")
            return
        
        # Extract pollutants from data (may be None if batch response doesn't include them)
        pm25 = data.get('pm25')
        pm10 = data.get('pm10')
        no2 = data.get('no2')
        o3 = data.get('o3')
        
        # If pollutants are not in batch data, fetch them separately
        pollutant_measurement_timestamp = data.get('measurement_timestamp')
        if pm25 is None and pm10 is None and no2 is None and o3 is None:
            # Batch response doesn't include pollutants, fetch separately
            self.logger.info(f"[API] Batch data saknar pollutants, hämtar separat för {city_name}")
            
            # Try OpenAQ first (real measurements)
            if self.openaq and lat is not None and lon is not None:
                try:
                    max_age_hours = self.db.get_calibration_parameter('openaq_max_data_age_hours')
                    if max_age_hours is None:
                        max_age_hours = 48.0
                    else:
                        max_age_hours = float(max_age_hours)
                    
                    air_quality_result = self.openaq.get_air_quality(lat, lon, max_age_hours=max_age_hours)
                    if air_quality_result and isinstance(air_quality_result, dict):
                        pollutants = air_quality_result.get("pollutants", {})
                        if pollutants:
                            pm25 = pollutants.get('pm25') if pm25 is None else pm25
                            pm10 = pollutants.get('pm10') if pm10 is None else pm10
                            no2 = pollutants.get('no2') if no2 is None else no2
                            o3 = pollutants.get('o3') if o3 is None else o3
                            if pollutant_measurement_timestamp is None:
                                pollutant_measurement_timestamp = air_quality_result.get("measurement_timestamp")
                            self.logger.info(f"[API] OpenAQ: Fick pollutants för {city_name}: pm25={pm25}, pm10={pm10}, no2={no2}, o3={o3}")
                except Exception as e:
                    self.logger.debug(f"OpenAQ misslyckades för {city_name}: {e}")
            
            # Try OpenMeteo if OpenAQ didn't provide data (endast om Open-Meteo inte är pausad/kvot)
            if (
                (pm25 is None and pm10 is None and no2 is None and o3 is None)
                and self.openmeteo
                and self.openmeteo.is_available()
                and lat is not None
                and lon is not None
            ):
                try:
                    air_quality_result = self.openmeteo.get_air_quality(lat, lon)
                    if air_quality_result and isinstance(air_quality_result, dict):
                        pollutants = air_quality_result.get("pollutants", {})
                        if pollutants:
                            pm25 = pollutants.get('pm25') if pm25 is None else pm25
                            pm10 = pollutants.get('pm10') if pm10 is None else pm10
                            no2 = pollutants.get('no2') if no2 is None else no2
                            o3 = pollutants.get('o3') if o3 is None else o3
                            if pollutant_measurement_timestamp is None:
                                pollutant_measurement_timestamp = air_quality_result.get("measurement_timestamp")
                            self.logger.info(f"[API] OpenMeteo: Fick pollutants för {city_name}: pm25={pm25}, pm10={pm10}, no2={no2}, o3={o3}")
                except Exception as e:
                    self.logger.debug(f"OpenMeteo AQI misslyckades för {city_name}: {e}")
        
        uv_index = data.get('uv_index')
        solar_radiation = data.get('solar_radiation')
        direct_radiation = data.get('direct_radiation')
        diffuse_radiation = data.get('diffuse_radiation')
        sunshine_duration = data.get('sunshine_duration')
        cape = data.get('cape')
        precipitation_probability = data.get('precipitation_probability')
        convective_precipitation = data.get('convective_precipitation')
        measurement_timestamp = data.get('measurement_timestamp')
        
        # Use pollutant measurement timestamp if available, otherwise use weather measurement timestamp
        if pollutant_measurement_timestamp is not None:
            measurement_timestamp = pollutant_measurement_timestamp
        
        # Save weather data
        saved_params = []
        if temp is not None:
            saved_params.append(f"temp={temp}")
        if uv_index is not None:
            saved_params.append(f"uv={uv_index}")
        if solar_radiation is not None:
            saved_params.append(f"solar={solar_radiation}")
        if cape is not None:
            saved_params.append(f"cape={cape}")
        if sunshine_duration is not None:
            saved_params.append(f"sunshine={sunshine_duration}")
        if precipitation_probability is not None:
            saved_params.append(f"precip_prob={precipitation_probability}")
        if convective_precipitation is not None:
            saved_params.append(f"conv_precip={convective_precipitation}")
        
        self.logger.info(f"[SPARA] Sparar data från {source} för {city_name} till databas: {', '.join(saved_params) if saved_params else 'endast grundläggande väderdata'}")
        
        if pm25 is not None or pm10 is not None or no2 is not None or o3 is not None:
            self.logger.info(f"[SPARA] {city_name}: Sparar pollutants: pm25={pm25}, pm10={pm10}, no2={no2}, o3={o3}")
        
        # Log gaps in timestamps if this is not the first data point
        try:
            prev_data = self.db.get_latest_weather(city_id)
            if prev_data and prev_data.get('timestamp'):
                from datetime import datetime
                from zoneinfo import ZoneInfo
                CET = ZoneInfo("Europe/Stockholm")
                
                prev_ts = prev_data['timestamp']
                if isinstance(prev_ts, str):
                    prev_ts = datetime.fromisoformat(prev_ts.replace('Z', '+00:00'))
                
                if measurement_timestamp:
                    gap_hours = (measurement_timestamp - prev_ts).total_seconds() / 3600.0
                    if gap_hours > 2.0:
                        self.logger.debug(f"[SPARA] {city_name}: Gap i data: {gap_hours:.1f} timmar sedan senaste mätning")
        except Exception as e:
            self.logger.debug(f"Kunde inte beräkna timestamp-gap: {e}")
        data_id = self.db.add_weather_data(
            city_id=city_id,
            temperature=float(temp),
            humidity=float(humidity),
            wind_speed=float(wind_speed),
            pm25=pm25,
            pm10=pm10,
            no2=no2,
            o3=o3,
            source=str(source),
            measurement_timestamp=measurement_timestamp,
            timestamp=None,
            uv_index=uv_index,
            solar_radiation=solar_radiation,
            direct_radiation=direct_radiation,
            diffuse_radiation=diffuse_radiation,
            sunshine_duration=sunshine_duration,
            cape=cape,
            precipitation_probability=precipitation_probability,
            convective_precipitation=convective_precipitation,
            **_extended_weather_field_kwargs(data),
        )
        
        if data_id and data_id > 0:
            self.logger.info(f"[SPARA] ✓ Data sparad för {city_name} (data_id={data_id})")
            self.data_updated.emit(city_id, data_id)
            
            # Compute analytical indices AFTER data is saved
            try:
                self._compute_analytical_indices(city_id)
            except Exception as e:
                self.logger.warning(f"Kunde inte beräkna analytical indices för {city_name}: {e}")
        else:
            self.logger.warning(f"[SPARA] ✗ Kunde inte spara data för {city_name} (data_id={data_id})")
    
    def _compute_analytical_indices(self, city_id: int):
        """
        Compute and save analytical indices (solar_index, storm_risk, smog_risk) for a city.
        
        Args:
            city_id: City ID
        """
        try:
            # Calculate solar_index
            solar_index = self.derived_metrics.calculate_solar_index(city_id)
            
            # TODO: Calculate storm_risk and smog_risk in future
            storm_risk = None
            smog_risk = None
            
            # Save to analytical_indices table
            if solar_index is not None or storm_risk is not None or smog_risk is not None:
                self.db.add_analytical_index(
                    city_id=city_id,
                    solar_index=solar_index,
                    storm_risk=storm_risk,
                    smog_risk=smog_risk
                )
                self.logger.debug(f"Saved analytical indices for city {city_id}: solar_index={solar_index}, storm_risk={storm_risk}, smog_risk={smog_risk}")
            else:
                self.logger.debug(f"No analytical indices to save for city {city_id} (insufficient data)")
        except Exception as e:
            self.logger.error(f"Error computing analytical indices for city {city_id}: {e}", exc_info=True)
    
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
        
        # Discover pollutant parameters dynamically from database schema
        # No hardcoding - parameters derived from actual database columns
        # No fallbacks - if schema query fails, return empty list (will be handled gracefully)
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(weather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            # Exclude non-pollutant columns
            excluded = {'id', 'city_id', 'timestamp', 'source', 'aqi', 'measurement_timestamp', 
                       'temperature', 'humidity', 'wind_speed'}
            pollutant_param_names = [col for col in columns if col not in excluded]
            
            if not pollutant_param_names:
                self.logger.warning(f"Inga pollutant-parametrar upptäckta från schema för {city_name}")
        except Exception as e:
            self.logger.error(f"Kunde inte upptäcka pollutant-parametrar från schema: {e}")
            # No fallback - return empty list (will be handled gracefully)
            pollutant_param_names = []
        
        # Initialize merged_pollutants dict dynamically
        merged_pollutants = {param: None for param in pollutant_param_names}
        self.logger.debug(f"Upptäckte {len(pollutant_param_names)} pollutant-parametrar: {pollutant_param_names}")
        
        pollutant_measurement_timestamp = None  # Track measurement timestamp for pollutants
        providers_tried = []
        
        # Priority for weather: Open-Meteo > OpenAQ
        # Priority for pollutants: OpenAQ > Open-Meteo
        provider_priority = {'openaq': 0, 'openmeteo': 1}
        
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
                    # Open-Meteo: is_available() False = t.ex. daglig API-kvot — anropa inte get_air_quality.
                    if provider_name == "openmeteo":
                        self.logger.info(
                            f"{provider_name} är inte tillgänglig — hoppar pollutant-anrop (ingen Open-Meteo-kvot / paus)"
                        )
                        continue
                    self.logger.info(f"{provider_name} är inte tillgänglig, försöker hämta pollutant-data ändå...")
                    # Try to get pollutants separately even if provider reports unavailable (t.ex. OpenAQ)
                    try:
                        # Get max age from calibration parameters (used only for OpenAQ)
                        max_age_hours = self.db.get_calibration_parameter('openaq_max_data_age_hours')
                        if max_age_hours is None:
                            max_age_hours = 48.0  # Default: 48 hours
                        else:
                            max_age_hours = float(max_age_hours)
                        
                        if provider_name == "openaq":
                            air_quality_result = provider.get_air_quality(lat, lon, max_age_hours=max_age_hours)
                        else:
                            air_quality_result = provider.get_air_quality(lat, lon)
                        if air_quality_result and isinstance(air_quality_result, dict):
                            pollutants = air_quality_result.get("pollutants", {})
                            # Extract measurement timestamp if available
                            if pollutant_measurement_timestamp is None:
                                pollutant_measurement_timestamp = air_quality_result.get("measurement_timestamp")
                            
                            # Merge pollutants (keep best available value for each parameter)
                            # Use dynamic parameter list from merged_pollutants keys
                            for param in merged_pollutants.keys():
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
                    self.logger.info(f"[API] Anropar {provider_name}.get_current_weather({lat:.2f}, {lon:.2f}) för {city_name}")
                    data = provider.get_current_weather(lat, lon)
                    if data and isinstance(data, dict):
                        # Log which parameters were actually retrieved
                        retrieved_params = []
                        for param in ['temperature', 'humidity', 'wind_speed', 'uv_index', 'solar_radiation', 
                                     'direct_radiation', 'diffuse_radiation', 'sunshine_duration', 
                                     'cape', 'precipitation_probability', 'convective_precipitation']:
                            if data.get(param) is not None:
                                retrieved_params.append(f"{param}={data.get(param)}")
                        
                        self.logger.info(f"[API] ✓ {provider_name} returnerade data för {city_name}: {', '.join(retrieved_params) if retrieved_params else 'endast grundläggande väderdata'}")
                        # Use first available weather data
                        if weather_data is None and data.get('temperature') is not None:
                            weather_data = data
                            self.logger.debug(f"{provider_name}: Fick väderdata (temp={data.get('temperature')}°C)")
                        
                        # Collect pollutant values from weather data
                        # Use dynamic parameter list from merged_pollutants keys
                        for param in merged_pollutants.keys():
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
                        if provider_name == "openmeteo" and not provider.is_available():
                            self.logger.debug(
                                f"{provider_name}: hoppar separat get_air_quality (ej tillgänglig efter väderanrop / kvot)"
                            )
                        else:
                            try:
                                self.logger.info(f"[DEBUG] Anropar {provider_name}.get_air_quality() separat för {city_name}")
                                # Get max age from calibration parameters (used only for OpenAQ)
                                max_age_hours = self.db.get_calibration_parameter('openaq_max_data_age_hours')
                                if max_age_hours is None:
                                    max_age_hours = 48.0  # Default: 48 hours
                                else:
                                    max_age_hours = float(max_age_hours)
                                
                                if provider_name == "openaq":
                                    self.logger.info(f"[API] Anropar {provider_name}.get_air_quality({lat:.2f}, {lon:.2f}, max_age_hours={max_age_hours}) för {city_name}")
                                    air_quality_result = provider.get_air_quality(lat, lon, max_age_hours=max_age_hours)
                                else:
                                    self.logger.info(f"[API] Anropar {provider_name}.get_air_quality({lat:.2f}, {lon:.2f}) för {city_name}")
                                    air_quality_result = provider.get_air_quality(lat, lon)
                                if air_quality_result and isinstance(air_quality_result, dict):
                                    pollutants = air_quality_result.get("pollutants", {})
                                    self.logger.info(f"[API] {provider_name} returnerade pollutants: {pollutants}")
                                    # Extract measurement timestamp if available
                                    if pollutant_measurement_timestamp is None:
                                        pollutant_measurement_timestamp = air_quality_result.get("measurement_timestamp")
                                        if pollutant_measurement_timestamp:
                                            self.logger.info(f"[API] {provider_name} measurement_timestamp: {pollutant_measurement_timestamp}")
                                    
                                    # Save sensors to database if OpenAQ returned sensor data
                                    if provider_name == "openaq" and "sensors" in air_quality_result:
                                        sensors_data = air_quality_result.get("sensors", [])
                                        if sensors_data:
                                            self.logger.info(f"[API] OpenAQ: Sparar {len(sensors_data)} sensorer för {city_name}")
                                            for sensor in sensors_data:
                                                try:
                                                    sensor_id = sensor.get("sensor_id")
                                                    parameter = sensor.get("parameter")
                                                    coords = sensor.get("coordinates", {})
                                                    sensor_lat = coords.get("latitude")
                                                    sensor_lon = coords.get("longitude")
                                                    value = sensor.get("value")
                                                    
                                                    if sensor_id and sensor_lat is not None and sensor_lon is not None:
                                                        # Format parameter name dynamically (no hardcoded IDs)
                                                        # Parameter can be int (ID) or string (name) from API
                                                        if isinstance(parameter, int):
                                                            # If parameter is an ID, we can't format it without name
                                                            # Use the parameter value as-is and let formatter handle it
                                                            param_name = format_parameter_name(str(parameter))
                                                        else:
                                                            # Parameter is already a name string from API
                                                            param_name = format_parameter_name(str(parameter))
                                                        
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
                                    # Use dynamic parameter list from merged_pollutants keys
                                    for param in merged_pollutants.keys():
                                        if pollutants.get(param) is not None:
                                            # Use value if we don't have one
                                            if merged_pollutants[param] is None:
                                                merged_pollutants[param] = pollutants.get(param)
                                                self.logger.info(f"[API] {provider_name}: ✓ Fick {param}={pollutants.get(param)} separat")
                                            else:
                                                self.logger.debug(f"[API] {provider_name}: {param} redan satt ({merged_pollutants[param]}), hoppar över")
                                        else:
                                            self.logger.debug(f"[API] {provider_name}: {param} är None i pollutants dict")
                            except Exception as poll_err:
                                self.logger.info(f"{provider_name}: Fel vid separat pollutant-hämtning: {poll_err}")
                except Exception as weather_error:
                    error_msg = str(weather_error)
                    self.logger.info(f"{provider_name}: Fel vid hämtning av väderdata: {error_msg}")
                    if provider_name == "openmeteo":
                        try:
                            if not provider.is_available():
                                self.logger.debug(
                                    f"{provider_name}: hoppar pollutant-fallback (ej tillgänglig / kvot)"
                                )
                                continue
                        except Exception:
                            pass
                    # Try to get pollutants separately as fallback
                    try:
                        # Get max age from calibration parameters (used only for OpenAQ)
                        max_age_hours = self.db.get_calibration_parameter('openaq_max_data_age_hours')
                        if max_age_hours is None:
                            max_age_hours = 48.0  # Default: 48 hours
                        else:
                            max_age_hours = float(max_age_hours)
                        
                        if provider_name == "openaq":
                            air_quality_result = provider.get_air_quality(lat, lon, max_age_hours=max_age_hours)
                        else:
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
                                                # Format parameter name dynamically (no hardcoded IDs)
                                                # Parameter can be int (ID) or string (name) from API
                                                if isinstance(parameter, int):
                                                    # If parameter is an ID, we can't format it without name
                                                    # Use the parameter value as-is and let formatter handle it
                                                    param_name = format_parameter_name(str(parameter))
                                                else:
                                                    # Parameter is already a name string from API
                                                    param_name = format_parameter_name(str(parameter))
                                                
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
                            
                            # Use dynamic parameter list from merged_pollutants keys
                            for param in merged_pollutants.keys():
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
                
                # Validate wind_speed value (0-30 m/s is reasonable for Sweden)
                if wind_speed is not None:
                    try:
                        wind_speed_float = float(wind_speed)
                        if wind_speed_float < 0:
                            self.logger.warning(
                                f"{city_name}: Negativt wind_speed-värde från provider: {wind_speed_float} m/s "
                                f"(source={source}). Använder 0.0 istället."
                            )
                            wind_speed = 0.0
                        elif wind_speed_float > 30.0:
                            self.logger.warning(
                                f"{city_name}: Ovanligt högt wind_speed-värde från provider: {wind_speed_float} m/s "
                                f"(source={source}). Kan vara korrekt vid extrem storm, men bör verifieras."
                            )
                        elif wind_speed_float > 20.0:
                            self.logger.warning(
                                f"{city_name}: Högt wind_speed-värde från provider: {wind_speed_float} m/s "
                                f"(source={source}). Kan vara korrekt vid storm, men bör verifieras."
                            )
                        self.logger.debug(
                            f"{city_name}: Validerat wind_speed={wind_speed_float:.2f} m/s från {source} "
                            f"(kommer sparas i databas)"
                        )
                    except (ValueError, TypeError) as e:
                        self.logger.warning(
                            f"{city_name}: Kunde inte konvertera wind_speed till float: {wind_speed} (error: {e})"
                        )
                        return
                
                # Separate weather data from pollutant data
                # Weather data: Save always (no timestamp check)
                # Pollutant data: Check timestamp before saving
                
                # Check if we have any pollutants
                has_pollutants = any(v is not None for v in merged_pollutants.values())
                all_pollutants_none = all(v is None for v in merged_pollutants.values())
                
                # Log pollutant availability
                if all_pollutants_none:
                    self.logger.warning(f"[SPARA] {city_name}: ⚠ Inga pollutant-värden från API:er (alla None) - detta skiljer sig från 'värde är 0'")
                    self.logger.warning(f"[SPARA] {city_name}: merged_pollutants = {merged_pollutants}")
                elif has_pollutants:
                    poll_display = [f"{k.upper()}={v:.1f}" for k, v in merged_pollutants.items() if v is not None]
                    self.logger.info(f"[SPARA] {city_name}: ✓ Har pollutant-värden: {', '.join(poll_display)}")
                    self.logger.info(f"[SPARA] {city_name}: merged_pollutants = {merged_pollutants}")
                
                # For pollutants: Check if measurement timestamp already exists AND values are identical
                # Core principle: If merged_pollutants has values, ALWAYS save them
                should_save_pollutants = True
                if has_pollutants:
                    if pollutant_measurement_timestamp is not None:
                        # Check if this measurement timestamp already exists in DB
                        if self.db.has_measurement_timestamp(city_id, pollutant_measurement_timestamp):
                            # Timestamp exists - check if values are ALSO identical
                            latest_pollutants = self.db.get_latest_pollutant_values(city_id)
                            if latest_pollutants:
                                # Compare values with tolerance for floating point
                                # Use dynamic parameter list from merged_pollutants keys
                                values_identical = True
                                for param in merged_pollutants.keys():
                                    new_val = merged_pollutants.get(param)
                                    old_val = latest_pollutants.get(param)
                                    if new_val is not None and old_val is not None:
                                        # Both have values - compare with tolerance
                                        if abs(new_val - old_val) > 0.001:
                                            values_identical = False
                                            break
                                    elif new_val is not None or old_val is not None:
                                        # One is None, other is not - not identical
                                        values_identical = False
                                        break
                                
                                if values_identical:
                                    # True duplicate: same timestamp AND same values
                                    should_save_pollutants = False
                                    self.logger.info(f"Skipping true duplicate för {city_name}: timestamp {pollutant_measurement_timestamp} och identiska värden")
                                else:
                                    # Different values: save with collector timestamp (new entry)
                                    self.logger.debug(f"{city_name}: Timestamp duplicate men värden ändrade - sparar med collector timestamp")
                                    pollutant_measurement_timestamp = None  # Use collector timestamp
                                    should_save_pollutants = True
                            else:
                                # No previous data, save anyway
                                self.logger.debug(f"{city_name}: Timestamp duplicate men ingen tidigare data - sparar ändå")
                                should_save_pollutants = True
                        else:
                            # New timestamp, save
                            self.logger.debug(f"Measurement timestamp {pollutant_measurement_timestamp} är ny för {city_name}, kommer spara")
                            should_save_pollutants = True
                    else:
                        # No measurement timestamp from API - always save pollutant values
                        # Even if values are identical, we should save them to ensure UI shows current data
                        # The timestamp will be different (collector timestamp), so it's a new measurement
                        self.logger.debug(f"No measurement timestamp för {city_name}, kommer spara pollutants med collector timestamp")
                        should_save_pollutants = True
                
                # Final guard: Never skip saving if we have pollutant values
                # This ensures pollutants are ALWAYS saved when available, even if deduplication logic fails
                if has_pollutants and not should_save_pollutants:
                    self.logger.warning(f"{city_name}: should_save_pollutants=False men merged_pollutants har värden - override till True för att säkerställa UI-uppdatering")
                    should_save_pollutants = True
                    # Use collector timestamp to ensure new entry
                    pollutant_measurement_timestamp = None
                
                # Save weather data (always save, use collector timestamp)
                # Always save with current timestamp to ensure UI updates even if values are identical
                self.logger.info(f"[SPARA] Sparar väderdata för {city_name} till databas (source={source})...")
                try:
                    data_id = None
                    # Extract solar and storm parameters from weather_data
                    uv_index = weather_data.get('uv_index')
                    solar_radiation = weather_data.get('solar_radiation')
                    direct_radiation = weather_data.get('direct_radiation')
                    diffuse_radiation = weather_data.get('diffuse_radiation')
                    sunshine_duration = weather_data.get('sunshine_duration')
                    cape = weather_data.get('cape')
                    precipitation_probability = weather_data.get('precipitation_probability')
                    convective_precipitation = weather_data.get('convective_precipitation')
                    
                    self.logger.info(f"[SPARA] Extraherade parametrar: uv={uv_index}, solar={solar_radiation}, cape={cape}, sunshine={sunshine_duration}")
                    
                    # Save weather data with pollutants if should_save_pollutants is True
                    if should_save_pollutants:
                        # Log what we're saving
                        pm25_val = merged_pollutants.get('pm25')
                        pm10_val = merged_pollutants.get('pm10')
                        no2_val = merged_pollutants.get('no2')
                        o3_val = merged_pollutants.get('o3')
                        self.logger.info(f"[SPARA] {city_name}: Sparar pollutants: pm25={pm25_val}, pm10={pm10_val}, no2={no2_val}, o3={o3_val}")
                        
                        # Save with measurement timestamp if available, otherwise collector timestamp (current time)
                        data_id = self.db.add_weather_data(
                            city_id=city_id,
                            temperature=float(temp),
                            humidity=float(humidity),
                            wind_speed=float(wind_speed),
                            pm25=pm25_val,
                            pm10=pm10_val,
                            no2=no2_val,
                            o3=o3_val,
                            source=str(source),
                            measurement_timestamp=pollutant_measurement_timestamp,
                            timestamp=None,  # Use current time (collector timestamp) to ensure new entry
                            # Solar parameters
                            uv_index=uv_index,
                            solar_radiation=solar_radiation,
                            direct_radiation=direct_radiation,
                            diffuse_radiation=diffuse_radiation,
                            sunshine_duration=sunshine_duration,
                            # Storm parameters
                            cape=cape,
                            precipitation_probability=precipitation_probability,
                            convective_precipitation=convective_precipitation,
                            **_extended_weather_field_kwargs(weather_data),
                        )
                    else:
                        # Save only weather data (no pollutants) with collector timestamp (current time)
                        # This ensures UI updates even when pollutant values haven't changed
                        data_id = self.db.add_weather_data(
                            city_id=city_id,
                            temperature=float(temp),
                            humidity=float(humidity),
                            wind_speed=float(wind_speed),
                            pm25=None,
                            pm10=None,
                            no2=None,
                            o3=None,
                            source=str(source),
                            timestamp=None,  # Use current time to ensure new entry and UI refresh
                            # Solar parameters
                            uv_index=uv_index,
                            solar_radiation=solar_radiation,
                            direct_radiation=direct_radiation,
                            diffuse_radiation=diffuse_radiation,
                            sunshine_duration=sunshine_duration,
                            # Storm parameters
                            cape=cape,
                            precipitation_probability=precipitation_probability,
                            convective_precipitation=convective_precipitation,
                            **_extended_weather_field_kwargs(weather_data),
                        )
                    
                    # Emit signal if data was successfully saved (data_id > 0)
                    if data_id and data_id > 0:
                        self.logger.info(f"[SPARA] ✓ Data sparad för {city_name} (data_id={data_id}, uv={uv_index}, solar={solar_radiation})")
                        self.data_updated.emit(city_id, data_id)
                        
                        # Compute analytical indices AFTER data is saved
                        try:
                            self._compute_analytical_indices(city_id)
                        except Exception as e:
                            self.logger.warning(f"Kunde inte beräkna analytical indices för {city_name}: {e}")
                    else:
                        self.logger.warning(f"[SPARA] ✗ Kunde inte spara data för {city_name} (data_id={data_id})")
                    
                    # Log saved pollutants with detailed information
                    poll_display = []
                    for param, value in merged_pollutants.items():
                        if value is not None:
                            poll_display.append(f"{param.upper()}={value:.1f}")
                    poll_str = ", ".join(poll_display) if poll_display else "Inga pollutant-värden"
                    
                    # Detailed logging based on what was saved
                    if should_save_pollutants:
                        if has_pollutants:
                            if pollutant_measurement_timestamp:
                                self.logger.info(f"Uppdaterade väder för {city_name}: {temp:.1f}°C, {poll_str} (measurement timestamp: {pollutant_measurement_timestamp})")
                            else:
                                self.logger.info(f"Uppdaterade väder för {city_name}: {temp:.1f}°C, {poll_str} (collector timestamp)")
                        else:
                            self.logger.info(f"Uppdaterade väder för {city_name}: {temp:.1f}°C (pollutants: {poll_str})")
                    else:
                        # This should never happen due to guard clause, but log if it does
                        self.logger.warning(f"Uppdaterade väder för {city_name}: {temp:.1f}°C (pollutants hoppades över - detta borde inte hända)")
                        
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
    
    def _compute_analytical_indices(self, city_id: int):
        """
        Compute analytical indices (solar_index, storm_risk, smog_risk) for a city.
        
        Args:
            city_id: City ID
        """
        try:
            from analytics.solar_index import SolarIndexCalculator
            from analytics.storm_risk import StormRiskCalculator
            from analytics.smog_risk import SmogRiskCalculator
            
            self.logger.debug(f"[ANALYTICS] Beräknar analytical indices för stad {city_id}")
            solar_calc = SolarIndexCalculator(self.db)
            storm_calc = StormRiskCalculator(self.db)
            smog_calc = SmogRiskCalculator(self.db)
            
            # Get latest weather data to validate inputs
            weather_data = self.db.get_latest_weather(city_id)
            if not weather_data:
                self.logger.debug(f"[ANALYTICS] Inga väderdata för stad {city_id}, hoppar över analytical indices")
                return
            
            self.logger.debug(
                f"[ANALYTICS] Tillgängliga nycklar för stad {city_id}: {sorted(weather_data.keys())}"
            )
            
            # Validate storm_risk inputs before calculating
            storm_required = ['cape', 'convective_precipitation', 'precipitation_probability', 'humidity', 'wind_speed']
            storm_missing = [p for p in storm_required if weather_data.get(p) is None]
            if storm_missing:
                self.logger.debug(f"[ANALYTICS] Kan inte beräkna storm_risk för stad {city_id}: saknar {storm_missing}")
                storm_risk = None
            else:
                self.logger.debug(
                    "[ANALYTICS] storm_risk inputs för stad %s: cape=%s conv_precip=%s precip_prob=%s hum=%s wind=%s",
                    city_id,
                    weather_data.get('cape'),
                    weather_data.get('convective_precipitation'),
                    weather_data.get('precipitation_probability'),
                    weather_data.get('humidity'),
                    weather_data.get('wind_speed'),
                )
                storm_risk = storm_calc.calculate(city_id)
            
            # Calculate other indices (they handle their own validation)
            solar_index = solar_calc.calculate(city_id)
            smog_risk = smog_calc.calculate(city_id)
            
            self.logger.debug(
                f"[ANALYTICS] Resultat för stad {city_id}: solar_index={solar_index} storm_risk={storm_risk} smog_risk={smog_risk}"
            )
            
            # Store indices in database
            if solar_index is not None or storm_risk is not None or smog_risk is not None:
                self.db.add_analytical_index(
                    city_id=city_id,
                    solar_index=solar_index,
                    storm_risk=storm_risk,
                    smog_risk=smog_risk
                )
                self.logger.debug(f"[ANALYTICS] Analytical indices sparade för stad {city_id}")
            else:
                self.logger.debug(f"[ANALYTICS] Inga analytical indices att spara för stad {city_id}")
        except RuntimeError as e:
            # Re-raise RuntimeError (missing calibration parameters)
            raise
        except Exception as e:
            self.logger.warning(f"Fel vid beräkning av analytical indices för stad {city_id}: {e}", exc_info=True)
    
    def _update_lightning_events(self):
        """
        Update lightning events for all cities.
        
        Reads lightning provider configuration from calibration_parameters.
        """
        try:
            # Get lightning provider configuration
            provider_type = self.db.get_calibration_parameter('lightning_provider_type')
            if provider_type is None:
                self.logger.warning("lightning_provider_type not found in calibration_parameters")
                return
            
            api_key = self.db.get_calibration_parameter('lightning_api_key')  # May be None
            
            from providers.lightning_provider import LightningProvider
            lightning_provider = LightningProvider(
                provider_type=int(provider_type),
                api_key=api_key if api_key else None,
                logger=self.logger
            )
            
            if not lightning_provider.is_available():
                self.logger.warning("Lightning provider is not available")
                return
            
            # Get all cities
            cities = self.db.get_all_cities()
            if not cities:
                return
            
            # Calculate bounding box for all cities
            lats = [city['latitude'] for city in cities]
            lons = [city['longitude'] for city in cities]
            min_lat = min(lats)
            max_lat = max(lats)
            min_lon = min(lons)
            max_lon = max(lons)
            
            # Get lightning strikes in bounding box
            strikes = lightning_provider.get_lightning_strikes_bbox(min_lat, max_lat, min_lon, max_lon)
            
            if not strikes:
                self.logger.debug("No lightning strikes found")
                return
            
            # Store strikes in database
            from datetime import datetime
            from zoneinfo import ZoneInfo
            CET = ZoneInfo("Europe/Stockholm")
            
            for strike in strikes:
                try:
                    # Find nearest city for this strike
                    strike_lat = strike['latitude']
                    strike_lon = strike['longitude']
                    strike_time = strike.get('timestamp', datetime.now(CET))
                    
                    # Calculate distance to each city and find nearest
                    min_distance = float('inf')
                    nearest_city_id = None
                    
                    for city in cities:
                        city_lat = city['latitude']
                        city_lon = city['longitude']
                        
                        # Simple distance calculation (Haversine would be better but this is faster)
                        import math
                        lat_diff = abs(strike_lat - city_lat)
                        lon_diff = abs(strike_lon - city_lon)
                        distance = math.sqrt(lat_diff**2 + lon_diff**2) * 111.0  # Rough km conversion
                        
                        if distance < min_distance:
                            min_distance = distance
                            nearest_city_id = city['id']
                    
                    # Store lightning event
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO lightning_events 
                        (timestamp, latitude, longitude, intensity, distance_km, city_id, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        strike_time,
                        strike_lat,
                        strike_lon,
                        strike.get('intensity'),
                        min_distance,
                        nearest_city_id,
                        lightning_provider.name
                    ))
                    conn.commit()
                    
                except Exception as e:
                    self.logger.warning(f"Fel vid sparande av lightning event: {e}")
                    continue
            
            self.logger.info(f"Sparade {len(strikes)} lightning events")
            
        except Exception as e:
            self.logger.error(f"Fel vid uppdatering av lightning events: {e}")
    
    def get_max_pm25_cities(self, limit: int = 10) -> List[Dict]:
        """Get cities with highest PM2.5."""
        return self.analyzer.get_max_pm25_cities(limit)
    
    def get_warning_statistics(self) -> Dict:
        """Get warning statistics."""
        return self.analyzer.get_warning_statistics()
    
    def generate_dynamic_debug_report(self, city_id: Optional[int] = None) -> Dict:
        """
        Generate a dynamic, log-driven debug report.

        Combines:
            - Log-analys (providers, schemafel m.m.)
            - Databasschema/migrationsstatus
            - Saknade calibration-nycklar (dynamiskt upptäckta)
            - Analytiska inputs vs faktiskt tillgänglig data
        """
        report: Dict[str, Any] = {
            "city_id": city_id,
            "providers": {},
            "schema": {},
            "calibration": {},
            "analytics": {},
            "logs": {},
        }

        # 1) Logganalys
        try:
            project_root = Path(__file__).resolve().parent.parent
            log_dir = project_root / "logs"
            logs_report = log_analyzer.analyze_logs(log_dir)
            report["logs"] = logs_report
            report["providers"] = log_analyzer.summarize_providers(logs_report)
            report["schema"]["log_issues"] = log_analyzer.summarize_schema_issues(
                logs_report
            )
        except Exception as e:
            self.logger.warning(f"generate_dynamic_debug_report: log analysis failed: {e}")

        # 2) Databashälsa
        try:
            schema_health = self.db.get_schema_health()
            report["schema"]["health"] = schema_health
        except Exception as e:
            self.logger.warning(f"generate_dynamic_debug_report: schema health failed: {e}")

        # 3) Saknade calibration-nycklar (dynamiskt upptäckta från analytics-kod)
        try:
            missing_calib = self.db.get_missing_calibration_keys()
            report["calibration"]["missing_keys"] = missing_calib
        except Exception as e:
            self.logger.warning(
                f"generate_dynamic_debug_report: missing calibration keys failed: {e}"
            )

        # 4) Analytiska inputs vs faktisk data för vald stad
        try:
            analytics_info: Dict[str, Any] = {"inputs": ANALYTICAL_INPUTS, "per_index": {}}
            if city_id is not None:
                # Re-use befintlig debug-metod för väder/analytical-data
                try:
                    city_debug = self.db.debug_analytical_data(city_id)
                except Exception:
                    city_debug = None

                latest_weather = (
                    city_debug.get("latest_weather_data") if city_debug else None
                )

                for index_name, params in ANALYTICAL_INPUTS.items():
                    index_entry: Dict[str, Any] = {"required_params": params, "missing": []}
                    if latest_weather:
                        for p in params:
                            if latest_weather.get(p) is None:
                                index_entry["missing"].append(p)
                    analytics_info["per_index"][index_name] = index_entry

            report["analytics"] = analytics_info
        except Exception as e:
            self.logger.warning(
                f"generate_dynamic_debug_report: analytics inspection failed: {e}"
            )

        return report
    
    def debug_all_issues(self, city_id: int) -> Dict:
        """
        Debug all issues for a city.
        
        Args:
            city_id: City ID
            
        Returns:
            Dictionary with debug information:
            - providers_available: List of available providers
            - latest_weather: Latest weather data dict
            - missing_solar_params: List of missing parameters for solar_index
            - missing_storm_params: List of missing parameters for storm_risk
            - data_coverage: Data coverage statistics
            - issues: List of identified issues
        """
        debug_info = {
            'providers_available': [],
            'latest_weather': None,
            'missing_solar_params': [],
            'missing_storm_params': [],
            'data_coverage': {},
            'issues': []
        }
        
        # Check providers
        if self.openaq and self.openaq.is_available():
            debug_info['providers_available'].append('openaq')
        if self.openmeteo and self.openmeteo.is_available():
            debug_info['providers_available'].append('openmeteo')
        
        if not debug_info['providers_available']:
            debug_info['issues'].append("Inga providers är tillgängliga")
        
        # Get latest weather data
        weather_data = self.db.get_latest_weather(city_id)
        if not weather_data:
            debug_info['issues'].append("Ingen weather_data för denna stad")
            return debug_info
        
        debug_info['latest_weather'] = weather_data
        
        # Check solar_index parameters
        solar_required = ['solar_radiation', 'uv_index', 'sunshine_duration']
        for param in solar_required:
            if weather_data.get(param) is None:
                debug_info['missing_solar_params'].append(param)
        
        if debug_info['missing_solar_params']:
            debug_info['issues'].append(f"Saknade parametrar för solar_index: {debug_info['missing_solar_params']}")
        
        # Check storm_risk parameters
        storm_required = ['cape', 'convective_precipitation', 'precipitation_probability', 'humidity', 'wind_speed']
        for param in storm_required:
            if weather_data.get(param) is None:
                debug_info['missing_storm_params'].append(param)
        
        if debug_info['missing_storm_params']:
            debug_info['issues'].append(f"Saknade parametrar för storm_risk: {debug_info['missing_storm_params']}")
        
        # Check data coverage (last 24 hours)
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        CET = ZoneInfo("Europe/Stockholm")
        
        cutoff = datetime.now(CET) - timedelta(hours=24)
        all_data = self.db.get_weather_data_for_city(city_id, hours=24)
        
        if all_data:
            timestamps = [row.get('timestamp') for row in all_data if row.get('timestamp')]
            if timestamps:
                from datetime import datetime
                try:
                    # Convert to datetime if needed
                    dt_timestamps = []
                    for ts in timestamps:
                        if isinstance(ts, str):
                            dt_timestamps.append(datetime.fromisoformat(ts.replace('Z', '+00:00')))
                        elif isinstance(ts, datetime):
                            dt_timestamps.append(ts)
                    
                    if dt_timestamps:
                        time_span = (max(dt_timestamps) - min(dt_timestamps)).total_seconds() / 3600.0
                        expected_span = 24.0
                        coverage = (time_span / expected_span) * 100.0 if expected_span > 0 else 0
                        
                        debug_info['data_coverage'] = {
                            'data_points': len(all_data),
                            'time_span_hours': time_span,
                            'coverage_percent': coverage,
                            'gaps_detected': len(timestamps) < 24  # Rough estimate
                        }
                        
                        if coverage < 10.0:
                            debug_info['issues'].append(f"Mycket sparse data: endast {coverage:.1f}% coverage över 24h")
                except Exception as e:
                    self.logger.debug(f"Kunde inte beräkna data coverage: {e}")
        
        return debug_info
    
    # Provider status
    def get_provider_status(self) -> Dict:
        """Get status of all providers."""
        status = {}
        
        if self.openmeteo:
            status['openmeteo'] = {
                'available': self.openmeteo.is_available(),
                'has_key': False
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
