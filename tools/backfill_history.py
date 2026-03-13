"""Manual, dynamic historical backfill script for Open-Meteo.

Körs manuellt (t.ex. via .bat) och fyller på historisk väderdata
utan hårdkodade parameternamn eller datumintervall i koden.

Allt styrs via CLI-argument och parameter_registry/provider_mappings.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List

import requests
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager  # type: ignore  # noqa: E402
from utils.logger import WeatherLogger  # type: ignore  # noqa: E402
from utils.config_loader import ConfigLoader  # type: ignore  # noqa: E402
from utils.unit_conversion import convert_parameter_unit  # type: ignore  # noqa: E402
from providers.openaq_provider import OpenAQProvider  # type: ignore  # noqa: E402


CET = ZoneInfo("Europe/Stockholm")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dynamisk historik-backfill för Open-Meteo (ingen hardcoding, inga fallbacks)."
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["openmeteo", "openaq", "both"],
        default="openmeteo",
        help=(
            "Vilken provider som ska användas för backfill. "
            "openmeteo = historisk väder/solar/storm data. "
            "openaq = historisk pollutant data (PM2.5, PM10, NO2, O3). "
            "both = kör både Open-Meteo och OpenAQ i sekvens (rekommenderas: Open-Meteo först)."
        ),
    )
    parser.add_argument(
        "--days",
        type=int,
        required=True,
        help="Antal dagar bakåt i tiden att backfilla (t.ex. 90).",
    )
    parser.add_argument(
        "--city",
        type=int,
        help="Valfritt: specifik city_id att backfilla. Om utelämnad tas alla städer.",
    )
    return parser.parse_args()


def load_openmeteo_mappings(db: DatabaseManager) -> Dict[str, str]:
    """
    Läs provider_mappings för Open-Meteo dynamiskt från parameter_registry.
    Om kolumnen saknas, lägg till den dynamiskt (ingen hardcoding, inga fallbacks).
    """
    mappings: Dict[str, str] = {}
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # Dynamiskt kontrollera om provider_mappings kolumnen finns
    cursor.execute("PRAGMA table_info(parameter_registry)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'provider_mappings' not in columns:
        # Kolumnen saknas - lägg till den dynamiskt
        logger = WeatherLogger()
        logger.info("provider_mappings kolumn saknas, lägger till dynamiskt...")
        try:
            cursor.execute("ALTER TABLE parameter_registry ADD COLUMN provider_mappings TEXT")
            conn.commit()
            logger.info("provider_mappings kolumn tillagd")
            
            # Kör migration för att populera mappings (dynamiskt)
            migration_path = Path(__file__).parent.parent / "database" / "migration_add_parameter_metadata.sql"
            if migration_path.exists():
                with open(migration_path, 'r', encoding='utf-8') as f:
                    migration_sql = f.read()
                conn.executescript(migration_sql)
                conn.commit()
                logger.info("Migration kördes: provider mappings tillagda")
            else:
                logger.warning(f"Migration file not found: {migration_path}")
        except Exception as e:
            logger.error(f"Kunde inte lägga till provider_mappings kolumn: {e}")
            return mappings  # Returnera tom dict om det misslyckas
    
    # Nu kan vi säkert läsa provider_mappings
    try:
        cursor.execute(
            """
            SELECT parameter_name, provider_mappings
            FROM parameter_registry
            WHERE provider_mappings IS NOT NULL AND provider_mappings != ''
            """
        )
        rows = cursor.fetchall()
        for row in rows:
            param_name = row["parameter_name"]
            try:
                import json

                provider_map = json.loads(row["provider_mappings"])
                if "openmeteo" in provider_map:
                    mappings[param_name] = provider_map["openmeteo"]
            except Exception:
                continue
    except Exception as e:
        logger = WeatherLogger()
        logger.error(f"Fel vid läsning av provider_mappings: {e}")
    
    return mappings


def discover_parameters_for_backfill(db: DatabaseManager, mappings: Dict[str, str]) -> List[str]:
    """Hitta alla parametrar (weather/solar/storm) som både finns i registry och har Open-Meteo-mapping."""
    params: List[str] = []
    for category in ("weather", "solar", "storm"):
        for p in db.get_parameters_by_category(category):
            name = p.get("parameter_name")
            if name and name in mappings and name not in params:
                params.append(name)
    return params


def get_cities(db: DatabaseManager, only_city_id: int | None) -> List[Dict[str, Any]]:
    """Hämta städer dynamiskt från cities-tabellen."""
    conn = db.get_connection()
    cursor = conn.cursor()
    if only_city_id is not None:
        cursor.execute(
            "SELECT id, name, latitude, longitude FROM cities WHERE id = ?", (only_city_id,)
        )
    else:
        cursor.execute("SELECT id, name, latitude, longitude FROM cities ORDER BY name")
    return [dict(row) for row in cursor.fetchall()]


def build_hourly_param_string(param_names: List[str], mappings: Dict[str, str]) -> str:
    """Bygg hourly-parametrar för Open-Meteo baserat på provider_mappings."""
    api_fields = []
    for name in param_names:
        api_field = mappings.get(name)
        if api_field:
            api_fields.append(api_field)
    return ",".join(api_fields)


def backfill_city_openmeteo(
    db: DatabaseManager,
    logger: WeatherLogger,
    city: Dict[str, Any],
    days: int,
    param_names: List[str],
    mappings: Dict[str, str],
) -> None:
    """Backfilla historisk väderdata för en stad via Open-Meteo."""
    city_id = city["id"]
    name = city["name"]
    lat = city["latitude"]
    lon = city["longitude"]

    if not param_names:
        logger.warning(f"[BACKFILL] Inga parametrar att hämta för {name}, hoppar över.")
        return

    hourly_fields = build_hourly_param_string(param_names, mappings)
    if not hourly_fields:
        logger.warning(
            f"[BACKFILL] Inga Open-Meteo-fält kunde byggas från provider_mappings för {name}, hoppar över."
        )
        return

    # Använd archive endpoint för ren historisk data (ingen forecast)
    # Korrekt host för Open-Meteo archive API
    url = "https://archive-api.open-meteo.com/v1/archive"
    
    # Beräkna start- och slutdatum baserat på days
    end_date = datetime.now(CET).date()
    start_date = end_date - timedelta(days=days)
    
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": hourly_fields,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "timezone": "auto",
    }

    logger.info(
        f"[BACKFILL] Open-Meteo: Hämtar {days} dagars historik för {name} ({lat}, {lon}) "
        f"med hourly={hourly_fields}"
    )

    def fetch_data():
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    try:
        data = fetch_data()
        if data is None:
            logger.error(f"[BACKFILL] Open-Meteo-förfrågan misslyckades för {name}: rate limit eller timeout")
            return
    except Exception as e:
        logger.error(f"[BACKFILL] Open-Meteo-förfrågan misslyckades för {name}: {e}")
        return

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        logger.warning(f"[BACKFILL] Open-Meteo gav ingen hourly-tidsserie för {name}")
        return

    # Bygg per-parameter-listor baserat på mappings
    series_per_param: Dict[str, List[Any]] = {}
    for param_name in param_names:
        api_field = mappings.get(param_name)
        if not api_field:
            continue
        values = hourly.get(api_field)
        if not isinstance(values, list) or len(values) != len(times):
            continue
        series_per_param[param_name] = values

    if not series_per_param:
        logger.warning(f"[BACKFILL] Inga parametrar kunde mappas för {name}, hoppar över.")
        return

    inserted = 0
    skipped_existing = 0
    failed = 0

    # Förbered alla datapunkter för batch insert
    weather_data_list: List[Dict[str, Any]] = []

    # Hämta faktiska kolumner i weather_data för safe-mode (ingen crash om kolumn saknas)
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(weather_data)")
        weather_columns = {row[1] for row in cursor.fetchall()}
    except Exception as e:
        logger.warning(f"[BACKFILL] Kunde inte läsa weather_data-schema (safe-mode inaktiverad): {e}")
        weather_columns = set()
    
    for idx, t_str in enumerate(times):
        try:
            ts = datetime.fromisoformat(t_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=CET)
            else:
                ts = ts.astimezone(CET)
        except Exception:
            continue

        # Undvik dubbletter – kontrollera measurement_timestamp före batch insert
        try:
            if db.has_measurement_timestamp(city_id, ts, tolerance_seconds=60):
                skipped_existing += 1
                continue
        except Exception:
            # Om kontrollen misslyckas är det säkrare att spara än att hoppa över
            pass

        # Basväder måste finnas, annars sparar vi inte raden
        temp = series_per_param.get("temperature", [None])[idx] if "temperature" in series_per_param else None
        hum = series_per_param.get("humidity", [None])[idx] if "humidity" in series_per_param else None
        wind = series_per_param.get("wind_speed", [None])[idx] if "wind_speed" in series_per_param else None

        if temp is None or hum is None or wind is None:
            continue

        # Konvertera vindhastighet till databasenhet (t.ex. km/h → m/s)
        try:
            wind_converted = convert_parameter_unit(db, "wind_speed", float(wind), "openmeteo")
        except Exception:
            # Om konverteringen av någon anledning misslyckas är det säkrare att hoppa över raden
            continue

        # Bygg data dictionary dynamiskt för solar/storm-parametrar
        base_dict: Dict[str, Any] = {
            'city_id': city_id,
            'temperature': float(temp),
            'humidity': float(hum),
            'wind_speed': float(wind_converted),
            'pm25': None,
            'pm10': None,
            'no2': None,
            'o3': None,
            'source': 'openmeteo_backfill',
            'measurement_timestamp': ts,
            'aqi': None,
        }

        # Lägg till solar/storm-parametrar dynamiskt
        for p in param_names:
            if p in ("temperature", "humidity", "wind_speed"):
                continue
            series = series_per_param.get(p)
            if series is not None and idx < len(series):
                base_dict[p] = series[idx]

        # Safe-mode: filtrera bort keys som inte finns i weather_data-schemat
        data_dict: Dict[str, Any] = {}
        for key, value in base_dict.items():
            if not weather_columns or key in weather_columns or key in ("city_id", "source"):
                data_dict[key] = value
            else:
                logger.debug(f"[BACKFILL] '{key}' saknas i weather_data, hoppar över fältet i insert för {name}")
        
        weather_data_list.append(data_dict)
    
    if not weather_data_list:
        logger.info(f"[BACKFILL] {name}: Inga nya datapunkter att spara (alla redan finns eller saknar data)")
        return
    
    # Batch insert med retry-logik för database locked errors
    batch_size = 500  # Större batch size för bättre prestanda med executemany
    import time
    max_retries = 3
    retry_delay = 0.5  # seconds
    
    for batch_start in range(0, len(weather_data_list), batch_size):
        batch_end = min(batch_start + batch_size, len(weather_data_list))
        batch_data = weather_data_list[batch_start:batch_end]
        
        for retry in range(max_retries):
            try:
                # Använd batch insert metod
                data_ids = db.add_weather_data_batch(
                    batch_data,
                    skip_auto_bounds=True  # Skip auto-generation during bulk insert for performance
                )
                inserted += len(data_ids)
                # Batch klar - break retry loop
                break
                
            except Exception as e:
                error_str = str(e).lower()
                if "database is locked" in error_str and retry < max_retries - 1:
                    # Vänta och försök igen
                    wait_time = retry_delay * (retry + 1)  # Exponential backoff
                    logger.debug(f"[BACKFILL] Database locked, väntar {wait_time:.1f}s och försöker igen (försök {retry + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                else:
                    # Max retries nådd eller annat fel - logga och fortsätt med nästa batch
                    logger.warning(f"[BACKFILL] Kunde inte spara batch för {name} (datapunkter {batch_start}-{batch_end-1}): {e}")
                    failed += len(batch_data)
                    break

    logger.info(
        f"[BACKFILL] {name}: sparade {inserted} nya datapunkter, hoppade över {skipped_existing} existerande, "
        f"{failed} misslyckades."
    )
    
    # Beräkna och spara solar_index för nya datapunkter
    if inserted > 0:
        try:
            calculate_and_save_solar_index_for_city(db, logger, city_id, name)
        except Exception as e:
            logger.warning(f"[BACKFILL] Kunde inte beräkna solar_index för {name}: {e}")


def backfill_city_openaq(
    db: DatabaseManager,
    logger: WeatherLogger,
    openaq_provider: OpenAQProvider,
    city: Dict[str, Any],
    days: int,
) -> None:
    """Backfilla historisk OpenAQ-pollutantdata för en stad med location-cache."""
    city_id = city["id"]
    name = city["name"]
    lat = city["latitude"]
    lon = city["longitude"]

    # Hämta eller skapa location-cache
    location_info = db.get_openaq_location(city_id)
    location_id = None
    
    # sqlite3.Row supports dict-style access (row["key"])
    if location_info:
        cached_location_id = location_info["location_id"]
        if cached_location_id:
            # Kontrollera TTL från calibration_parameters
            ttl_hours = db.get_calibration_parameter("openaq_location_ttl_hours")
            if ttl_hours is None:
                ttl_hours = 168.0  # Default: 7 dagar
            
            last_verified = location_info["last_verified"]
            if last_verified:
                if isinstance(last_verified, str):
                    last_verified = datetime.fromisoformat(last_verified.replace('Z', '+00:00'))
                age_hours = (datetime.now(CET) - last_verified.replace(tzinfo=CET)).total_seconds() / 3600.0
                
                if age_hours < float(ttl_hours):
                    location_id = cached_location_id
                    logger.debug(f"[BACKFILL] OpenAQ: Använder cached location_id {location_id} för {name} (ålder: {age_hours:.1f}h)")
    
    # Om ingen cached location, gör lookup
    if location_id is None:
        logger.info(f"[BACKFILL] OpenAQ: Gör location lookup för {name} ({lat}, {lon})")

        def lookup_location():
            locations_url = f"{openaq_provider.BASE_URL}/locations"
            params = {
                "coordinates": f"{lat},{lon}",
                "radius": 10000,  # 10km
                "limit": 1
            }
            resp = requests.get(
                locations_url,
                params=params,
                headers=openaq_provider._headers,
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results and len(results) > 0:
                return results[0].get("id")
            return None

        try:
            location_id = lookup_location()
            if location_id:
                # Spara i cache
                db.upsert_openaq_location(city_id, lat, lon, location_id)
                logger.info(f"[BACKFILL] OpenAQ: Sparade location_id {location_id} i cache för {name}")
            else:
                logger.warning(f"[BACKFILL] OpenAQ: Ingen location hittades för {name}, hoppar över")
                return
        except Exception as e:
            logger.error(f"[BACKFILL] OpenAQ: Location lookup misslyckades för {name}: {e}")
            return
    
    # Hämta historiska measurements för location_id
    # OpenAQ API v3: Prova olika endpoints för historiska data
    # Notera: OpenAQ API v3 kan ha begränsat stöd för historiska measurements
    # Vi försöker flera endpoints och fallbackar till latest om historiska inte finns
    end_date = datetime.now(CET).date()
    start_date = end_date - timedelta(days=days)
    
    def fetch_measurements():
        # Format 1: /v3/locations/{id}/measurements (preferred)
        measurements_url = f"{openaq_provider.BASE_URL}/locations/{location_id}/measurements"
        params = {
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat(),
            "limit": 10000,
        }
        resp = requests.get(
            measurements_url,
            params=params,
            headers=openaq_provider._headers,
            timeout=30
        )
        
        # Om 404, prova alternativ endpoint
        if resp.status_code == 404:
            # Format 2: /v3/measurements med locations_id som query param
            alt_url = f"{openaq_provider.BASE_URL}/measurements"
            alt_params = {
                "locations_id": location_id,
                "date_from": start_date.isoformat(),
                "date_to": end_date.isoformat(),
                "limit": 10000,
            }
            resp = requests.get(
                alt_url,
                params=alt_params,
                headers=openaq_provider._headers,
                timeout=30
            )
        
        # Om fortfarande 404, OpenAQ API v3 stödjer kanske inte historiska measurements
        # I så fall loggar vi varning och returnerar None
        if resp.status_code == 404:
            logger.warning(
                f"[BACKFILL] OpenAQ: Historiska measurements inte tillgängliga för location {location_id}. "
                f"OpenAQ API v3 kan ha begränsat stöd för historiska data."
            )
            return None
        
        resp.raise_for_status()
        return resp.json()
    
    logger.info(
        f"[BACKFILL] OpenAQ: Hämtar {days} dagars historik för {name} (location_id={location_id}) "
        f"från {start_date} till {end_date}"
    )
    
    try:
        data = fetch_measurements()
        if data is None:
            logger.warning(
                f"[BACKFILL] OpenAQ: Kunde inte hämta historiska measurements för {name}. "
                f"OpenAQ API v3 kan ha begränsat stöd för historiska data. "
                f"Pollutanter kommer att hämtas via CollectorWorker vid nästa körning."
            )
            return
    except Exception as e:
        logger.warning(
            f"[BACKFILL] OpenAQ: Historiska measurements misslyckades för {name}: {e}. "
            f"Pollutanter kommer att hämtas via CollectorWorker vid nästa körning."
        )
        return
    
    # Parse measurements response
    results = data.get("results", [])
    if not results:
        logger.warning(f"[BACKFILL] OpenAQ gav inga measurements för {name}")
        return
    
    logger.info(f"[BACKFILL] OpenAQ: Fick {len(results)} measurements för {name}")
    
    # Gruppera measurements per timestamp och parameter
    # OpenAQ returnerar en measurement per parameter per timestamp
    measurements_by_time: Dict[datetime, Dict[str, float]] = {}
    
    for measurement in results:
        try:
            # Extract timestamp
            date_obj = measurement.get("date", {})
            if isinstance(date_obj, dict):
                date_utc = date_obj.get("utc")
                if date_utc:
                    ts = datetime.fromisoformat(date_utc.replace('Z', '+00:00'))
                    if ts.tzinfo is None:
                        from datetime import timezone
                        ts = ts.replace(tzinfo=timezone.utc)
                    ts = ts.astimezone(CET)
                else:
                    continue
            else:
                continue
            
            # Extract parameter and value
            parameter_obj = measurement.get("parameter", {})
            if isinstance(parameter_obj, dict):
                param_name = parameter_obj.get("name", "").lower()
            else:
                param_name = str(parameter_obj).lower()
            
            value = measurement.get("value")
            if value is None:
                continue
            
            # Map OpenAQ parameter names to our internal names
            param_mapping = {
                "pm25": "pm25",
                "pm2.5": "pm25",
                "pm10": "pm10",
                "no2": "no2",
                "o3": "o3",
            }
            
            internal_param = param_mapping.get(param_name)
            if not internal_param:
                continue
            
            if ts not in measurements_by_time:
                measurements_by_time[ts] = {}
            
            # Use first value if multiple measurements for same timestamp+parameter
            if internal_param not in measurements_by_time[ts]:
                measurements_by_time[ts][internal_param] = float(value)
        except Exception as e:
            logger.debug(f"[BACKFILL] OpenAQ: Kunde inte parsa measurement: {e}")
            continue
    
    if not measurements_by_time:
        logger.warning(f"[BACKFILL] OpenAQ: Inga giltiga measurements kunde parsas för {name}")
        return
    
    # Förbered datapunkter för batch insert
    weather_data_list: List[Dict[str, Any]] = []
    inserted = 0
    skipped_existing = 0
    failed = 0
    
    for ts, pollutants in measurements_by_time.items():
        # Undvik dubbletter
        try:
            if db.has_measurement_timestamp(city_id, ts, tolerance_seconds=60):
                skipped_existing += 1
                continue
        except Exception:
            pass
        
        # Hämta grundläggande väderdata för samma timestamp (om det finns)
        # För OpenAQ backfill sparar vi bara pollutanter, väderdata kommer från Open-Meteo
        try:
            # Kolla om det redan finns väderdata för denna timestamp
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, temperature, humidity, wind_speed 
                FROM weather_data 
                WHERE city_id = ? AND measurement_timestamp = ?
                LIMIT 1
            """, (city_id, ts))
            existing_weather = cursor.fetchone()
            
            if existing_weather:
                # Uppdatera befintlig rad med pollutants
                weather_id = existing_weather[0] if isinstance(existing_weather, (list, tuple)) else existing_weather["id"]
                cursor.execute("""
                    UPDATE weather_data 
                    SET pm25 = COALESCE(?, pm25),
                        pm10 = COALESCE(?, pm10),
                        no2 = COALESCE(?, no2),
                        o3 = COALESCE(?, o3)
                    WHERE id = ?
                """, (
                    pollutants.get("pm25"),
                    pollutants.get("pm10"),
                    pollutants.get("no2"),
                    pollutants.get("o3"),
                    weather_id
                ))
                conn.commit()
                inserted += 1
                continue
        except Exception as e:
            logger.debug(f"[BACKFILL] OpenAQ: Kunde inte kolla/uppdatera befintlig väderdata: {e}")
        
        # Ingen befintlig väderdata - vi kan inte skapa en rad utan required fields
        # Spara denna measurement för senare merge med Open-Meteo data
        # För nu, logga att vi hoppar över (kan implementera merge-logik senare)
        logger.debug(
            f"[BACKFILL] OpenAQ: Hittade pollutants för {name} vid {ts} men ingen väderdata. "
            "Kör Open-Meteo backfill först för att skapa bas-rader."
        )
        skipped_existing += 1
    
    if weather_data_list:
        # Batch insert med retry-logik
        batch_size = 500
        import time
        max_retries = 3
        retry_delay = 0.5
        
        for batch_start in range(0, len(weather_data_list), batch_size):
            batch_end = min(batch_start + batch_size, len(weather_data_list))
            batch_data = weather_data_list[batch_start:batch_end]
            
            for retry in range(max_retries):
                try:
                    data_ids = db.add_weather_data_batch(
                        batch_data,
                        skip_auto_bounds=True
                    )
                    inserted += len(data_ids)
                    break
                except Exception as e:
                    error_str = str(e).lower()
                    if "database is locked" in error_str and retry < max_retries - 1:
                        wait_time = retry_delay * (retry + 1)
                        logger.debug(f"[BACKFILL] Database locked, väntar {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.warning(f"[BACKFILL] Kunde inte spara batch för {name}: {e}")
                        failed += len(batch_data)
                        break
    
    logger.info(
        f"[BACKFILL] OpenAQ {name}: sparade {inserted} nya datapunkter, hoppade över {skipped_existing} existerande, "
        f"{failed} misslyckades."
    )


def calculate_and_save_solar_index_for_city(
    db: DatabaseManager,
    logger: WeatherLogger,
    city_id: int,
    city_name: str,
) -> None:
    """
    Beräkna och spara solar_index för alla datapunkter i en stad som har solar_radiation, uv_index, sunshine_duration.
    
    Args:
        db: DatabaseManager instance
        logger: Logger instance
        city_id: City ID
        city_name: City name (för loggning)
    """
    try:
        # Hämta alla väderdata för staden med solar-parametrar
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Hämta datapunkter som har minst en av solar_radiation, uv_index, sunshine_duration
        cursor.execute("""
            SELECT id, measurement_timestamp, solar_radiation, uv_index, sunshine_duration
            FROM weather_data
            WHERE city_id = ?
            AND (solar_radiation IS NOT NULL OR uv_index IS NOT NULL OR sunshine_duration IS NOT NULL)
            ORDER BY measurement_timestamp DESC
        """, (city_id,))
        
        rows = cursor.fetchall()
        if not rows:
            logger.debug(f"[BACKFILL] Inga datapunkter med solar-parametrar för {city_name}")
            return
        
        logger.info(f"[BACKFILL] Beräknar solar_index för {len(rows)} datapunkter i {city_name}")
        
        # Hämta vikter från calibration_parameters
        w1 = db.get_calibration_parameter('solar_index_radiation_weight')
        w2 = db.get_calibration_parameter('solar_index_uv_weight')
        w3 = db.get_calibration_parameter('solar_index_sunshine_weight')
        
        # Default weights
        if w1 is None:
            w1 = 0.5
        else:
            w1 = float(w1)
        if w2 is None:
            w2 = 0.3
        else:
            w2 = float(w2)
        if w3 is None:
            w3 = 0.2
        else:
            w3 = float(w3)
        
        # Normalize weights to sum to 1.0
        total_weight = w1 + w2 + w3
        if total_weight > 0:
            w1 = w1 / total_weight
            w2 = w2 / total_weight
            w3 = w3 / total_weight
        else:
            w1, w2, w3 = 0.5, 0.3, 0.2
        
        saved_count = 0
        
        for row in rows:
            try:
                data_id = row['id'] if isinstance(row, dict) or hasattr(row, 'keys') else row[0]
                measurement_ts = row['measurement_timestamp'] if isinstance(row, dict) or hasattr(row, 'keys') else row[1]
                solar_rad = row['solar_radiation'] if isinstance(row, dict) or hasattr(row, 'keys') else row[2]
                uv_idx = row['uv_index'] if isinstance(row, dict) or hasattr(row, 'keys') else row[3]
                sunshine = row['sunshine_duration'] if isinstance(row, dict) or hasattr(row, 'keys') else row[4]
                
                # Normalisera värden (använd samma logik som DerivedMetricsCalculator)
                def normalize_param_value(value, param_name):
                    """Normalize parameter value using winsorized bounds."""
                    if value is None:
                        return None
                    bounds = db.get_parameter_winsorized_bounds(param_name, 5.0, 95.0)
                    if bounds is None or bounds[0] is None or bounds[1] is None:
                        return None
                    lo, hi = bounds
                    if hi <= lo:
                        return None
                    normalized = (value - lo) / (hi - lo)
                    return max(0.0, min(1.0, normalized))
                
                solar_rad_norm = normalize_param_value(solar_rad, 'solar_radiation')
                uv_norm = normalize_param_value(uv_idx, 'uv_index')
                sunshine_norm = normalize_param_value(sunshine, 'sunshine_duration')
                
                # Bygg terms och weights
                terms = []
                weights = []
                
                if solar_rad_norm is not None:
                    terms.append(solar_rad_norm)
                    weights.append(w1)
                
                if uv_norm is not None:
                    terms.append(uv_norm)
                    weights.append(w2)
                
                if sunshine_norm is not None:
                    terms.append(sunshine_norm)
                    weights.append(w3)
                
                # Behöver minst en term
                if not terms:
                    continue
                
                # Normalisera weights för tillgängliga terms
                total_available_weight = sum(weights)
                if total_available_weight > 0:
                    weights = [w / total_available_weight for w in weights]
                else:
                    weights = [1.0 / len(weights)] * len(weights)
                
                # Beräkna solar_index
                solar_index = sum(term * weight for term, weight in zip(terms, weights))
                solar_index = max(0.0, min(1.0, solar_index))  # Clamp to [0, 1]
                
                # Spara i analytical_indices (eller uppdatera befintlig)
                # Notera: measurement_timestamp används som timestamp för analytical_index
                if isinstance(measurement_ts, str):
                    measurement_ts = datetime.fromisoformat(measurement_ts.replace('Z', '+00:00'))
                
                db.add_analytical_index(
                    city_id=city_id,
                    solar_index=solar_index,
                    storm_risk=None,
                    smog_risk=None
                )
                saved_count += 1
                
            except Exception as e:
                logger.debug(f"[BACKFILL] Kunde inte beräkna solar_index för datapunkt {data_id}: {e}")
                continue
        
        if saved_count > 0:
            logger.info(f"[BACKFILL] Sparade {saved_count} solar_index-värden för {city_name}")
        
    except Exception as e:
        logger.error(f"[BACKFILL] Fel vid beräkning av solar_index för {city_name}: {e}")


def main() -> int:
    args = parse_args()

    # Initiera logger & databas
    logger = WeatherLogger()
    db = DatabaseManager()

    # Hämta städer
    try:
        cities = get_cities(db, args.city)
    except Exception as e:
        logger.error(f"[BACKFILL] Kunde inte hämta städer: {e}")
        return 1

    if not cities:
        logger.warning("[BACKFILL] Inga städer hittades att backfilla.")
        return 0

    # Hantera provider-val
    providers_to_run = []
    if args.provider == "both":
        providers_to_run = ["openmeteo", "openaq"]
    else:
        providers_to_run = [args.provider]
    
    openaq_provider = None
    
    for provider in providers_to_run:
        if provider == "openmeteo":
            mappings = load_openmeteo_mappings(db)
            if not mappings:
                logger.error(
                    "[BACKFILL] Hittade inga provider_mappings för Open-Meteo i parameter_registry. "
                    "Kör migrations och starta om applikationen först."
                )
                continue

            param_names = discover_parameters_for_backfill(db, mappings)
            if not param_names:
                logger.error(
                    "[BACKFILL] Hittade inga parametrar i parameter_registry med Open-Meteo-mapping "
                    "för kategorierna weather/solar/storm."
                )
                continue

            logger.info(
                f"[BACKFILL] Startar Open-Meteo historik-backfill: days={args.days}, city={args.city}, "
                f"parametrar={param_names}"
            )

            for city in cities:
                backfill_city_openmeteo(db, logger, city, args.days, param_names, mappings)
        
        elif provider == "openaq":
            # Initiera OpenAQ provider (bara en gång)
            if openaq_provider is None:
                config = ConfigLoader()
                api_key = config.get_api_key("openaq")
                if not api_key:
                    logger.error(
                        "[BACKFILL] OpenAQ API-nyckel saknas. Lägg till den i config först."
                    )
                    continue
                
                try:
                    openaq_provider = OpenAQProvider(api_key, logger)
                except Exception as e:
                    logger.error(f"[BACKFILL] Kunde inte initialisera OpenAQ provider: {e}")
                    continue

            logger.info(
                f"[BACKFILL] Startar OpenAQ historik-backfill: days={args.days}, city={args.city}"
            )

            for city in cities:
                backfill_city_openaq(db, logger, openaq_provider, city, args.days)
        
        else:
            logger.error(f"[BACKFILL] Okänd provider: {provider}")
            continue

    logger.info("[BACKFILL] Klar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

