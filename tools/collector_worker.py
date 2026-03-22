"""Background collector worker for polling external APIs and writing into the database.

This worker:
    - never touches GUI directly,
    - uses DatabaseManager,
    - relies on existing providers (OpenAQProvider, OpenMeteoProvider),
    - is configured dynamically via calibration_parameters (no hardcoded magic values).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

from database.db_manager import DatabaseManager, WEATHER_DATA_EXTENDED_OPTIONAL_COLUMNS
from providers.openaq_provider import OpenAQProvider
from providers.openmeteo_provider import OpenMeteoProvider
from utils.config_loader import ConfigLoader
from utils.logger import WeatherLogger


CET = ZoneInfo("Europe/Stockholm")


class CollectorWorker:
    """Central collector for API polling."""

    def __init__(self, db: Optional[DatabaseManager] = None, logger: Optional[WeatherLogger] = None) -> None:
        self.db = db or DatabaseManager()
        self.logger = logger or WeatherLogger()
        self.config = ConfigLoader()

        # Providers are initialized lazily; OpenAQ may be missing API key.
        self._openaq: Optional[OpenAQProvider] = None
        self._openmeteo: Optional[OpenMeteoProvider] = None
        self._init_providers()

    def _init_providers(self) -> None:
        # OpenAQ
        try:
            api_key = self.config.get_api_key("openaq")
            if api_key:
                self._openaq = OpenAQProvider(api_key, self.logger)
                self.logger.info("CollectorWorker: OpenAQ provider initialiserad")
            else:
                self.logger.info("CollectorWorker: OpenAQ API-nyckel saknas, hoppar över OpenAQ")
        except Exception as e:
            self.logger.warning(f"CollectorWorker: kunde inte initialisera OpenAQ: {e}")
            self._openaq = None

        # Open-Meteo
        try:
            self._openmeteo = OpenMeteoProvider(self.logger, self.db)
            self.logger.info("CollectorWorker: Open-Meteo provider initialiserad")
        except Exception as e:
            self.logger.warning(f"CollectorWorker: kunde inte initialisera Open-Meteo: {e}")
            self._openmeteo = None

    def _get_collector_interval(self) -> int:
        """Read collector interval (seconds) from calibration_parameters."""
        try:
            val = self.db.get_calibration_parameter("collector_interval_seconds")
            if val is None:
                return 300  # 5 min default, but still DB-driven if key is set
            return int(float(val))
        except Exception:
            return 300

    def _get_openaq_location_ttl_hours(self) -> float:
        """Read OpenAQ location cache TTL in hours from calibration_parameters."""
        try:
            val = self.db.get_calibration_parameter("openaq_location_ttl_hours")
            if val is None:
                return 24.0
            return float(val)
        except Exception:
            return 24.0

    def _ensure_openaq_location(self, city: Dict[str, Any]) -> Optional[int]:
        """
        Ensure we have a valid OpenAQ location_id cached for the given city.

        Returns:
            location_id or None if lookup failed or OpenAQ is not available.
        """
        if not self._openaq:
            return None

        city_id = city["id"]
        lat = city["latitude"]
        lon = city["longitude"]

        row = self.db.get_openaq_location(city_id)
        ttl_hours = self._get_openaq_location_ttl_hours()

        if row is not None:
            try:
                last_verified_raw = row["last_verified"]
                last_verified = (
                    datetime.fromisoformat(last_verified_raw)
                    if isinstance(last_verified_raw, str)
                    else last_verified_raw
                )
                if last_verified.tzinfo is None:
                    last_verified = last_verified.replace(tzinfo=CET)
                age_hours = (datetime.now(CET) - last_verified).total_seconds() / 3600.0
                if age_hours <= ttl_hours:
                    return int(row["location_id"])
            except Exception as e:
                self.logger.debug(f"CollectorWorker: kunde inte tolka last_verified för stad {city_id}: {e}")

        # Cache miss eller för gammal: gör exakt ett locations-anrop
        def _lookup_location() -> Optional[int]:
            result = self._openaq.get_air_quality(lat, lon)
            return None

        try:
            _lookup_location()
        except Exception as e:
            self.logger.info(f"CollectorWorker: OpenAQ location-lookup misslyckades för stad {city_id}: {e}")

        # Vi har ingen robust location_id att spara ännu, så returnera None för nu.
        return None

    def _fetch_city(self, city: Dict[str, Any]) -> None:
        """
        Fetch data for a single city using providers and save to DB.

        This reuses existing logic by delegating to WeatherController-style flows indirectly,
        but stays strictly in the collector layer.
        """
        city_id = city["id"]
        name = city.get("name", "okänd stad")
        lat = city["latitude"]
        lon = city["longitude"]

        self.logger.info(f"CollectorWorker: hämtar data för {name} ({lat}, {lon})")

        # Weather and solar/storm via Open-Meteo (if available)
        weather_data: Optional[Dict[str, Any]] = None
        if self._openmeteo:
            weather_data = self._openmeteo.get_current_weather(lat, lon)

        # Pollutants via OpenAQ first, fallback to Open-Meteo's AQI wrapper (which returns None pollutants)
        pollutants: Dict[str, Any] = {}
        pollutant_measurement_timestamp: Optional[datetime] = None

        if self._openaq:
            max_age_hours = self.db.get_calibration_parameter("openaq_max_data_age_hours")
            if max_age_hours is None:
                max_age_hours = 48.0
            else:
                max_age_hours = float(max_age_hours)
            aq_result = self._openaq.get_air_quality(lat, lon)
            if aq_result and isinstance(aq_result, dict):
                pollutants = aq_result.get("pollutants", {}) or {}
                pollutant_measurement_timestamp = aq_result.get("measurement_timestamp")

        if (not pollutants) and self._openmeteo and self._openmeteo.is_available():
            om_aq_result = self._openmeteo.get_air_quality(lat, lon)
            if om_aq_result and isinstance(om_aq_result, dict):
                pollutants = om_aq_result.get("pollutants", {}) or {}
                if pollutant_measurement_timestamp is None:
                    pollutant_measurement_timestamp = om_aq_result.get("measurement_timestamp")

        if not weather_data:
            self.logger.warning(f"CollectorWorker: ingen väderdata för {name}, hoppar över sparande")
            return

        # Merge into same shape WeatherController förväntar sig vid add_weather_data()
        try:
            temp = weather_data.get("temperature")
            hum = weather_data.get("humidity")
            wind = weather_data.get("wind_speed")
            source = weather_data.get("source", "collector")

            if temp is None or hum is None or wind is None:
                self.logger.warning(f"CollectorWorker: ofullständig väderdata för {name}, hoppar över")
                return

            solar_radiation = weather_data.get("solar_radiation")
            uv_index = weather_data.get("uv_index")
            direct_radiation = weather_data.get("direct_radiation")
            diffuse_radiation = weather_data.get("diffuse_radiation")
            sunshine_duration = weather_data.get("sunshine_duration")
            cape = weather_data.get("cape")
            precip_prob = weather_data.get("precipitation_probability")
            conv_precip = weather_data.get("convective_precipitation")

            def _poll(name: str) -> Optional[float]:
                v = pollutants.get(name)
                if v is not None:
                    return v
                return weather_data.get(name)

            pm25 = _poll("pm25")
            pm10 = _poll("pm10")
            no2 = _poll("no2")
            o3 = _poll("o3")

            measurement_timestamp = pollutant_measurement_timestamp or weather_data.get("measurement_timestamp")

            ext_kw = {
                k: weather_data[k]
                for k in WEATHER_DATA_EXTENDED_OPTIONAL_COLUMNS
                if k in weather_data and weather_data[k] is not None
            }

            self.logger.info(
                f"CollectorWorker: sparar data för {name} (source={source}, "
                f"temp={temp}, pm25={pm25}, pm10={pm10}, no2={no2}, o3={o3})"
            )

            data_id = self.db.add_weather_data(
                city_id=city_id,
                temperature=float(temp),
                humidity=float(hum),
                wind_speed=float(wind),
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
                precipitation_probability=precip_prob,
                convective_precipitation=conv_precip,
                **ext_kw,
            )

            if data_id and data_id > 0:
                self.logger.info(f"CollectorWorker: ✓ data sparad för {name} (data_id={data_id})")
            else:
                self.logger.warning(f"CollectorWorker: ✗ kunde inte spara data för {name} (data_id={data_id})")
        except Exception as e:
            self.logger.error(f"CollectorWorker: fel vid sparande för {name}: {e}")

    def run_once(self) -> None:
        """One full collection pass over all cities."""
        try:
            cities = self.db.get_all_cities()
        except Exception as e:
            self.logger.error(f"CollectorWorker: kunde inte hämta städer: {e}")
            return

        if not cities:
            self.logger.info("CollectorWorker: inga städer att samla data för.")
            return

        for city in cities:
            self._fetch_city(city)

    def run_forever(self) -> None:
        """Main loop: periodically run collection over all cities."""
        interval = self._get_collector_interval()
        self.logger.info(f"CollectorWorker: startar huvudloop med intervall {interval}s")

        while True:
            start = datetime.now(CET)
            self.run_once()
            elapsed = (datetime.now(CET) - start).total_seconds()
            sleep_time = max(0.0, interval - elapsed)
            if sleep_time > 0:
                self.logger.debug(f"CollectorWorker: sover {sleep_time:.1f}s innan nästa körning")
                try:
                    from time import sleep

                    sleep(sleep_time)
                except Exception:
                    # If sleep is interrupted, just continue loop
                    continue

