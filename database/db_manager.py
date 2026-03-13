"""Database manager for SQLite operations."""

import sqlite3
import os
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
import logging
import re

# CET timezone for all operations
CET = ZoneInfo("Europe/Stockholm")

# Get module logger
logger = logging.getLogger("WeatherApp.database")

# Thread-local storage for database connections
_thread_local = threading.local()

# Lock for write operations
_write_lock = threading.Lock()


class DatabaseManager:
    """Manages SQLite database operations for weather data."""
    
    def __init__(self, db_path: str = "weather.db"):
        """
        Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        logger.info(f"Initializing DatabaseManager with path: {db_path}")
        self.db_path = db_path
        try:
            self._init_database()
            logger.info("DatabaseManager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize DatabaseManager: {e}", exc_info=True)
            raise
    
    def _get_connection(self) -> sqlite3.Connection:
        """
        Get database connection with thread-local storage.
        """
        # Use thread-local storage to avoid connection conflicts
        if not hasattr(_thread_local, 'connection') or _thread_local.connection is None:
            logger.debug(f"Creating new database connection to {self.db_path}")
            _thread_local.connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0  # Ökad timeout för backfill-processer
            )
            _thread_local.connection.row_factory = sqlite3.Row
            # Aktivera WAL mode för bättre concurrency (dynamiskt, ingen hardcoding)
            # VIKTIGT: WAL mode gör att GUI kan läsa medan backfill skriver
            try:
                _thread_local.connection.execute("PRAGMA journal_mode=WAL")
                logger.debug("WAL mode aktiverad för bättre concurrency")
            except Exception:
                # Om WAL inte stöds, fortsätt med default mode
                pass
            # Lägg till synchronous=NORMAL för bättre prestanda under bulk inserts
            try:
                _thread_local.connection.execute("PRAGMA synchronous=NORMAL")
                logger.debug("Synchronous mode satt till NORMAL för bättre prestanda")
            except Exception:
                pass
            logger.debug("Database connection created successfully")
        else:
            # Check if connection is still valid
            try:
                _thread_local.connection.execute("SELECT 1")
                logger.debug("Reusing existing database connection")
            except (sqlite3.ProgrammingError, sqlite3.OperationalError) as e:
                # Connection is closed or invalid, create new one
                logger.warning(f"Database connection invalid, recreating: {e}")
                try:
                    _thread_local.connection.close()
                except Exception:
                    pass
                _thread_local.connection = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    timeout=30.0  # Ökad timeout för backfill-processer
                )
                _thread_local.connection.row_factory = sqlite3.Row
                # Aktivera WAL mode för bättre concurrency
                # VIKTIGT: WAL mode gör att GUI kan läsa medan backfill skriver
                try:
                    _thread_local.connection.execute("PRAGMA journal_mode=WAL")
                    logger.debug("WAL mode aktiverad för bättre concurrency")
                except Exception:
                    pass
                # Lägg till synchronous=NORMAL för bättre prestanda under bulk inserts
                try:
                    _thread_local.connection.execute("PRAGMA synchronous=NORMAL")
                    logger.debug("Synchronous mode satt till NORMAL för bättre prestanda")
                except Exception:
                    pass
                logger.debug("Database connection recreated successfully")
        return _thread_local.connection
    
    def get_connection(self) -> sqlite3.Connection:
        """
        Public method to get database connection.
        Use this instead of accessing _get_connection() directly.
        """
        return self._get_connection()

    # --- OpenAQ location cache & API usage helpers ---

    def get_openaq_location(self, city_id: int) -> Optional[sqlite3.Row]:
        """
        Get cached OpenAQ location for a city.
        
        Returns sqlite3.Row with city_id, latitude, longitude, location_id, last_verified
        or None if no cache entry exists.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT city_id, latitude, longitude, location_id, last_verified
                FROM openaq_locations
                WHERE city_id = ?
                """,
                (city_id,),
            )
            row = cursor.fetchone()
            return row
        except sqlite3.OperationalError as e:
            logger.warning(f"get_openaq_location: table openaq_locations saknas eller annat fel: {e}")
            return None

    def upsert_openaq_location(
        self,
        city_id: int,
        latitude: float,
        longitude: float,
        location_id: int,
        last_verified: Optional[datetime] = None,
    ) -> None:
        """
        Insert or update cached OpenAQ location for a city.
        """
        if last_verified is None:
            last_verified = datetime.now(CET)
        conn = self.get_connection()
        cursor = conn.cursor()
        with _write_lock:
            try:
                cursor.execute(
                    """
                    INSERT INTO openaq_locations (city_id, latitude, longitude, location_id, last_verified)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(city_id) DO UPDATE SET
                        latitude=excluded.latitude,
                        longitude=excluded.longitude,
                        location_id=excluded.location_id,
                        last_verified=excluded.last_verified
                    """,
                    (city_id, float(latitude), float(longitude), int(location_id), last_verified.isoformat()),
                )
                conn.commit()
            except sqlite3.OperationalError as e:
                logger.warning(f"upsert_openaq_location: kunde inte skriva till openaq_locations: {e}")

    def get_all_openaq_location_ids(self) -> List[int]:
        """
        Get all cached OpenAQ location_ids for cities that have a mapping.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT location_id FROM openaq_locations WHERE location_id IS NOT NULL")
            rows = cursor.fetchall()
            return [int(row["location_id"]) for row in rows if row["location_id"] is not None]
        except sqlite3.OperationalError as e:
            logger.warning(f"get_all_openaq_location_ids: table openaq_locations saknas eller annat fel: {e}")
            return []

    def record_api_usage(self, api: str, ts: Optional[datetime] = None) -> None:
        """
        Record a single API request usage event.
        """
        if ts is None:
            ts = datetime.now(CET)
        conn = self.get_connection()
        cursor = conn.cursor()
        with _write_lock:
            try:
                cursor.execute(
                    "INSERT INTO api_usage (api, timestamp) VALUES (?, ?)",
                    (str(api), ts.isoformat()),
                )
                conn.commit()
            except sqlite3.OperationalError as e:
                logger.warning(f"record_api_usage: kunde inte skriva till api_usage: {e}")

    def get_api_usage_counts(
        self,
        api: str,
        window_minutes: int,
        window_hours: int,
        now: Optional[datetime] = None,
    ) -> Tuple[int, int]:
        """
        Return (count_last_minutes, count_last_hours) for a given API.
        """
        if now is None:
            now = datetime.now(CET)
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            counts = [0, 0]
            if window_minutes > 0:
                since_min = now - timedelta(minutes=window_minutes)
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM api_usage
                    WHERE api = ? AND timestamp >= ?
                    """,
                    (str(api), since_min.isoformat()),
                )
                counts[0] = int(cursor.fetchone()[0])
            if window_hours > 0:
                since_hour = now - timedelta(hours=window_hours)
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM api_usage
                    WHERE api = ? AND timestamp >= ?
                    """,
                    (str(api), since_hour.isoformat()),
                )
                counts[1] = int(cursor.fetchone()[0])
            return counts[0], counts[1]
        except sqlite3.OperationalError as e:
            logger.warning(f"get_api_usage_counts: kunde inte läsa från api_usage: {e}")
            return 0, 0

    def get_api_limits(self, api: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Get configured rate limits for an API from api_limits or calibration_parameters.
        
        Returns:
            (max_per_minute, max_per_hour) where each element may be None.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        max_per_minute: Optional[int] = None
        max_per_hour: Optional[int] = None
        try:
            # Try api_limits table first
            cursor.execute(
                "SELECT max_per_minute, max_per_hour FROM api_limits WHERE api = ?",
                (str(api),),
            )
            row = cursor.fetchone()
            if row:
                max_per_minute = int(row[0]) if row[0] is not None else None
                max_per_hour = int(row[1]) if row[1] is not None else None
        except sqlite3.OperationalError:
            # Table may not exist; fall back to calibration_parameters keys
            pass

        # If limits not found in api_limits, look in calibration_parameters (DB still source of truth)
        if max_per_minute is None or max_per_hour is None:
            try:
                cursor.execute(
                    "SELECT key, value FROM calibration_parameters WHERE key IN (?, ?)",
                    (f"{api}_max_rpm", f"{api}_max_rph"),
                )
                rows = cursor.fetchall()
                for row in rows:
                    key = row[0]
                    try:
                        val = int(float(row[1]))
                    except (TypeError, ValueError):
                        continue
                    if key.endswith("_max_rpm"):
                        max_per_minute = val if max_per_minute is None else max_per_minute
                    elif key.endswith("_max_rph"):
                        max_per_hour = val if max_per_hour is None else max_per_hour
            except sqlite3.OperationalError:
                # calibration_parameters may not exist on very old DBs
                pass

        return max_per_minute, max_per_hour
    
    def _init_database(self):
        """Initialize database schema."""
        logger.info(f"Initialiserar databas: {self.db_path}")
        schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            error_msg = f"Schema file not found: {schema_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        logger.debug(f"Läser schema från: {schema_path}")
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        
        # Use a separate connection for initialization to avoid affecting thread-local storage
        init_conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        try:
            logger.debug("Kör schema SQL...")
            init_conn.executescript(schema_sql)
            init_conn.commit()
            logger.info("Databasschema initialiserat")
            
            # Run migration if needed (check if pollutant columns exist)
            self._run_migration_if_needed(init_conn)
        except Exception as e:
            logger.error(f"Fel vid databasinitiering: {e}")
            raise
        finally:
            init_conn.close()
    
    def _run_migration_if_needed(self, conn: sqlite3.Connection):
        """Run migrations if needed."""
        logger.debug("Checking if database migrations are needed")
        try:
            cursor = conn.cursor()
            # Check if pm25 column exists
            logger.debug("Checking weather_data table structure")
            cursor.execute("PRAGMA table_info(weather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            logger.debug(f"weather_data table has {len(columns)} columns")
            
            # Check if additional weather columns exist
            missing_columns = []
            required_columns = ['measurement_timestamp', 'uv_index', 'solar_radiation', 
                              'direct_radiation', 'diffuse_radiation', 'sunshine_duration',
                              'cape', 'precipitation_probability', 'convective_precipitation']
            for col in required_columns:
                if col not in columns:
                    missing_columns.append(col)
            
            if missing_columns:
                logger.info(f"Kör migration för att lägga till weather-kolumner: {missing_columns}")
                migration_path = Path(__file__).parent / "migration_add_weather_columns.sql"
                if migration_path.exists():
                    with open(migration_path, 'r', encoding='utf-8') as f:
                        migration_sql = f.read()
                    # Execute each ALTER TABLE statement separately with error handling
                    for stmt in migration_sql.split(';'):
                        stmt = stmt.strip()
                        if stmt and stmt.upper().startswith('ALTER'):
                            try:
                                cursor.execute(stmt)
                                logger.debug(f"Körde: {stmt[:50]}...")
                            except sqlite3.OperationalError as e:
                                if "duplicate column name" not in str(e).lower():
                                    logger.warning(f"Kunde inte lägga till kolumn: {e}")
                    conn.commit()
                    logger.info("Migration klar: weather-kolumner tillagda")
                else:
                    logger.warning(f"Migration file not found: {migration_path}")
            
            if 'pm25' not in columns:
                logger.info("Running migration to add pollutant columns...")
                migration_path = Path(__file__).parent / "migration_add_pollutants.sql"
                if migration_path.exists():
                    logger.debug(f"Reading migration file: {migration_path}")
                    with open(migration_path, 'r', encoding='utf-8') as f:
                        migration_sql = f.read()
                    logger.debug(f"Executing migration SQL ({len(migration_sql)} chars)")
                    conn.executescript(migration_sql)
                    conn.commit()
                    logger.info("Migration complete: pollutant columns added")
                else:
                    logger.warning(f"Migration file not found: {migration_path}")
            
            # Check if sensors table exists
            if not self.has_sensors_table():
                logger.info("Running migration to add sensors table...")
                migration_path = Path(__file__).parent / "migration_add_sensors_table.sql"
                if migration_path.exists():
                    logger.debug(f"Reading migration file: {migration_path}")
                    with open(migration_path, 'r', encoding='utf-8') as f:
                        migration_sql = f.read()
                    logger.debug(f"Executing migration SQL ({len(migration_sql)} chars)")
                    conn.executescript(migration_sql)
                    conn.commit()
                    logger.info("Migration complete: sensors table added")
                else:
                    logger.warning(f"Migration file not found: {migration_path}")
            
            # Check if sensor_readings table exists and sensors table has new columns
            if self.has_sensors_table():
                cursor.execute("PRAGMA table_info(sensors)")
                sensor_columns = [row[1] for row in cursor.fetchall()]
                
                # Check if sensor_readings table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sensor_readings'")
                has_readings_table = cursor.fetchone() is not None
                
                # Run sensor engine migration if needed
                if 'provider_type' not in sensor_columns or not has_readings_table:
                    logger.info("Kör migration för sensor engine...")
                    migration_path = Path(__file__).parent / "migration_sensor_engine.sql"
                    if migration_path.exists():
                        # Add columns one by one with error handling
                        # Note: SQLite doesn't support DEFAULT CURRENT_TIMESTAMP in ALTER TABLE
                        # We add columns without DEFAULT, then UPDATE existing rows
                        columns_to_add = [
                            ('provider_type', 'TEXT', None),
                            ('config_json', 'TEXT', None),
                            ('visibility_mode', 'TEXT', "'marker'"),
                            ('enabled', 'INTEGER', '1'),
                            ('interval_seconds', 'INTEGER', '600'),
                            ('last_error', 'TEXT', None),
                            ('error_count', 'INTEGER', '0'),
                            ('created_at', 'DATETIME', None)  # Will be set via UPDATE
                        ]
                        
                        for col_name, col_type, default_value in columns_to_add:
                            if col_name not in sensor_columns:
                                try:
                                    # Add column without DEFAULT (SQLite limitation)
                                    cursor.execute(f"ALTER TABLE sensors ADD COLUMN {col_name} {col_type}")
                                    logger.debug(f"Lade till kolumn {col_name}")
                                    
                                    # Set default value for existing rows if specified
                                    if default_value is not None:
                                        cursor.execute(f"UPDATE sensors SET {col_name} = {default_value} WHERE {col_name} IS NULL")
                                    elif col_name == 'created_at':
                                        # Special case: set created_at to CURRENT_TIMESTAMP for existing rows
                                        cursor.execute(f"UPDATE sensors SET {col_name} = CURRENT_TIMESTAMP WHERE {col_name} IS NULL")
                                except sqlite3.OperationalError as e:
                                    if "duplicate column name" not in str(e).lower():
                                        logger.warning(f"Kunde inte lägga till kolumn {col_name}: {e}")
                        
                        # Create sensor_readings table if it doesn't exist
                        if not has_readings_table:
                            try:
                                cursor.execute("""
                                    CREATE TABLE IF NOT EXISTS sensor_readings (
                                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                                        sensor_id INTEGER NOT NULL,
                                        value REAL NOT NULL,
                                        parameter TEXT,
                                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                                        FOREIGN KEY (sensor_id) REFERENCES sensors(id) ON DELETE CASCADE
                                    )
                                """)
                                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sensor_readings_sensor_timestamp ON sensor_readings(sensor_id, timestamp)")
                                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sensor_readings_timestamp ON sensor_readings(timestamp)")
                                logger.info("sensor_readings tabell skapad")
                            except Exception as e:
                                logger.warning(f"Kunde inte skapa sensor_readings tabell: {e}")
                        
                        conn.commit()
                        logger.info("Migration klar: sensor engine schema uppdaterat")
                    else:
                        logger.warning(f"Migration file not found: {migration_path}")
            
            # Check if calibration_parameters table exists and has required parameters
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='calibration_parameters'")
            has_calibration_table = cursor.fetchone() is not None
            
            if has_calibration_table:
                # Check if required normalization parameters exist
                cursor.execute("SELECT key FROM calibration_parameters WHERE key IN (?, ?, ?, ?, ?, ?, ?)",
                             ('humidity_normalize_p_low', 'wind_speed_normalize_p_low', 'o3_normalize_p_low',
                              'solar_index_radiation_weight', 'solar_radiation_normalize_p_low', 'uv_index_normalize_p_low',
                              'storm_risk_cape_threshold'))
                existing_keys = {row[0] for row in cursor.fetchall()}
                
                # If any required parameters are missing, run solar/storm calibration migration
                required_keys = {'humidity_normalize_p_low', 'wind_speed_normalize_p_low', 'o3_normalize_p_low',
                                'solar_index_radiation_weight', 'solar_radiation_normalize_p_low', 'uv_index_normalize_p_low',
                                'storm_risk_cape_threshold'}
                if not required_keys.issubset(existing_keys):
                    logger.info("Kör migration för solar/storm calibration parameters...")
                    migration_path = Path(__file__).parent / "migration_add_solar_storm_calibration.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: solar/storm calibration parameters tillagda")
                    else:
                        logger.warning(f"Migration file not found: {migration_path}")
            else:
                # Create calibration_parameters table first
                logger.info("Kör migration för calibration_parameters tabell...")
                migration_path = Path(__file__).parent / "migration_add_calibration_parameters.sql"
                if migration_path.exists():
                    with open(migration_path, 'r', encoding='utf-8') as f:
                        migration_sql = f.read()
                    conn.executescript(migration_sql)
                    conn.commit()
                    logger.info("Migration klar: calibration_parameters tabell skapad")
                    
                    # Then run solar/storm migration
                    migration_path = Path(__file__).parent / "migration_add_solar_storm_calibration.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: solar/storm calibration parameters tillagda")
                
                # Check if storm_risk_cape_threshold exists (old parameter, kept for backward compatibility)
                cursor.execute("SELECT key FROM calibration_parameters WHERE key = 'storm_risk_cape_threshold'")
                if cursor.fetchone() is None:
                    logger.info("Kör migration för storm_risk_cape_threshold...")
                    migration_path = Path(__file__).parent / "migration_add_storm_risk_cape_threshold.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: storm_risk_cape_threshold tillagd")
                
                # Check if new CAPE scaling parameters exist (meteorologically aware model)
                cursor.execute("SELECT key FROM calibration_parameters WHERE key = 'storm_risk_cape_zero_threshold'")
                if cursor.fetchone() is None:
                    logger.info("Kör migration för CAPE scaling parameters...")
                    migration_path = Path(__file__).parent / "migration_add_storm_risk_cape_scaling.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: CAPE scaling parameters tillagda")
                
                # Check if chart variation system exists
                cursor.execute("PRAGMA table_info(parameter_registry)")
                param_registry_cols = [row[1] for row in cursor.fetchall()]
                if 'variation_mode' not in param_registry_cols:
                    logger.info("Kör migration för chart variation system...")
                    migration_path = Path(__file__).parent / "migration_add_chart_variation_system.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: chart variation system tillagt")
                
                # Check if provider_mappings column exists in parameter_registry
                if 'provider_mappings' not in param_registry_cols:
                    logger.info("Kör migration för parameter provider metadata...")
                    try:
                        # Add provider_mappings column
                        cursor.execute("ALTER TABLE parameter_registry ADD COLUMN provider_mappings TEXT")
                        conn.commit()
                        logger.info("Migration klar: provider_mappings kolumn tillagd i parameter_registry")
                    except sqlite3.OperationalError as e:
                        if "duplicate column name" not in str(e).lower():
                            logger.warning(f"Kunde inte lägga till provider_mappings kolumn: {e}")
                    
                    # Run migration SQL to populate mappings
                    migration_path = Path(__file__).parent / "migration_add_parameter_metadata.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: parameter provider mappings tillagda")
                    else:
                        logger.warning(f"Migration file not found: {migration_path}")
                
                # Check if chart_category_styles table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chart_category_styles'")
                if cursor.fetchone() is None:
                    logger.info("Kör migration för chart_category_styles...")
                    migration_path = Path(__file__).parent / "migration_add_chart_category_styles.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: chart_category_styles tabell skapad")

            # Ensure OpenAQ cache and API usage tables exist
            try:
                logger.info("Kör migration för OpenAQ cache och API-usage tabeller...")
                migration_path = Path(__file__).parent / "migration_add_openaq_cache_and_api_usage.sql"
                if migration_path.exists():
                    with open(migration_path, 'r', encoding='utf-8') as f:
                        migration_sql = f.read()
                    conn.executescript(migration_sql)
                    conn.commit()
                    logger.info("Migration klar: openaq_locations/api_usage/api_limits skapade (om de saknades)")
                else:
                    logger.warning(f"Migration file not found: {migration_path}")
            except Exception as e:
                logger.warning(f"Kunde inte köra OpenAQ cache/API-usage migration: {e}")
                
                # Check if analytical_indices table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='analytical_indices'")
                if cursor.fetchone() is None:
                    logger.info("Kör migration för analytical_indices...")
                    migration_path = Path(__file__).parent / "migration_add_analytical_indices.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: analytical_indices tabell skapad")
                
                # Check if lightning_events table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lightning_events'")
                if cursor.fetchone() is None:
                    logger.info("Kör migration för lightning_events...")
                    migration_path = Path(__file__).parent / "migration_add_lightning_events.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: lightning_events tabell skapad")
                
                # Check if chart calibration parameters exist
                cursor.execute("SELECT key FROM calibration_parameters WHERE key = 'chart_background_color'")
                if cursor.fetchone() is None:
                    logger.info("Kör migration för chart calibration parameters...")
                    migration_path = Path(__file__).parent / "migration_add_chart_calibration.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: chart calibration parameters tillagda")
                
                # Wind calibration (warning threshold and migration threshold)
                cursor.execute("SELECT key FROM calibration_parameters WHERE key = 'wind_speed_warning_threshold_mps'")
                if cursor.fetchone() is None:
                    migration_path = Path(__file__).parent / "migration_add_wind_calibration.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: wind calibration parameters tillagda")
                
                # Map extent (heatmap and view bounds; fallback to bbox of all cities if missing)
                cursor.execute("SELECT key FROM calibration_parameters WHERE key = 'map_extent_lat_min'")
                if cursor.fetchone() is None:
                    migration_path = Path(__file__).parent / "migration_add_map_extent.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: map extent calibration parameters tillagda")
                
                # Graph legend setting (default off)
                cursor.execute("SELECT key FROM calibration_parameters WHERE key = 'graph_show_legend'")
                if cursor.fetchone() is None:
                    migration_path = Path(__file__).parent / "migration_add_graph_legend_setting.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: graph_show_legend tillagd")
                
                # Remove icon system (SVG icons removed from application)
                cursor.execute("PRAGMA table_info(chart_category_styles)")
                columns = [col[1] for col in cursor.fetchall()]
                has_icon_column = 'icon_filename' in columns
                
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parameter_icon_overrides'")
                has_param_overrides = cursor.fetchone() is not None
                
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='category_icon_overrides'")
                has_category_overrides = cursor.fetchone() is not None
                
                if has_icon_column or has_param_overrides or has_category_overrides:
                    logger.info("Kör migration för att ta bort icon system...")
                    migration_path = Path(__file__).parent / "migration_remove_icon_system.sql"
                    if migration_path.exists():
                        with open(migration_path, 'r', encoding='utf-8') as f:
                            migration_sql = f.read()
                        conn.executescript(migration_sql)
                        conn.commit()
                        logger.info("Migration klar: icon system borttaget")
                    else:
                        logger.warning(f"Migration file not found: {migration_path}")
            
            # After migrations, run auto-discovery and auto-generation
            logger.info("Kör parameter registry auto-discovery och normalization bounds auto-generering...")
            try:
                self._auto_discover_parameters_from_schema(conn)
                self._auto_generate_all_normalization_bounds(conn)
            except Exception as e:
                logger.warning(f"Fel vid auto-discovery/auto-generation: {e}")
        except Exception as e:
            logger.error(f"Fel vid migration: {e}")
            # Don't raise - migration is optional, schema might already be updated
    
    # City operations
    def add_city(self, name: str, latitude: float, longitude: float) -> int:
        """
        Add a new city to the database.
        
        Args:
            name: City name
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            
        Returns:
            City ID
        """
        logger.info(f"Lägger till stad: {name} ({latitude}, {longitude})")
        with _write_lock:  # Use lock for write operations
            conn = self._get_connection()
            # Verify connection is still open
            try:
                conn.execute("SELECT 1")
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                # Connection closed, recreate it
                if hasattr(_thread_local, 'connection'):
                    try:
                        _thread_local.connection.close()
                    except Exception:
                        pass
                    _thread_local.connection = None
                conn = self._get_connection()
            
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO cities (name, latitude, longitude) VALUES (?, ?, ?)",
                    (name, latitude, longitude)
                )
                conn.commit()
                city_id = cursor.lastrowid
                logger.info(f"Stad tillagd med ID: {city_id}")
                return city_id
            except sqlite3.IntegrityError as e:
                error_msg = f"City '{name}' already exists"
                logger.warning(error_msg)
                raise ValueError(error_msg)
            except Exception as e:
                logger.error(f"Fel vid tillägg av stad: {e}")
                raise
    
    def get_city(self, city_id: int) -> Optional[Dict]:
        """Get city by ID."""
        # No logger to avoid recursion
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cities WHERE id = ?", (city_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            # Return None on error instead of raising
            return None
    
    def get_city_by_name(self, name: str) -> Optional[Dict]:
        """Get city by name."""
        # No logger to avoid recursion
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cities WHERE name = ?", (name,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            # Return None on error instead of raising
            return None
    
    def get_all_cities(self) -> List[Dict]:
        """Get all cities."""
        # No logger to avoid recursion - this is called frequently from GUI
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cities ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            # Return empty list on error instead of raising
            return []
    
    def delete_city(self, city_id: int) -> bool:
        """Delete a city and its weather data."""
        logger.info(f"Tar bort stad med ID: {city_id}")
        with _write_lock:  # Use lock for write operations
            conn = self._get_connection()
            # Verify connection is still open
            try:
                conn.execute("SELECT 1")
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                # Connection closed, recreate it
                if hasattr(_thread_local, 'connection'):
                    try:
                        _thread_local.connection.close()
                    except Exception:
                        pass
                    _thread_local.connection = None
                conn = self._get_connection()
            
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM cities WHERE id = ?", (city_id,))
                conn.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Stad {city_id} borttagen")
                else:
                    logger.warning(f"Kunde inte hitta stad med ID: {city_id}")
                return deleted
            except Exception as e:
                logger.error(f"Fel vid borttagning av stad: {e}")
                raise
    
    # Weather data operations
    def has_measurement_timestamp(
        self,
        city_id: int,
        measurement_timestamp: datetime,
        tolerance_seconds: int = 60
    ) -> bool:
        """
        Check if measurement timestamp already exists for city.
        
        Args:
            city_id: City ID
            measurement_timestamp: Measurement timestamp from API
            tolerance_seconds: Tolerance for timestamp matching (default 60s)
            
        Returns:
            True if timestamp exists (within tolerance), False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Ensure timestamp is timezone-aware (CET)
            if measurement_timestamp.tzinfo is None:
                measurement_timestamp = measurement_timestamp.replace(tzinfo=CET)
            elif measurement_timestamp.tzinfo != CET:
                measurement_timestamp = measurement_timestamp.astimezone(CET)
            
            # Convert to string for SQL comparison
            ts_str = measurement_timestamp.strftime('%Y-%m-%d %H:%M:%S')
            
            # Check if timestamp exists within tolerance
            # Use JULIANDAY for precise comparison
            query = """
                SELECT COUNT(*) as count
                FROM weather_data
                WHERE city_id = ?
                AND ABS((JULIANDAY(timestamp) - JULIANDAY(?)) * 86400) <= ?
            """
            
            cursor.execute(query, (city_id, ts_str, tolerance_seconds))
            result = cursor.fetchone()
            
            count = result['count'] if result else 0
            exists = count > 0
            
            if exists:
                logger.debug(f"Measurement timestamp {ts_str} finns redan för stad {city_id} (tolerance: {tolerance_seconds}s)")
            else:
                logger.debug(f"Measurement timestamp {ts_str} är ny för stad {city_id}")
            
            return exists
            
        except Exception as e:
            # NO fallback: If error, return False (safer to save than to miss)
            logger.warning(f"Fel vid kontroll av measurement timestamp: {e}, returnerar False")
            return False

    def debug_wind_speed_conversion(
        self,
        city_id: Optional[int] = None,
        source_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Debug wind_speed values to verify unit conversion.

        Args:
            city_id: Optional city ID to filter by
            source_filter: Optional source filter (e.g., 'openmeteo_backfill')

        Returns:
            Dictionary with statistics and sample rows
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                city_id,
                source,
                COUNT(*) as count,
                AVG(wind_speed) as avg_wind,
                MIN(wind_speed) as min_wind,
                MAX(wind_speed) as max_wind,
                SUM(CASE WHEN wind_speed > 20 THEN 1 ELSE 0 END) as high_wind_count
            FROM weather_data
            WHERE 1=1
        """
        params: list[Any] = []

        if city_id is not None:
            query += " AND city_id = ?"
            params.append(city_id)

        if source_filter is not None:
            query += " AND source = ?"
            params.append(source_filter)

        query += " GROUP BY city_id, source ORDER BY avg_wind DESC LIMIT 20"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Get sample rows with high wind speeds
        sample_query = """
            SELECT id, city_id, timestamp, wind_speed, source
            FROM weather_data
            WHERE 1=1
        """
        sample_params: list[Any] = []
        if city_id is not None:
            sample_query += " AND city_id = ?"
            sample_params.append(city_id)
        if source_filter is not None:
            sample_query += " AND source = ?"
            sample_params.append(source_filter)

        sample_query += " AND wind_speed > 15 ORDER BY wind_speed DESC LIMIT 10"
        cursor.execute(sample_query, sample_params)
        samples = [dict(row) for row in cursor.fetchall()]

        return {
            "statistics": [dict(row) for row in rows],
            "high_wind_samples": samples,
            "expected_range": "3-8 m/s for Sweden (normal), up to 20 m/s during storms",
        }
    
    def add_weather_data(
        self,
        city_id: int,
        temperature: float,
        humidity: float,
        wind_speed: float,
        pm25: Optional[float] = None,
        pm10: Optional[float] = None,
        no2: Optional[float] = None,
        o3: Optional[float] = None,
        source: str = "unknown",
        timestamp: Optional[datetime] = None,
        measurement_timestamp: Optional[datetime] = None,  # NEW
        aqi: Optional[float] = None,  # Kept for backward compatibility, calculated on-demand
        # Solar parameters
        uv_index: Optional[float] = None,
        solar_radiation: Optional[float] = None,
        direct_radiation: Optional[float] = None,
        diffuse_radiation: Optional[float] = None,
        sunshine_duration: Optional[float] = None,
        # Storm parameters
        cape: Optional[float] = None,
        precipitation_probability: Optional[float] = None,
        convective_precipitation: Optional[float] = None,
        # Performance optimization flags
        skip_auto_bounds: bool = False  # Skip auto-generation of normalization bounds (for bulk inserts)
    ) -> int:
        """
        Add weather data entry.
        
        Args:
            city_id: City ID
            temperature: Temperature in Celsius
            humidity: Humidity percentage
            wind_speed: Wind speed in m/s
            pm25: PM2.5 in µg/m³ (optional)
            pm10: PM10 in µg/m³ (optional)
            no2: NO₂ in µg/m³ (optional)
            o3: O₃ in µg/m³ (optional)
            source: API source name
            timestamp: Optional timestamp (defaults to now) - collector timestamp
            measurement_timestamp: Optional measurement timestamp from API (preferred over timestamp)
            aqi: Air Quality Index (optional, kept for backward compatibility)
            
        Returns:
            Weather data ID
        """
        logger.debug(
            f"Lägger till väderdata för stad {city_id} från {source}: "
            f"temp={temperature}°C, hum={humidity}%, wind_speed={wind_speed}, PM2.5={pm25}, PM10={pm10}"
        )
        
        # Validate wind_speed value (0-50 m/s is reasonable range, >20 m/s should be logged)
        if wind_speed is not None:
            try:
                wind_speed_float = float(wind_speed)
                if wind_speed_float < 0:
                    logger.warning(
                        f"[UNITS] add_weather_data: Negativt wind_speed-värde för stad {city_id} från {source}: "
                        f"{wind_speed_float} m/s. Använder 0.0 istället."
                    )
                    wind_speed = 0.0
                elif wind_speed_float > 50.0:
                    logger.warning(
                        f"[UNITS] add_weather_data: Extremt högt wind_speed-värde för stad {city_id} från {source}: "
                        f"{wind_speed_float} m/s. Kan vara felaktigt data eller fel enhet."
                    )
                elif wind_speed_float > 20.0:
                    logger.warning(
                        f"[UNITS] add_weather_data: Högt wind_speed-värde för stad {city_id} från {source}: "
                        f"{wind_speed_float} m/s. Kan vara korrekt vid storm, men bör verifieras mot källa och enheter."
                    )
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"[UNITS] add_weather_data: Kunde inte konvertera wind_speed till float för stad {city_id}: "
                    f"{wind_speed} (error: {e})"
                )
                # Don't raise - let the database constraint handle it or use None
        
        with _write_lock:  # Use lock for write operations
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # timestamp = collector timestamp (when data was saved) - always use current time
                # measurement_timestamp = when measurement was actually taken (from API) - stored separately
                # Always use current time for timestamp to ensure "last updated" shows correctly
                if timestamp is not None:
                    ts = timestamp
                    # Ensure timezone-aware (CET)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=CET)
                    elif ts.tzinfo != CET:
                        ts = ts.astimezone(CET)
                else:
                    # Always use current time for collector timestamp
                    ts = datetime.now(CET)
                
                # measurement_timestamp is stored separately in measurement_timestamp column
                # and is used for tracking when the measurement was actually taken, not when it was saved
                
                # Prepare measurement_timestamp for storage (separate from collector timestamp)
                meas_ts = None
                if measurement_timestamp is not None:
                    meas_ts = measurement_timestamp
                    # Ensure timezone-aware (CET)
                    if meas_ts.tzinfo is None:
                        meas_ts = meas_ts.replace(tzinfo=CET)
                    elif meas_ts.tzinfo != CET:
                        meas_ts = meas_ts.astimezone(CET)
                
                cursor.execute(
                    """INSERT INTO weather_data 
                       (city_id, temperature, humidity, wind_speed, pm25, pm10, no2, o3, aqi, timestamp, source,
                        uv_index, solar_radiation, direct_radiation, diffuse_radiation, sunshine_duration,
                        cape, precipitation_probability, convective_precipitation, measurement_timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (city_id, temperature, humidity, wind_speed, pm25, pm10, no2, o3, aqi, ts, source,
                     uv_index, solar_radiation, direct_radiation, diffuse_radiation, sunshine_duration,
                     cape, precipitation_probability, convective_precipitation, meas_ts)
                )
                conn.commit()
                data_id = cursor.lastrowid
                logger.debug(f"Väderdata sparad med ID: {data_id}, timestamp: {ts}")
                
                # Auto-generate normalization bounds for parameters that have sufficient data
                # Skip this during bulk inserts (e.g. backfill) for performance
                if not skip_auto_bounds:
                    # Check solar and storm parameters that were just saved
                    parameters_to_check = []
                    if uv_index is not None:
                        parameters_to_check.append('uv_index')
                    if solar_radiation is not None:
                        parameters_to_check.append('solar_radiation')
                    if sunshine_duration is not None:
                        parameters_to_check.append('sunshine_duration')
                    if cape is not None:
                        parameters_to_check.append('cape')
                    if precipitation_probability is not None:
                        parameters_to_check.append('precipitation_probability')
                    if convective_precipitation is not None:
                        parameters_to_check.append('convective_precipitation')
                    
                    # Also check pollutant parameters
                    if pm25 is not None:
                        parameters_to_check.append('pm25')
                    if pm10 is not None:
                        parameters_to_check.append('pm10')
                    if no2 is not None:
                        parameters_to_check.append('no2')
                    if o3 is not None:
                        parameters_to_check.append('o3')
                    
                    # Try to auto-generate bounds for each parameter
                    for param in parameters_to_check:
                        try:
                            self._auto_generate_normalization_bounds(param)
                        except Exception as e:
                            logger.debug(f"Kunde inte auto-generera bounds för {param}: {e}")
                
                return data_id
            except Exception as e:
                logger.error(f"Fel vid sparande av väderdata: {e}")
                raise
    
    def add_weather_data_batch(
        self,
        weather_data_list: List[Dict],
        skip_auto_bounds: bool = True
    ) -> List[int]:
        """
        Batch insert weather data using BEGIN/COMMIT transaction and executemany().
        Much faster than individual inserts and reduces database locks.
        
        Args:
            weather_data_list: List of dictionaries, each containing weather data fields:
                - city_id (required)
                - temperature (required)
                - humidity (required)
                - wind_speed (required)
                - measurement_timestamp (preferred) or timestamp
                - source (default: "unknown")
                - Optional: pm25, pm10, no2, o3, aqi
                - Optional: uv_index, solar_radiation, direct_radiation, diffuse_radiation, sunshine_duration
                - Optional: cape, precipitation_probability, convective_precipitation
            skip_auto_bounds: Skip auto-generation of normalization bounds (default: True for performance)
            
        Returns:
            List of data_ids for successfully inserted rows
        """
        if not weather_data_list:
            return []
        
        data_ids = []
        with _write_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Prepare all rows for executemany()
                rows_to_insert = []
                for data in weather_data_list:
                    city_id = data.get('city_id')
                    temperature = data.get('temperature')
                    humidity = data.get('humidity')
                    wind_speed = data.get('wind_speed')
                    source = data.get('source', 'unknown')
                    
                    # Validate required fields
                    if city_id is None or temperature is None or humidity is None or wind_speed is None:
                        continue
                    
                    # Handle timestamp (prefer measurement_timestamp)
                    if 'measurement_timestamp' in data and data['measurement_timestamp'] is not None:
                        ts = data['measurement_timestamp']
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=CET)
                        elif ts.tzinfo != CET:
                            ts = ts.astimezone(CET)
                    elif 'timestamp' in data and data['timestamp'] is not None:
                        ts = data['timestamp']
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=CET)
                        elif ts.tzinfo != CET:
                            ts = ts.astimezone(CET)
                    else:
                        ts = datetime.now(CET)
                    
                    # Build row tuple (match INSERT statement order)
                    row = (
                        city_id,
                        float(temperature),
                        float(humidity),
                        float(wind_speed),
                        data.get('pm25'),
                        data.get('pm10'),
                        data.get('no2'),
                        data.get('o3'),
                        data.get('aqi'),
                        ts,
                        source,
                        data.get('uv_index'),
                        data.get('solar_radiation'),
                        data.get('direct_radiation'),
                        data.get('diffuse_radiation'),
                        data.get('sunshine_duration'),
                        data.get('cape'),
                        data.get('precipitation_probability'),
                        data.get('convective_precipitation')
                    )
                    rows_to_insert.append(row)
                
                if not rows_to_insert:
                    logger.warning("Inga giltiga rader att spara i batch")
                    return []
                
                # Use transaction for batch insert with executemany()
                cursor.execute("BEGIN TRANSACTION")
                try:
                    # Use executemany() for maximum performance
                    cursor.executemany(
                        """INSERT INTO weather_data 
                           (city_id, temperature, humidity, wind_speed, pm25, pm10, no2, o3, aqi, timestamp, source,
                            uv_index, solar_radiation, direct_radiation, diffuse_radiation, sunshine_duration,
                            cape, precipitation_probability, convective_precipitation)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        rows_to_insert
                    )
                    conn.commit()
                    
                    # Get inserted IDs - executemany() only returns lastrowid, so we calculate range
                    # This is approximate but acceptable for batch operations
                    if rows_to_insert:
                        last_id = cursor.lastrowid
                        num_inserted = len(rows_to_insert)
                        # Calculate approximate IDs (SQLite auto-increment is sequential)
                        data_ids = list(range(last_id - num_inserted + 1, last_id + 1))
                    
                    logger.debug(f"Batch insert klar: {len(data_ids)} rader sparade i en transaktion med executemany()")
                    
                except Exception as e:
                    conn.rollback()
                    logger.error(f"Fel vid batch insert, rollback utförd: {e}")
                    raise
                
                # Auto-generate normalization bounds if requested (skip for performance during bulk inserts)
                if not skip_auto_bounds:
                    # Collect unique parameters that were inserted
                    parameters_to_check = set()
                    for data in weather_data_list:
                        for param in ['uv_index', 'solar_radiation', 'sunshine_duration', 'cape', 
                                     'precipitation_probability', 'convective_precipitation',
                                     'pm25', 'pm10', 'no2', 'o3']:
                            if data.get(param) is not None:
                                parameters_to_check.add(param)
                    
                    # Try to auto-generate bounds for each parameter (once per batch)
                    for param in parameters_to_check:
                        try:
                            self._auto_generate_normalization_bounds(param)
                        except Exception as e:
                            logger.debug(f"Kunde inte auto-generera bounds för {param}: {e}")
                
                return data_ids
                
            except Exception as e:
                logger.error(f"Fel vid batch insert av väderdata: {e}")
                raise
    
    def get_24h_rolling_average(self, city_id: int, parameter: str) -> Optional[float]:
        """
        Get 24h rolling average for a pollutant parameter.
        
        Args:
            city_id: City ID
            parameter: Parameter name ('pm25', 'pm10', 'no2', 'o3')
            
        Returns:
            24h rolling average value, or None if insufficient data
        """
        return self.get_rolling_average(city_id, parameter, hours=24)
    
    def get_rolling_average(self, city_id: int, parameter: str, hours: int = 24) -> Optional[float]:
        """
        Get rolling average for a parameter over specified hours (dynamic, no hardcoding).
        
        Args:
            city_id: City ID
            parameter: Parameter name (dynamically discovered from schema, no hardcoded list)
            hours: Number of hours to average over (default: 24)
            
        Returns:
            Rolling average value, or None if insufficient data
        """
        try:
            # Dynamically check if parameter exists in schema (no hardcoded whitelist)
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(weather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if parameter not in columns:
                logger.debug(f"Parameter '{parameter}' not found in weather_data schema")
                return None
            
            # Get data for specified hours (dynamic WHERE clause)
            cursor.execute(
                f"""SELECT {parameter}, timestamp 
                   FROM weather_data 
                   WHERE city_id = ? 
                   AND {parameter} IS NOT NULL
                   AND timestamp >= datetime('now', '-' || ? || ' hours')
                   ORDER BY timestamp""",
                (city_id, hours)
            )
            
            rows = cursor.fetchall()
            if not rows:
                return None
            
            # Calculate average
            values = [row[0] for row in rows if row[0] is not None]
            if not values:
                return None
            
            # Accept any data available (no minimum threshold - dynamic based on actual data)
            if len(values) < 1:
                return None
            
            avg = sum(values) / len(values)
            logger.debug(f"{hours}h rolling average {parameter} for city {city_id}: {avg:.2f} (from {len(values)} values)")
            return avg
            
        except Exception as e:
            logger.error(f"Fel vid beräkning av {hours}h medelvärde för {parameter}: {e}")
            return None
    
    def get_latest_pollutant_values(self, city_id: int) -> Optional[Dict]:
        """
        Get latest pollutant values for a city.
        Dynamically discovers pollutant parameters from schema (no hardcoding).
        
        Args:
            city_id: City ID
            
        Returns:
            Dictionary with pollutant values (dynamically discovered), or None if no data
        """
        try:
            # Discover pollutant parameters from schema dynamically
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(weather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            # Exclude non-pollutant columns
            excluded = {'id', 'city_id', 'timestamp', 'source', 'aqi', 'measurement_timestamp', 
                       'temperature', 'humidity', 'wind_speed'}
            pollutant_params = [col for col in columns if col not in excluded]
            
            if not pollutant_params:
                return None
            
            # Build dynamic SQL query
            # Create condition: at least one pollutant is NOT NULL
            not_null_conditions = " OR ".join([f"{param} IS NOT NULL" for param in pollutant_params])
            select_clause = ", ".join(pollutant_params)
            
            query = f"""SELECT {select_clause}
                       FROM weather_data 
                       WHERE city_id = ? 
                       AND ({not_null_conditions})
                       ORDER BY timestamp DESC 
                       LIMIT 1"""
            
            cursor.execute(query, (city_id,))
            row = cursor.fetchone()
            if row:
                # Return dict with all pollutant values (dynamically discovered)
                return {param: row[param] for param in pollutant_params}
            return None
        except Exception as e:
            logger.warning(f"Fel vid hämtning av senaste pollutant-värden: {e}")
            return None
    
    def debug_pollutant_data(self, city_id: int) -> Dict[str, Any]:
        """
        Debug helper to inspect pollutant-data för en stad.
        
        Returnerar en struktur med:
          - 'city_id'
          - 'pollutant_params': lista av upptäckta pollutant-kolumner
          - 'latest_values': dict med senaste pollutant-värden (eller None)
          - 'rows_with_any_pollutant': antal rader där minst en pollutant != NULL
          - 'last_row_timestamps': {'timestamp': ..., 'measurement_timestamp': ...} för senaste rad
        """
        result: Dict[str, Any] = {
            "city_id": city_id,
            "pollutant_params": [],
            "latest_values": None,
            "rows_with_any_pollutant": 0,
            "last_row_timestamps": None,
        }
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Discover pollutant columns (same logic as get_latest_pollutant_values)
            cursor.execute("PRAGMA table_info(weather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            excluded = {
                "id",
                "city_id",
                "timestamp",
                "source",
                "aqi",
                "measurement_timestamp",
                "temperature",
                "humidity",
                "wind_speed",
            }
            pollutant_params = [col for col in columns if col not in excluded]
            result["pollutant_params"] = pollutant_params

            if not pollutant_params:
                return result

            # Count rows with any pollutant value
            not_null_conditions = " OR ".join(
                [f"{param} IS NOT NULL" for param in pollutant_params]
            )
            count_query = f"""
                SELECT COUNT(*) AS cnt
                FROM weather_data
                WHERE city_id = ?
                  AND ({not_null_conditions})
            """
            cursor.execute(count_query, (city_id,))
            row = cursor.fetchone()
            if row:
                result["rows_with_any_pollutant"] = row[0]

            # Latest pollutant values (reuse helper)
            result["latest_values"] = self.get_latest_pollutant_values(city_id)

            # Last row timestamps
            cursor.execute(
                """
                SELECT timestamp, measurement_timestamp
                FROM weather_data
                WHERE city_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (city_id,),
            )
            ts_row = cursor.fetchone()
            if ts_row:
                result["last_row_timestamps"] = {
                    "timestamp": ts_row[0],
                    "measurement_timestamp": ts_row[1],
                }

            return result
        except Exception as e:
            logger.warning(f"Fel vid debug_pollutant_data för city_id={city_id}: {e}")
            return result
    
    def debug_wind_speed_for_city(self, city_id: int, city_name: str = None) -> Dict[str, Any]:
        """
        Debug helper to inspect wind speed data for a city.
        
        Returns:
            Dict with:
            - 'city_id': City ID
            - 'city_name': City name (if provided or found)
            - 'total_rows': Total number of rows for this city
            - 'rows_with_wind_speed': Number of rows with non-NULL wind_speed
            - 'rows_high_wind': Number of rows with wind_speed > 15 m/s
            - 'rows_null_wind': Number of rows with wind_speed IS NULL
            - 'min_wind_speed': Minimum wind_speed value
            - 'max_wind_speed': Maximum wind_speed value
            - 'avg_wind_speed': Average wind_speed value
            - 'latest_10_rows': List of latest 10 rows with id, timestamp, measurement_timestamp, wind_speed, source
        """
        result: Dict[str, Any] = {
            "city_id": city_id,
            "city_name": city_name,
            "total_rows": 0,
            "rows_with_wind_speed": 0,
            "rows_high_wind": 0,
            "rows_null_wind": 0,
            "min_wind_speed": None,
            "max_wind_speed": None,
            "avg_wind_speed": None,
            "latest_10_rows": [],
        }
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get city name if not provided
            if not city_name:
                cursor.execute("SELECT name FROM cities WHERE id = ?", (city_id,))
                city_row = cursor.fetchone()
                if city_row:
                    result["city_name"] = city_row[0]
            
            # Get total rows
            cursor.execute("SELECT COUNT(*) FROM weather_data WHERE city_id = ?", (city_id,))
            total = cursor.fetchone()
            if total:
                result["total_rows"] = total[0]
            
            # Get rows with wind_speed
            cursor.execute(
                "SELECT COUNT(*) FROM weather_data WHERE city_id = ? AND wind_speed IS NOT NULL",
                (city_id,)
            )
            with_wind = cursor.fetchone()
            if with_wind:
                result["rows_with_wind_speed"] = with_wind[0]
            
            # Get rows with high wind (>15 m/s)
            cursor.execute(
                "SELECT COUNT(*) FROM weather_data WHERE city_id = ? AND wind_speed > 15.0",
                (city_id,)
            )
            high_wind = cursor.fetchone()
            if high_wind:
                result["rows_high_wind"] = high_wind[0]
            
            # Get rows with NULL wind_speed
            cursor.execute(
                "SELECT COUNT(*) FROM weather_data WHERE city_id = ? AND wind_speed IS NULL",
                (city_id,)
            )
            null_wind = cursor.fetchone()
            if null_wind:
                result["rows_null_wind"] = null_wind[0]
            
            # Get min/max/avg wind_speed
            cursor.execute(
                """SELECT MIN(wind_speed) as min_ws, MAX(wind_speed) as max_ws, AVG(wind_speed) as avg_ws
                   FROM weather_data
                   WHERE city_id = ? AND wind_speed IS NOT NULL""",
                (city_id,)
            )
            stats = cursor.fetchone()
            if stats:
                result["min_wind_speed"] = stats[0]
                result["max_wind_speed"] = stats[1]
                result["avg_wind_speed"] = stats[2]
            
            # Get latest 10 rows sorted by COALESCE(measurement_timestamp, timestamp) DESC
            cursor.execute(
                """SELECT id, timestamp, measurement_timestamp, wind_speed, source
                   FROM weather_data
                   WHERE city_id = ?
                   ORDER BY COALESCE(measurement_timestamp, timestamp) DESC
                   LIMIT 10""",
                (city_id,)
            )
            rows = cursor.fetchall()
            result["latest_10_rows"] = [
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "measurement_timestamp": row[2],
                    "wind_speed": row[3],
                    "source": row[4],
                }
                for row in rows
            ]
            
            return result
        except Exception as e:
            logger.warning(f"Fel vid debug_wind_speed_for_city för city_id={city_id}: {e}")
            return result
    
    def get_latest_weather(self, city_id: int) -> Optional[Dict]:
        """
        Get latest weather data for a city.
        Prefers rows with pollutant data if available.
        Uses measurement_timestamp if available, otherwise falls back to timestamp.
        """
        # No logger to avoid recursion - this is called frequently from GUI
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # First try to get latest row with any pollutant data
            # Use measurement_timestamp if available (more accurate), otherwise timestamp
            cursor.execute(
                """SELECT * FROM weather_data 
                   WHERE city_id = ? 
                   AND (pm25 IS NOT NULL OR pm10 IS NOT NULL OR no2 IS NOT NULL OR o3 IS NOT NULL)
                   ORDER BY COALESCE(measurement_timestamp, timestamp) DESC 
                   LIMIT 1""",
                (city_id,)
            )
            row = cursor.fetchone()
            
            # If no row with pollutants, get latest row regardless
            if not row:
                cursor.execute(
                    """SELECT * FROM weather_data 
                       WHERE city_id = ? 
                       ORDER BY COALESCE(measurement_timestamp, timestamp) DESC 
                       LIMIT 1""",
                    (city_id,)
                )
                row = cursor.fetchone()
            
            return dict(row) if row else None
        except Exception:
            # Return None on error instead of raising
            return None
    
    def get_weather_history(
        self,
        city_id: int,
        hours: int = 24
    ) -> List[Dict]:
        """Get weather history for a city."""
        # No logger to avoid recursion - this is called from analytics
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM weather_data 
                   WHERE city_id = ? AND timestamp > datetime('now', '-' || ? || ' hours')
                   ORDER BY timestamp ASC""",
                (city_id, hours)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            # Return empty list on error instead of raising
            return []
    
    def get_all_latest_weather(self) -> List[Dict]:
        """Get latest weather for all cities.
        Uses COALESCE(measurement_timestamp, timestamp) to get the most accurate latest row.
        """
        # No logger to avoid recursion
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT wd.*, c.name as city_name, c.latitude, c.longitude
                   FROM weather_data wd
                   INNER JOIN cities c ON wd.city_id = c.id
                   INNER JOIN (
                       SELECT city_id, MAX(COALESCE(measurement_timestamp, timestamp)) as max_ts
                       FROM weather_data
                       GROUP BY city_id
                   ) latest ON wd.city_id = latest.city_id 
                          AND COALESCE(wd.measurement_timestamp, wd.timestamp) = latest.max_ts
                   ORDER BY c.name"""
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            # Return empty list on error instead of raising
            return []
    
    def get_total_data_points_count(self) -> int:
        """
        Get total number of rows in weather_data table.
        
        Returns:
            int: Total count of rows (0 if table is empty)
            
        Raises:
            Exception: If database query fails (exceptions propagate)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM weather_data")
        result = cursor.fetchone()
        return result[0] if result else 0
    
    def get_unique_cities_in_data_count(self) -> int:
        """
        Get number of unique cities that have data in weather_data table.
        
        Returns:
            int: Number of unique city_ids (0 if no data)
            
        Raises:
            Exception: If database query fails (exceptions propagate)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT city_id) FROM weather_data")
        result = cursor.fetchone()
        return result[0] if result else 0
    
    # Statistics operations
    def update_daily_stats(
        self,
        date: str,
        coldest_city_id: Optional[int],
        warmest_city_id: Optional[int],
        best_air_quality_city_id: Optional[int],
        worst_air_quality_city_id: Optional[int]
    ):
        """Update or insert daily statistics."""
        # No logger to avoid recursion
        with _write_lock:  # Use lock for write operations
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT OR REPLACE INTO daily_stats 
                       (date, coldest_city_id, warmest_city_id, 
                        best_air_quality_city_id, worst_air_quality_city_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (date, coldest_city_id, warmest_city_id,
                     best_air_quality_city_id, worst_air_quality_city_id)
                )
                conn.commit()
            except Exception:
                # Silently fail for stats updates
                pass
    
    def get_daily_stats(self, date: str) -> Optional[Dict]:
        """Get daily statistics for a date."""
        # No logger to avoid recursion
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM daily_stats WHERE date = ?", (date,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            # Return None on error instead of raising
            return None
    
    def get_weather_data_for_city(self, city_id: int, hours: Optional[int] = None) -> List[Dict]:
        """
        Get weather data for a city.
        
        Args:
            city_id: City ID
            hours: Optional hours to filter (None = ALL data, no time limit)
            
        Returns:
            List of weather data dictionaries, sorted by timestamp ASC
            Empty list if no data found
        """
        # No logger to avoid recursion
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if hours is None:
                # Get ALL data - no time limit
                cursor.execute(
                    """SELECT * FROM weather_data 
                       WHERE city_id = ? 
                       ORDER BY timestamp ASC""",
                    (city_id,)
                )
            else:
                # Time-based filtering: timestamp >= now - timedelta(hours=hours)
                # NOT datapoint-based (NOT .iloc[-N])
                # Use CET timezone for cutoff
                cutoff_time = datetime.now(CET) - timedelta(hours=hours)
                cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute(
                    """SELECT * FROM weather_data 
                       WHERE city_id = ? 
                       AND timestamp >= ?
                       ORDER BY timestamp ASC""",
                    (city_id, cutoff_str)
                )
            
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            # Return empty list on error instead of raising
            return []
    
    def get_all_weather_data(self, hours: Optional[int] = None) -> List[Dict]:
        """
        Get weather data from all cities.
        
        Args:
            hours: Optional hours to filter (None = ALL data, no time limit)
            
        Returns:
            List of weather data dictionaries with city_name, sorted by timestamp ASC
            Empty list if no data found
        """
        # No logger to avoid recursion
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if hours is None:
                # Get ALL data - no time limit
                cursor.execute(
                    """SELECT wd.*, c.name as city_name, c.latitude, c.longitude
                       FROM weather_data wd
                       INNER JOIN cities c ON wd.city_id = c.id
                       ORDER BY wd.timestamp ASC"""
                )
            else:
                # Time-based filtering: timestamp >= now - timedelta(hours=hours)
                # NOT datapoint-based
                # Use CET timezone for cutoff
                cutoff_time = datetime.now(CET) - timedelta(hours=hours)
                cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute(
                    """SELECT wd.*, c.name as city_name, c.latitude, c.longitude
                       FROM weather_data wd
                       INNER JOIN cities c ON wd.city_id = c.id
                       WHERE wd.timestamp >= ?
                       ORDER BY wd.timestamp ASC""",
                    (cutoff_str,)
                )
            
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            # Return empty list on error instead of raising
            return []
    
    # Sensor operations
    def has_sensors_table(self) -> bool:
        """
        Check if sensors table exists.
        
        Returns:
            True if table exists, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sensors'"
            )
            return cursor.fetchone() is not None
        except Exception as e:
            logger.warning(f"Fel vid kontroll av sensors-tabell: {e}")
            return False
    
    def add_sensor(
        self,
        city_id: int,
        sensor_id: Optional[int],
        parameter: Optional[str],
        latitude: float,
        longitude: float,
        last_value: Optional[float] = None,
        last_updated: Optional[datetime] = None,
        is_custom: int = 0,
        custom_info: Optional[str] = None
    ) -> int:
        """
        Add a sensor to the database.
        
        Args:
            city_id: City ID
            sensor_id: OpenAQ sensor ID (None for custom markers)
            parameter: Parameter name (None for custom markers)
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            last_value: Last measured value (None for custom markers)
            last_updated: Last update timestamp
            is_custom: 0 for OpenAQ sensor, 1 for custom marker
            custom_info: JSON string for custom markers (None for OpenAQ sensors)
            
        Returns:
            Sensor ID
        """
        logger.debug(f"Lägger till sensor för stad {city_id}: sensor_id={sensor_id}, parameter={parameter}")
        with _write_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Check if sensor already exists (for OpenAQ sensors with sensor_id)
                if sensor_id is not None and not is_custom:
                    cursor.execute(
                        "SELECT id FROM sensors WHERE city_id = ? AND sensor_id = ?",
                        (city_id, sensor_id)
                    )
                    existing = cursor.fetchone()
                    if existing:
                        # Update existing sensor
                        sensor_db_id = existing['id']
                        cursor.execute(
                            """UPDATE sensors 
                               SET parameter = ?, latitude = ?, longitude = ?, 
                                   last_value = ?, last_updated = ?, custom_info = ?
                               WHERE id = ?""",
                            (parameter, latitude, longitude, last_value, last_updated, custom_info, sensor_db_id)
                        )
                        conn.commit()
                        logger.debug(f"Uppdaterade sensor {sensor_db_id} för stad {city_id}")
                        return sensor_db_id
                
                # Insert new sensor
                cursor.execute(
                    """INSERT INTO sensors 
                       (city_id, sensor_id, parameter, latitude, longitude, last_value, last_updated, is_custom, custom_info)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (city_id, sensor_id, parameter, latitude, longitude, last_value, last_updated, is_custom, custom_info)
                )
                conn.commit()
                sensor_db_id = cursor.lastrowid
                logger.debug(f"Sensor tillagd med ID: {sensor_db_id}")
                return sensor_db_id
            except Exception as e:
                logger.error(f"Fel vid tillägg av sensor: {e}")
                raise
    
    def get_sensors_for_city(self, city_id: int) -> List[Dict]:
        """
        Get all sensors for a city.
        
        Args:
            city_id: City ID
            
        Returns:
            List of sensor dictionaries, empty list if no sensors found
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM sensors 
                   WHERE city_id = ? 
                   ORDER BY is_custom ASC, parameter ASC""",
                (city_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"Fel vid hämtning av sensorer för stad {city_id}: {e}")
            return []
    
    def get_all_sensors(self) -> List[Dict]:
        """
        Get all sensors from all cities.
        
        Returns:
            List of sensor dictionaries with city_name, empty list if no sensors found
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT s.*, c.name as city_name 
                   FROM sensors s
                   INNER JOIN cities c ON s.city_id = c.id
                   ORDER BY c.name ASC, s.is_custom ASC, s.parameter ASC"""
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"Fel vid hämtning av alla sensorer: {e}")
            return []
    
    def update_sensor_value(self, sensor_db_id: int, last_value: Optional[float], last_updated: Optional[datetime]) -> bool:
        """
        Update sensor value and timestamp.
        
        Args:
            sensor_db_id: Sensor database ID
            last_value: New value
            last_updated: Update timestamp
            
        Returns:
            True if updated, False on error
        """
        try:
            with _write_lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """UPDATE sensors 
                       SET last_value = ?, last_updated = ?
                       WHERE id = ?""",
                    (last_value, last_updated, sensor_db_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.warning(f"Fel vid uppdatering av sensor {sensor_db_id}: {e}")
            return False
    
    def add_custom_marker(self, city_id: int, latitude: float, longitude: float, custom_info: str) -> int:
        """
        Add a custom marker.
        
        Args:
            city_id: City ID
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            custom_info: JSON string with marker info (name, description, value, etc.)
            
        Returns:
            Marker ID
        """
        return self.add_sensor(
            city_id=city_id,
            sensor_id=None,
            parameter=None,
            latitude=latitude,
            longitude=longitude,
            last_value=None,
            last_updated=None,
            is_custom=1,
            custom_info=custom_info
        )
    
    # Sensor readings operations (for new sensor engine)
    def add_sensor_reading(self, sensor_id: int, value: float, parameter: str, timestamp: datetime) -> int:
        """
        Add a sensor reading to sensor_readings table.
        
        Args:
            sensor_id: Sensor ID
            value: Reading value
            parameter: Parameter name
            timestamp: Reading timestamp
            
        Returns:
            Reading ID
        """
        try:
            with _write_lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO sensor_readings (sensor_id, value, parameter, timestamp)
                       VALUES (?, ?, ?, ?)""",
                    (sensor_id, value, parameter, timestamp)
                )
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding sensor reading: {e}")
            raise
    
    def batch_add_sensor_readings(self, readings: List[Dict]):
        """
        Batch insert sensor readings.
        
        Args:
            readings: List of dicts with keys: sensor_id, value, parameter, timestamp
        """
        if not readings:
            return
        
        try:
            with _write_lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.executemany(
                    """INSERT INTO sensor_readings (sensor_id, value, parameter, timestamp)
                       VALUES (?, ?, ?, ?)""",
                    [
                        (r['sensor_id'], r['value'], r['parameter'], r['timestamp'])
                        for r in readings
                    ]
                )
                conn.commit()
                logger.debug(f"Batch inserted {len(readings)} sensor readings")
        except Exception as e:
            logger.error(f"Error batch adding sensor readings: {e}")
            raise
    
    def update_sensor_last_value(self, sensor_id: int, value: float, timestamp: datetime):
        """
        Update sensor last_value and last_updated.
        
        Args:
            sensor_id: Sensor ID
            value: New value
            timestamp: Update timestamp
        """
        try:
            with _write_lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """UPDATE sensors 
                       SET last_value = ?, last_updated = ?
                       WHERE id = ?""",
                    (value, timestamp, sensor_id)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating sensor last value: {e}")
            raise
    
    def batch_update_sensor_last_values(self, updates: List[Dict]):
        """
        Batch update sensor last values.
        
        Args:
            updates: List of dicts with keys: sensor_id, last_value, last_updated
        """
        if not updates:
            return
        
        try:
            with _write_lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                for update in updates:
                    cursor.execute(
                        """UPDATE sensors 
                           SET last_value = ?, last_updated = ?
                           WHERE id = ?""",
                        (update['last_value'], update['last_updated'], update['sensor_id'])
                    )
                conn.commit()
                logger.debug(f"Batch updated {len(updates)} sensor last values")
        except Exception as e:
            logger.error(f"Error batch updating sensor last values: {e}")
            raise
    
    def get_sensor_readings(self, sensor_id: int, hours: Optional[int] = None) -> List[Dict]:
        """
        Get sensor readings for a sensor.
        
        Args:
            sensor_id: Sensor ID
            hours: Optional hours to filter (None = all readings)
            
        Returns:
            List of reading dicts
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if hours is None:
                cursor.execute(
                    """SELECT * FROM sensor_readings 
                       WHERE sensor_id = ? 
                       ORDER BY timestamp ASC""",
                    (sensor_id,)
                )
            else:
                cutoff_time = datetime.now(CET) - timedelta(hours=hours)
                cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute(
                    """SELECT * FROM sensor_readings 
                       WHERE sensor_id = ? AND timestamp >= ?
                       ORDER BY timestamp ASC""",
                    (sensor_id, cutoff_str)
                )
            
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting sensor readings: {e}")
            return []
    
    def get_latest_sensor_readings(self) -> List[Dict]:
        """
        Get latest readings for all sensors (for heatmap).
        
        Returns:
            List of dicts with sensor_id, latitude, longitude, last_value
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT s.id as sensor_id, s.latitude, s.longitude, s.last_value
                   FROM sensors s
                   WHERE s.enabled = 1 AND s.visibility_mode = 'heatmap' AND s.last_value IS NOT NULL
                   ORDER BY s.id"""
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting latest sensor readings: {e}")
            return []
    
    def delete_sensor(self, sensor_db_id: int) -> bool:
        """
        Delete a sensor from database.
        
        Args:
            sensor_db_id: Sensor database ID
            
        Returns:
            True if deleted, False on error
        """
        try:
            with _write_lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sensors WHERE id = ?", (sensor_db_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.warning(f"Fel vid borttagning av sensor {sensor_db_id}: {e}")
            return False
    
    # Map analytics queries
    def get_cities_with_weather_for_map(self) -> List[Dict]:
        """
        Single JOIN query returning the latest weather row per city for map rendering.

        Returns:
            List of dicts: city_id, city_name, latitude, longitude,
                           temperature, humidity, wind_speed, pm25, no2, o3
            Empty list if no data found.
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT c.id AS city_id,
                          c.name AS city_name,
                          c.latitude,
                          c.longitude,
                          wd.temperature,
                          wd.humidity,
                          wd.wind_speed,
                          wd.pm25,
                          wd.no2,
                          wd.o3
                   FROM cities c
                   INNER JOIN weather_data wd ON wd.city_id = c.id
                   INNER JOIN (
                       SELECT city_id, MAX(COALESCE(measurement_timestamp, timestamp)) AS max_ts
                       FROM weather_data
                       GROUP BY city_id
                   ) latest ON wd.city_id = latest.city_id
                          AND COALESCE(wd.measurement_timestamp, wd.timestamp) = latest.max_ts
                   ORDER BY c.name"""
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"Fel vid get_cities_with_weather_for_map: {e}")
            return []

    def get_national_pm25_7day_average(self) -> Optional[float]:
        """
        Compute the mean PM2.5 across all cities over the last 168 hours.

        Returns:
            Mean PM2.5 as float, or None if no data exists.
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT AVG(pm25) AS mean_pm25
                   FROM weather_data
                   WHERE pm25 IS NOT NULL
                     AND timestamp > datetime('now', '-168 hours')"""
            )
            row = cursor.fetchone()
            if row and row["mean_pm25"] is not None:
                return float(row["mean_pm25"])
            return None
        except Exception as e:
            logger.warning(f"Fel vid get_national_pm25_7day_average: {e}")
            return None

    def get_parameter_winsorized_bounds(
        self, parameter: str, p_low: int, p_high: int
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Return winsorized (percentile-based) bounds for a weather_data column.

        Fetches the full sorted history for the parameter and computes the
        p_low-th and p_high-th percentile in Python.  A single outlier sensor
        cannot corrupt these bounds as long as it represents less than
        (100 - p_high) percent of all readings.

        Args:
            parameter: Column name in weather_data (e.g. 'wind_speed', 'humidity').
                       Only whitelisted column names are accepted.
            p_low:     Lower percentile (0–100).
            p_high:    Upper percentile (0–100).

        Returns:
            (lower_bound, upper_bound) as floats, or (None, None) if fewer
            than 20 non-null rows exist for the parameter.
        """
        # Check if parameter exists in parameter_registry (dynamic, no hardcoded whitelist)
        try:
            conn_check = self._get_connection()
            cursor_check = conn_check.cursor()
            cursor_check.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parameter_registry'")
            if cursor_check.fetchone() is not None:
                # Table exists - check if parameter is registered
                cursor_check.execute("SELECT parameter_name FROM parameter_registry WHERE parameter_name = ?", (parameter,))
                if cursor_check.fetchone() is None:
                    # Parameter not in registry - trigger auto-discovery first
                    logger.debug(f"Parameter '{parameter}' inte i registry, kör auto-discovery...")
                    self._auto_discover_parameters_from_schema()
                    # Check again after auto-discovery
                    cursor_check.execute("SELECT parameter_name FROM parameter_registry WHERE parameter_name = ?", (parameter,))
                    if cursor_check.fetchone() is None:
                        logger.warning(
                            f"get_parameter_winsorized_bounds: parameter '{parameter}' not found in parameter_registry after auto-discovery"
                        )
                        return None, None
            else:
                # Table doesn't exist - use fallback whitelist for backward compatibility
                ALLOWED_PARAMETERS = {
                    "wind_speed", "humidity", "temperature", "pm25", "pm10", "no2", "o3", "aqi",
                    "solar_radiation", "uv_index", "sunshine_duration"
                }
                if parameter not in ALLOWED_PARAMETERS:
                    logger.warning(
                        f"get_parameter_winsorized_bounds: parameter '{parameter}' not in fallback whitelist (parameter_registry table missing)"
                    )
                    return None, None
        except Exception as e:
            logger.warning(f"Fel vid kontroll av parameter_registry för '{parameter}': {e}")
            # Fallback to whitelist on error
            ALLOWED_PARAMETERS = {
                "wind_speed", "humidity", "temperature", "pm25", "pm10", "no2", "o3", "aqi",
                "solar_radiation", "uv_index", "sunshine_duration"
            }
            if parameter not in ALLOWED_PARAMETERS:
                logger.warning(
                    f"get_parameter_winsorized_bounds: parameter '{parameter}' not in fallback whitelist (error checking registry)"
                )
                return None, None

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get historical data period from calibration_parameters (days)
            # Default to 30 days if not configured (meteorologically better than 7 days)
            history_days = self.get_calibration_parameter('normalization_history_days')
            if history_days is None:
                history_days = 30.0  # Default: 30 days (meteorologically better)
            else:
                history_days = float(history_days)
            
            # Fetch sorted history within time window — column name is safe because of whitelist above
            cursor.execute(
                f"SELECT {parameter} FROM weather_data "
                f"WHERE {parameter} IS NOT NULL "
                f"AND timestamp >= datetime('now', '-' || ? || ' days') "
                f"ORDER BY {parameter} ASC",
                (history_days,)
            )
            rows = [row[0] for row in cursor.fetchall()]

            if len(rows) < 20:
                # Logga bara på DEBUG-nivå för att undvika spam under backfill
                logger.debug(
                    f"get_parameter_winsorized_bounds: insufficient history for "
                    f"'{parameter}' ({len(rows)} rows, need ≥ 20)"
                )
                return None, None

            n = len(rows)
            lo_idx = max(0, int(round(p_low  / 100 * (n - 1))))
            hi_idx = min(n - 1, int(round(p_high / 100 * (n - 1))))
            return float(rows[lo_idx]), float(rows[hi_idx])
        except Exception as e:
            logger.warning(
                f"Fel vid get_parameter_winsorized_bounds('{parameter}'): {e}"
            )
            return None, None
    
    def _auto_generate_normalization_bounds(self, parameter_name: str) -> bool:
        """
        Auto-generate normalization bounds for a parameter when sufficient historical data is available.
        
        Checks if parameter has ≥20 historical data points and if bounds are missing from calibration_parameters.
        If both conditions are met, computes winsorized bounds and stores percentile values.
        
        Args:
            parameter_name: Parameter name (e.g. 'solar_radiation', 'cape')
            
        Returns:
            True if bounds were generated and stored, False otherwise
        """
        try:
            # Check if bounds already exist
            p_low_key = f"{parameter_name}_normalize_p_low"
            p_high_key = f"{parameter_name}_normalize_p_high"
            
            existing_p_low = self.get_calibration_parameter(p_low_key)
            existing_p_high = self.get_calibration_parameter(p_high_key)
            
            # If bounds already exist, skip
            if existing_p_low is not None and existing_p_high is not None:
                logger.debug(f"Normalization bounds för '{parameter_name}' finns redan, hoppar över auto-generering")
                return False
            
            # Get default percentile values (5.0 and 95.0)
            default_p_low = 5.0
            default_p_high = 95.0
            
            # Check if we have sufficient historical data (≥20 rows)
            bounds = self.get_parameter_winsorized_bounds(parameter_name, int(default_p_low), int(default_p_high))
            
            if bounds[0] is None or bounds[1] is None:
                # Insufficient data - cannot generate bounds yet
                logger.debug(f"Otillräcklig historisk data för '{parameter_name}' för att generera bounds (behöver ≥20 rader)")
                return False
            
            lo, hi = bounds
            
            # If bounds are equal, cannot use them
            if lo == hi:
                logger.debug(f"Bounds är lika för '{parameter_name}' (lo=hi={lo}), kan inte generera normalization bounds")
                return False
            
            # Store percentile values in calibration_parameters (not the actual bounds - those are computed dynamically)
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO calibration_parameters (key, value, unit, description, source)
                VALUES (?, ?, ?, ?, ?)
            """, (p_low_key, default_p_low, 'percentile', f'Lower winsorization percentile for {parameter_name} normalization (auto-generated)', 'auto_generation'))
            
            cursor.execute("""
                INSERT OR REPLACE INTO calibration_parameters (key, value, unit, description, source)
                VALUES (?, ?, ?, ?, ?)
            """, (p_high_key, default_p_high, 'percentile', f'Upper winsorization percentile for {parameter_name} normalization (auto-generated)', 'auto_generation'))
            
            conn.commit()
            
            logger.info(f"Auto-genererade normalization bounds för '{parameter_name}': p_low={default_p_low}, p_high={default_p_high} (computed bounds: [{lo}, {hi}])")
            return True
            
        except Exception as e:
            logger.warning(f"Fel vid auto-generering av normalization bounds för '{parameter_name}': {e}")
            return False
    
    def _auto_generate_all_normalization_bounds(self, conn: Optional[sqlite3.Connection] = None):
        """
        Auto-generate normalization bounds for all parameters in weather_data schema.
        Called on startup and after migrations.
        
        Args:
            conn: Optional database connection (if None, uses _get_connection())
        """
        try:
            if conn is None:
                conn = self._get_connection()
            
            # Get all columns from weather_data schema
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(weather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # Filter out non-parameter columns
            excluded = {'id', 'city_id', 'timestamp', 'source', 'aqi', 'measurement_timestamp'}
            parameter_columns = [col for col in columns if col not in excluded]
            
            logger.info(f"Auto-genererar normalization bounds för {len(parameter_columns)} parametrar...")
            
            generated_count = 0
            for param in parameter_columns:
                try:
                    if self._auto_generate_normalization_bounds(param):
                        generated_count += 1
                except Exception as e:
                    logger.debug(f"Kunde inte generera bounds för {param}: {e}")
            
            logger.info(f"Auto-genererade normalization bounds för {generated_count}/{len(parameter_columns)} parametrar")
            
        except Exception as e:
            logger.warning(f"Fel vid auto-generering av alla normalization bounds: {e}")
    
    def _auto_discover_parameters_from_schema(self, conn: Optional[sqlite3.Connection] = None):
        """
        Auto-discover parameters from weather_data schema and register them in parameter_registry.
        Called on startup and after migrations.
        
        Args:
            conn: Optional database connection (if None, uses _get_connection())
        """
        try:
            if conn is None:
                conn = self._get_connection()
            
            # Check if parameter_registry table exists
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parameter_registry'")
            if cursor.fetchone() is None:
                logger.debug("parameter_registry tabell finns inte, hoppar över auto-discovery")
                return
            
            # Get all columns from weather_data schema
            cursor.execute("PRAGMA table_info(weather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # Filter out non-parameter columns
            excluded = {'id', 'city_id', 'timestamp', 'source', 'aqi', 'measurement_timestamp'}
            parameter_columns = [col for col in columns if col not in excluded]
            
            logger.info(f"Auto-upptäcker parametrar från schema: {len(parameter_columns)} parametrar...")
            
            # Category inference mapping
            category_map = {
                'pm25': 'air_quality',
                'pm10': 'air_quality',
                'no2': 'air_quality',
                'o3': 'air_quality',
                'uv_index': 'solar',
                'solar_radiation': 'solar',
                'direct_radiation': 'solar',
                'diffuse_radiation': 'solar',
                'sunshine_duration': 'solar',
                'cape': 'storm',
                'precipitation_probability': 'storm',
                'convective_precipitation': 'storm',
                'temperature': 'weather',
                'humidity': 'weather',
                'wind_speed': 'weather'
            }
            
            # Unit inference mapping
            unit_map = {
                'pm25': 'µg/m³',
                'pm10': 'µg/m³',
                'no2': 'µg/m³',
                'o3': 'µg/m³',
                'uv_index': 'index',
                'solar_radiation': 'W/m²',
                'direct_radiation': 'W/m²',
                'diffuse_radiation': 'W/m²',
                'sunshine_duration': 'seconds',
                'cape': 'J/kg',
                'precipitation_probability': 'percent',
                'convective_precipitation': 'mm',
                'temperature': '°C',
                'humidity': 'percent',
                'wind_speed': 'm/s'
            }
            
            registered_count = 0
            for param in parameter_columns:
                try:
                    # Check if parameter already exists in registry
                    cursor.execute("SELECT parameter_name FROM parameter_registry WHERE parameter_name = ?", (param,))
                    if cursor.fetchone() is not None:
                        continue  # Already registered
                    
                    # Infer category and unit
                    category = category_map.get(param, 'unknown')
                    unit = unit_map.get(param, 'unknown')
                    
                    # Format display name (e.g., "pm25" → "PM2.5", "uv_index" → "UV Index")
                    display_name = param.replace('_', ' ').title()
                    if param == 'pm25':
                        display_name = 'PM2.5'
                    elif param == 'pm10':
                        display_name = 'PM10'
                    elif param == 'no2':
                        display_name = 'NO₂'
                    elif param == 'o3':
                        display_name = 'O₃'
                    
                    # Insert into parameter_registry
                    cursor.execute("""
                        INSERT INTO parameter_registry (parameter_name, display_name, unit, category, description, source)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (param, display_name, unit, category, f'Auto-discovered from schema', 'auto_discovery'))
                    
                    registered_count += 1
                    logger.debug(f"Auto-registrerade parameter: {param} (category={category}, unit={unit})")
                    
                except sqlite3.IntegrityError:
                    # Parameter already exists, skip
                    continue
                except Exception as e:
                    logger.debug(f"Kunde inte registrera parameter {param}: {e}")
            
            conn.commit()
            logger.info(f"Auto-registrerade {registered_count} nya parametrar i parameter_registry")
            
        except Exception as e:
            logger.warning(f"Fel vid parameter registry auto-discovery: {e}")

    # Calibration parameters
    def get_calibration_parameter(self, key: str) -> Optional[float]:
        """
        Get a calibration parameter value by key.
        
        Args:
            key: Parameter key (e.g. 'inversion_p_low', 'idw_power')
            
        Returns:
            Parameter value as float, or None if key not found or error
            
        Raises:
            No exceptions - returns None on error to allow fail-fast handling in callers
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM calibration_parameters WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            if row:
                return float(row[0])
            return None
        except Exception as e:
            logger.warning(f"Fel vid hämtning av calibration parameter '{key}': {e}")
            return None
    
    def get_all_calibration_parameters(self) -> Dict[str, float]:
        """
        Get all calibration parameters as a dictionary.
        
        Returns:
            Dictionary mapping parameter keys to values
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM calibration_parameters")
            rows = cursor.fetchall()
            return {row[0]: float(row[1]) for row in rows}
        except Exception as e:
            logger.warning(f"Fel vid hämtning av alla calibration parameters: {e}")
            return {}
    
    def diagnose_calibration_parameters(self, required_keys: List[str]) -> Dict[str, Any]:
        """
        Diagnostic method to check which calibration parameters exist in database.
        
        Read-only operation - does NOT insert or modify any values.
        Pure diagnostic to understand database state.
        
        Args:
            required_keys: List of parameter keys to check for
            
        Returns:
            Dictionary with:
            - "found": List of keys that exist in database
            - "missing": List of keys that are missing
            - "all_params": Dictionary of all parameters in database (key -> value)
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get all parameters from database
            cursor.execute("SELECT key, value FROM calibration_parameters")
            rows = cursor.fetchall()
            all_params = {row[0]: float(row[1]) for row in rows}
            
            # Check which required keys are found
            found = []
            missing = []
            
            for key in required_keys:
                if key in all_params:
                    found.append(key)
                else:
                    missing.append(key)
            
            return {
                "found": found,
                "missing": missing,
                "all_params": all_params
            }
        except Exception as e:
            logger.warning(f"Fel vid diagnostik av calibration parameters: {e}")
            return {
                "found": [],
                "missing": required_keys,
                "all_params": {}
            }

    # Analytical indices
    def add_analytical_index(
        self,
        city_id: int,
        solar_index: Optional[float] = None,
        storm_risk: Optional[float] = None,
        smog_risk: Optional[float] = None,
        timestamp: Optional[datetime] = None
    ) -> int:
        """
        Add analytical index entry.
        
        Args:
            city_id: City ID
            solar_index: Solar index [0, 1] (optional)
            storm_risk: Storm risk [0, 1] (optional)
            smog_risk: Smog risk [0, 1] (optional)
            timestamp: Optional timestamp (defaults to now)
            
        Returns:
            Analytical index ID
        """
        if timestamp is None:
            timestamp = datetime.now(CET)
        else:
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=CET)
            elif timestamp.tzinfo != CET:
                timestamp = timestamp.astimezone(CET)
        
        with _write_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO analytical_indices 
                       (city_id, timestamp, solar_index, storm_risk, smog_risk)
                       VALUES (?, ?, ?, ?, ?)""",
                    (city_id, timestamp, solar_index, storm_risk, smog_risk)
                )
                conn.commit()
                return cursor.lastrowid
            except Exception as e:
                logger.error(f"Fel vid sparande av analytical index: {e}")
                raise
    
    def get_latest_analytical_indices(self, city_id: int) -> Optional[Dict[str, Optional[float]]]:
        """
        Get latest analytical indices for a city.
        
        Args:
            city_id: City ID
            
        Returns:
            Dictionary with solar_index, storm_risk, smog_risk, or None if not found
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.row_factory = sqlite3.Row
            cursor.execute("""
                SELECT solar_index, storm_risk, smog_risk
                FROM analytical_indices
                WHERE city_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (city_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    'solar_index': float(row['solar_index']) if row['solar_index'] is not None else None,
                    'storm_risk': float(row['storm_risk']) if row['storm_risk'] is not None else None,
                    'smog_risk': float(row['smog_risk']) if row['smog_risk'] is not None else None
                }
            return None
        except Exception as e:
            logger.warning(f"Fel vid hämtning av analytical indices för city {city_id}: {e}")
            return None

    def debug_analytical_data(self, city_id: int) -> Dict:
        """
        Debug helper for analytical indices.

        Returns a dictionary with:
            - latest_weather: latest weather_data row for the city
            - latest_indices: latest analytical_indices row for the city
            - missing_solar_params: list of solar parameters missing in latest_weather
            - missing_storm_params: list of storm parameters missing in latest_weather
        """
        try:
            latest_weather = self.get_latest_weather(city_id)
            latest_indices = self.get_latest_analytical_indices(city_id)

            solar_required = ['solar_radiation', 'uv_index', 'sunshine_duration']
            storm_required = ['cape', 'convective_precipitation', 'precipitation_probability', 'humidity', 'wind_speed']

            missing_solar = []
            missing_storm = []

            if latest_weather:
                missing_solar = [p for p in solar_required if latest_weather.get(p) is None]
                missing_storm = [p for p in storm_required if latest_weather.get(p) is None]

            return {
                "latest_weather": latest_weather,
                "latest_indices": latest_indices,
                "missing_solar_params": missing_solar,
                "missing_storm_params": missing_storm,
            }
        except Exception as e:
            logger.warning(f"Fel vid debug_analytical_data för city {city_id}: {e}")
            return {
                "latest_weather": None,
                "latest_indices": None,
                "missing_solar_params": [],
                "missing_storm_params": [],
            }
    
    def get_solar_data_history(self, city_id: int, hours: int = 24) -> List[Dict]:
        """
        Get historical solar data for a city.
        
        Args:
            city_id: City ID
            hours: Number of hours of history to retrieve
            
        Returns:
            List of dictionaries with timestamp, uv_index, solar_radiation, sunshine_duration
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cutoff_time = datetime.now(CET) - timedelta(hours=hours)
            cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute("""
                SELECT timestamp, uv_index, solar_radiation, sunshine_duration
                FROM weather_data
                WHERE city_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (city_id, cutoff_str))
            
            rows = cursor.fetchall()
            result = []
            for row in rows:
                result.append({
                    'timestamp': row[0],
                    'uv_index': row[1],
                    'solar_radiation': row[2],
                    'sunshine_duration': row[3]
                })
            return result
        except Exception as e:
            logger.warning(f"Fel vid hämtning av solar data history för city {city_id}: {e}")
            return []
    
    def get_lightning_events(self, city_id: Optional[int] = None, hours: int = 24, max_distance_km: Optional[float] = None) -> List[Dict]:
        """
        Get lightning events from database.
        
        Args:
            city_id: Optional city ID to filter by proximity
            hours: Number of hours of history to retrieve
            max_distance_km: Optional maximum distance from city center (if city_id provided)
            
        Returns:
            List of dictionaries with timestamp, latitude, longitude, intensity, distance_km
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cutoff_time = datetime.now(CET) - timedelta(hours=hours)
            cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
            
            if city_id is not None:
                # Get city coordinates
                city = self.get_city(city_id)
                if not city:
                    return []
                
                city_lat = city['latitude']
                city_lon = city['longitude']
                
                # Get all lightning events within time window
                cursor.execute("""
                    SELECT timestamp, latitude, longitude, intensity, distance_km
                    FROM lightning_events
                    WHERE timestamp >= ?
                    ORDER BY timestamp DESC
                """, (cutoff_str,))
                
                rows = cursor.fetchall()
                result = []
                
                for row in rows:
                    strike_lat = row[1]
                    strike_lon = row[2]
                    
                    # Calculate distance using Haversine formula
                    import math
                    R = 6371.0  # Earth radius in km
                    lat1_rad = math.radians(city_lat)
                    lon1_rad = math.radians(city_lon)
                    lat2_rad = math.radians(strike_lat)
                    lon2_rad = math.radians(strike_lon)
                    
                    dlat = lat2_rad - lat1_rad
                    dlon = lon2_rad - lon1_rad
                    
                    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
                    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    distance = R * c
                    
                    # Filter by distance if specified
                    if max_distance_km is None or distance <= max_distance_km:
                        result.append({
                            'timestamp': row[0],
                            'latitude': strike_lat,
                            'longitude': strike_lon,
                            'intensity': row[3],
                            'distance_km': distance
                        })
                
                return result
            else:
                # Get all lightning events (no city filter)
                cursor.execute("""
                    SELECT timestamp, latitude, longitude, intensity, distance_km
                    FROM lightning_events
                    WHERE timestamp >= ?
                    ORDER BY timestamp DESC
                """, (cutoff_str,))
                
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    result.append({
                        'timestamp': row[0],
                        'latitude': row[1],
                        'longitude': row[2],
                        'intensity': row[3],
                        'distance_km': row[4]
                    })
                return result
                
        except Exception as e:
            logger.warning(f"Fel vid hämtning av lightning events: {e}")
            return []

    # Parameter registry operations
    def get_parameter_registry(self) -> List[Dict]:
        """
        Get all parameters from parameter_registry.
        
        Returns:
            List of dictionaries with parameter metadata
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT parameter_name, display_name, unit, category, description, 
                       min_value, max_value, source, updated_at
                FROM parameter_registry
                ORDER BY category, parameter_name
            """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.warning(f"Fel vid hämtning av parameter_registry: {e}")
            return []
    
    def get_parameters_by_category(self, category: str) -> List[Dict]:
        """
        Get parameters filtered by category.
        
        Args:
            category: Category name ('weather', 'air_quality', 'solar', 'storm', 'lightning')
            
        Returns:
            List of dictionaries with parameter metadata
        """
        import time
        query_start = time.time()
        logger.debug(f"[{time.time():.3f}] DatabaseManager.get_parameters_by_category() - Starting query for category: {category}")
        try:
            logger.debug(f"[{time.time():.3f}] DatabaseManager.get_parameters_by_category() - Getting connection for category: {category}")
            conn = self._get_connection()
            if conn is None:
                logger.warning(f"[{time.time():.3f}] DatabaseManager.get_parameters_by_category() - Connection is None for category: {category}")
                return []
            
            logger.debug(f"[{time.time():.3f}] DatabaseManager.get_parameters_by_category() - Creating cursor for category: {category}")
            cursor = conn.cursor()
            
            # Dynamiskt upptäck vilka kolumner som finns (ingen hardcoding)
            cursor.execute("PRAGMA table_info(parameter_registry)")
            available_columns = [row[1] for row in cursor.fetchall()]
            
            # Bygg SELECT-klausul dynamiskt baserat på tillgängliga kolumner
            # Prioritera viktiga kolumner, men hoppa över om de saknas
            select_columns = []
            priority_columns = ['parameter_name', 'display_name', 'unit', 'category', 'description', 
                               'min_value', 'max_value', 'source', 'updated_at']
            
            for col in priority_columns:
                if col in available_columns:
                    select_columns.append(col)
            
            # Om inga kolumner hittades, använd minsta möjliga set
            if not select_columns:
                select_columns = ['parameter_name', 'category']
            
            select_clause = ', '.join(select_columns)
            
            logger.debug(f"[{time.time():.3f}] DatabaseManager.get_parameters_by_category() - Executing query for category: {category} (columns: {select_clause})")
            cursor.execute(f"""
                SELECT {select_clause}
                FROM parameter_registry
                WHERE category = ?
                ORDER BY parameter_name
            """, (category,))
            logger.debug(f"[{time.time():.3f}] DatabaseManager.get_parameters_by_category() - Fetching rows for category: {category}")
            rows = cursor.fetchall()
            query_time = time.time() - query_start
            logger.debug(f"[{time.time():.3f}] DatabaseManager.get_parameters_by_category() - Query completed for category: {category} (took {query_time:.3f}s, got {len(rows)} rows)")
            return [dict(row) for row in rows]
        except Exception as e:
            query_time = time.time() - query_start
            logger.warning(f"[{time.time():.3f}] DatabaseManager.get_parameters_by_category() - Error getting parameters for category '{category}' (query took {query_time:.3f}s): {e}", exc_info=True)
            return []
    
    def get_parameter_metadata(self, parameter_name: str) -> Optional[Dict]:
        """
        Get metadata for a single parameter.
        
        Args:
            parameter_name: Parameter name (e.g. 'cape', 'storm_risk')
            
        Returns:
            Dictionary with parameter metadata, or None if not found
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT parameter_name, display_name, unit, category, description, 
                       min_value, max_value, source, updated_at
                FROM parameter_registry
                WHERE parameter_name = ?
            """, (parameter_name,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.warning(f"Fel vid hämtning av metadata för parameter '{parameter_name}': {e}")
            return None

    def get_schema_health(self) -> Dict[str, Any]:
        """
        Get a dynamic view of database schema health.

        Returns:
            Dict with:
                - tables: List of table names
                - columns: Mapping table -> list of column names (or None if table missing)
                - migrations_on_disk: List of migration_*.sql files found on disk
                - expected_columns: Declarativ mapping migration -> expected columns per table
                - missing_columns: Mapping table -> list of missing columns vs expected
        """
        result: Dict[str, Any] = {
            "tables": [],
            "columns": {},
            "migrations_on_disk": [],
            "expected_columns": {},
            "missing_columns": {},
        }

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            result["tables"] = tables

            # Columns for key tables
            for table in ("weather_data", "parameter_registry", "calibration_parameters"):
                if table in tables:
                    cursor.execute(f"PRAGMA table_info({table})")
                    cols = [row[1] for row in cursor.fetchall()]
                    result["columns"][table] = cols
                else:
                    result["columns"][table] = None

            # Migrations present on disk (dynamic, no hardcoded list)
            migration_dir = Path(__file__).parent
            result["migrations_on_disk"] = sorted(
                [p.name for p in migration_dir.glob("migration_*.sql")]
            )

            # Declarativ mapping: vilka kolumner vissa migrations förväntas skapa.
            # Detta är ett schema-kontrakt, inte en körbar migrationslista.
            expected_by_migration: Dict[str, Dict[str, List[str]]] = {
                "migration_add_weather_columns.sql": {
                    "weather_data": [
                        "measurement_timestamp",
                        "uv_index",
                        "solar_radiation",
                        "direct_radiation",
                        "diffuse_radiation",
                        "sunshine_duration",
                        "cape",
                        "precipitation_probability",
                        "convective_precipitation",
                    ]
                }
            }

            result["expected_columns"] = expected_by_migration

            # Beräkna saknade kolumner per tabell baserat på expected_by_migration
            missing_by_table: Dict[str, List[str]] = {}
            for migration_name, table_map in expected_by_migration.items():
                for table_name, expected_cols in table_map.items():
                    actual_cols = result["columns"].get(table_name) or []
                    # actual_cols kan vara None om tabellen saknas helt
                    if not actual_cols:
                        # Alla kolumner saknas om tabellen inte finns
                        missing_by_table.setdefault(table_name, [])
                        for col in expected_cols:
                            if col not in missing_by_table[table_name]:
                                missing_by_table[table_name].append(col)
                        continue

                    for col in expected_cols:
                        if col not in actual_cols:
                            missing_by_table.setdefault(table_name, [])
                            if col not in missing_by_table[table_name]:
                                missing_by_table[table_name].append(col)

            result["missing_columns"] = missing_by_table
        except Exception as e:
            logger.warning(f"Fel vid get_schema_health: {e}")

        return result

    def diagnose_backfill_schema(self) -> Dict[str, Any]:
        """
        Dynamisk diagnos av skillnader mellan backfillens parametrar och weather_data-schemat.

        Returns:
            Dict med:
                - weather_columns: list of actual columns in weather_data
                - backfill_parameters: dynamic list of parameters backfill tries to save
                - missing_in_db: list of parameters used by backfill but missing in weather_data
        """
        diagnosis: Dict[str, Any] = {
            "weather_columns": [],
            "backfill_parameters": [],
            "missing_in_db": [],
        }

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 1) Hämta faktiska kolumner i weather_data
            cursor.execute("PRAGMA table_info(weather_data)")
            weather_cols = [row[1] for row in cursor.fetchall()]
            diagnosis["weather_columns"] = weather_cols

            # 2) Hämta parametrar som backfill använder via parameter_registry/provider_mappings
            #    (weather/solar/storm), samma logik som backfill_history/discover_parameters_for_backfill.
            backfill_params: List[str] = []
            for category in ("weather", "solar", "storm"):
                try:
                    params = self.get_parameters_by_category(category)
                    for p in params:
                        name = p.get("parameter_name")
                        if name and name not in backfill_params:
                            backfill_params.append(name)
                except Exception as e:
                    logger.debug(f"diagnose_backfill_schema: kunde inte läsa parametrar för kategori {category}: {e}")
                    continue

            diagnosis["backfill_parameters"] = sorted(backfill_params)

            # 3) Saknade kolumner = parametrar som backfill vill spara, men som inte finns som kolumn
            missing = [p for p in backfill_params if p not in weather_cols]
            diagnosis["missing_in_db"] = sorted(missing)

        except Exception as e:
            logger.warning(f"diagnose_backfill_schema: fel vid diagnos av backfill/schema: {e}")

        return diagnosis

    def get_missing_calibration_keys(self) -> List[str]:
        """
        Dynamiskt identifiera saknade calibration_parameters-nycklar.

        Metod:
            - Skanna analytics-kod efter get_calibration_parameter('key')
            - Jämför med existerande nycklar i calibration_parameters

        Returns:
            Lista av nycklar som refereras i kod men saknas i tabellen.
        """
        required_keys = set()

        try:
            analytics_dir = Path(__file__).resolve().parent.parent / "analytics"
            if analytics_dir.exists():
                pattern = re.compile(r"get_calibration_parameter\\('([^']+)'\\)")
                for py_file in analytics_dir.glob("*.py"):
                    try:
                        text = py_file.read_text(encoding="utf-8")
                        for match in pattern.finditer(text):
                            required_keys.add(match.group(1))
                    except Exception as e:
                        logger.debug(f"Kunde inte läsa {py_file}: {e}")

            if not required_keys:
                return []

            conn = self._get_connection()
            cursor = conn.cursor()

            # Check if calibration_parameters table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='calibration_parameters'"
            )
            if cursor.fetchone() is None:
                # Table missing entirely – all required keys are effectively missing
                return sorted(required_keys)

            cursor.execute("SELECT key FROM calibration_parameters")
            existing = {row[0] for row in cursor.fetchall()}

            missing = sorted(required_keys - existing)
            return missing
        except Exception as e:
            logger.warning(f"Fel vid get_missing_calibration_keys: {e}")
            return []
    
    def get_weather_data_batch(
        self,
        city_id: int,
        start_time: datetime,
        parameter_names: Optional[List[str]] = None
    ) -> Dict[str, List[Tuple[datetime, float]]]:
        """
        Get weather data for multiple parameters in single query.
        
        Uses PRAGMA to discover metadata columns dynamically (no hardcoded exclusion list).
        
        Args:
            city_id: City ID
            start_time: Start time for data filtering
            parameter_names: Optional list of parameter names to filter
        
        Returns:
            Dictionary mapping parameter_name -> [(timestamp, value), ...]
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Discover metadata columns via PRAGMA and parameter_registry (fully dynamic)
            cursor.execute("PRAGMA table_info(weather_data)")
            table_info = cursor.fetchall()
            
            # Identify metadata columns dynamically:
            # A column is metadata if it's NOT in parameter_registry
            # This makes the system schema-agnostic - new columns automatically handled
            metadata_columns = set()
            for col_info in table_info:
                col_name = col_info[1]
                # Check if column is registered as a parameter
                cursor_check = conn.cursor()
                cursor_check.execute(
                    "SELECT COUNT(*) FROM parameter_registry WHERE parameter_name = ?",
                    (col_name,)
                )
                is_parameter = cursor_check.fetchone()[0] > 0
                
                # If not in parameter_registry, it's metadata
                if not is_parameter:
                    metadata_columns.add(col_name)
            
            # Build dynamic SELECT based on requested parameters
            if parameter_names:
                # Only select requested parameters (exclude metadata)
                valid_params = [p for p in parameter_names if p not in metadata_columns]
                if not valid_params:
                    return {}
                param_cols = ', '.join([f"`{p}`" for p in valid_params])
                select_clause = f"timestamp, {param_cols}"
            else:
                # Select all (will filter in memory)
                select_clause = "*"
            
            start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(f"""
                SELECT {select_clause}
                FROM weather_data
                WHERE city_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (city_id, start_str))
            
            rows = cursor.fetchall()
            if not rows:
                return {}
            
            # Group by parameter (exclude metadata columns dynamically)
            result = {}
            for row in rows:
                row_dict = dict(row)
                ts_raw = row_dict.get('timestamp')
                if not ts_raw:
                    continue
                
                # Parse timestamp
                try:
                    if isinstance(ts_raw, datetime):
                        ts = ts_raw
                    elif isinstance(ts_raw, str):
                        # Handle timezone-aware and naive strings
                        if 'T' in ts_raw or ' ' in ts_raw:
                            # Try parsing with timezone
                            try:
                                ts = datetime.fromisoformat(ts_raw.replace('Z', '+00:00'))
                            except ValueError:
                                # Try without timezone
                                ts = datetime.strptime(ts_raw, '%Y-%m-%d %H:%M:%S')
                                # Localize to CET if naive
                                if ts.tzinfo is None:
                                    ts = ts.replace(tzinfo=CET)
                        else:
                            continue
                    else:
                        continue
                except (ValueError, AttributeError, TypeError):
                    continue
                
                # Iterate through all columns, skip metadata (discovered via PRAGMA)
                for param_name, value in row_dict.items():
                    if param_name in metadata_columns:
                        continue
                    if param_name == 'timestamp':
                        continue
                    if parameter_names and param_name not in parameter_names:
                        continue
                    if value is not None:
                        if param_name not in result:
                            result[param_name] = []
                        try:
                            result[param_name].append((ts, float(value)))
                        except (ValueError, TypeError):
                            continue
            
            return result
        except Exception as e:
            logger.warning(f"Error in get_weather_data_batch: {e}")
            return {}
    
    # Cleanup operations
    def cleanup_old_data(self, days: int):
        """Delete weather data older than specified days."""
        with _write_lock:  # Use lock for write operations
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM weather_data WHERE timestamp < datetime('now', '-' || ? || ' days')",
                    (days,)
                )
                conn.commit()
                return cursor.rowcount
            except Exception:
                # Return 0 on error instead of raising
                return 0
