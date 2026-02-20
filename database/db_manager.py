"""Database manager for SQLite operations."""

import sqlite3
import os
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import logging

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
        self.db_path = db_path
        self._init_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """
        Get database connection with thread-local storage.
        Don't use logger here to avoid potential recursion.
        """
        # Use thread-local storage to avoid connection conflicts
        if not hasattr(_thread_local, 'connection') or _thread_local.connection is None:
            _thread_local.connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=10.0
            )
            _thread_local.connection.row_factory = sqlite3.Row
        else:
            # Check if connection is still valid
            try:
                _thread_local.connection.execute("SELECT 1")
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                # Connection is closed or invalid, create new one
                try:
                    _thread_local.connection.close()
                except Exception:
                    pass
                _thread_local.connection = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    timeout=10.0
                )
                _thread_local.connection.row_factory = sqlite3.Row
        return _thread_local.connection
    
    def get_connection(self) -> sqlite3.Connection:
        """
        Public method to get database connection.
        Use this instead of accessing _get_connection() directly.
        """
        return self._get_connection()
    
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
        try:
            cursor = conn.cursor()
            # Check if pm25 column exists
            cursor.execute("PRAGMA table_info(weather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'pm25' not in columns:
                logger.info("Kör migration för att lägga till pollutant-kolumner...")
                migration_path = Path(__file__).parent / "migration_add_pollutants.sql"
                if migration_path.exists():
                    with open(migration_path, 'r', encoding='utf-8') as f:
                        migration_sql = f.read()
                    conn.executescript(migration_sql)
                    conn.commit()
                    logger.info("Migration klar: pollutant-kolumner tillagda")
                else:
                    logger.warning(f"Migration file not found: {migration_path}")
            
            # Check if sensors table exists
            if not self.has_sensors_table():
                logger.info("Kör migration för att lägga till sensors-tabell...")
                migration_path = Path(__file__).parent / "migration_add_sensors_table.sql"
                if migration_path.exists():
                    with open(migration_path, 'r', encoding='utf-8') as f:
                        migration_sql = f.read()
                    conn.executescript(migration_sql)
                    conn.commit()
                    logger.info("Migration klar: sensors-tabell tillagd")
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
        aqi: Optional[float] = None  # Kept for backward compatibility, calculated on-demand
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
        logger.debug(f"Lägger till väderdata för stad {city_id} från {source}: temp={temperature}°C, PM2.5={pm25}, PM10={pm10}")
        with _write_lock:  # Use lock for write operations
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Use measurement_timestamp if provided, otherwise use timestamp, otherwise use now
                if measurement_timestamp is not None:
                    ts = measurement_timestamp
                    # Ensure timezone-aware (CET)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=CET)
                    elif ts.tzinfo != CET:
                        ts = ts.astimezone(CET)
                elif timestamp is not None:
                    ts = timestamp
                    # Ensure timezone-aware (CET)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=CET)
                    elif ts.tzinfo != CET:
                        ts = ts.astimezone(CET)
                else:
                    ts = datetime.now(CET)
                
                cursor.execute(
                    """INSERT INTO weather_data 
                       (city_id, temperature, humidity, wind_speed, pm25, pm10, no2, o3, aqi, timestamp, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (city_id, temperature, humidity, wind_speed, pm25, pm10, no2, o3, aqi, ts, source)
                )
                conn.commit()
                data_id = cursor.lastrowid
                logger.debug(f"Väderdata sparad med ID: {data_id}, timestamp: {ts}")
                return data_id
            except Exception as e:
                logger.error(f"Fel vid sparande av väderdata: {e}")
                raise
    
    def get_24h_rolling_average(self, city_id: int, parameter: str) -> Optional[float]:
        """
        Get 24h rolling average for a pollutant parameter.
        
        Args:
            city_id: City ID
            parameter: Parameter name ('pm25', 'pm10', 'no2', 'o3')
            
        Returns:
            24h rolling average value, or None if insufficient data (< 12 hours)
        """
        if parameter not in ['pm25', 'pm10', 'no2', 'o3']:
            logger.warning(f"Invalid parameter: {parameter}")
            return None
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get last 24 hours of data for this city and parameter
            cursor.execute(
                f"""SELECT {parameter}, timestamp 
                   FROM weather_data 
                   WHERE city_id = ? 
                   AND {parameter} IS NOT NULL
                   AND timestamp >= datetime('now', '-24 hours')
                   ORDER BY timestamp""",
                (city_id,)
            )
            
            rows = cursor.fetchall()
            if not rows:
                return None
            
            # Calculate average
            values = [row[0] for row in rows if row[0] is not None]
            if not values:
                return None
            
            # Accept any data available (changed from 6 to 1)
            # For 24h rolling average, we accept even single measurements
            # This allows showing data even if collection just started
            if len(values) < 1:
                return None
            
            avg = sum(values) / len(values)
            logger.debug(f"24h rolling average {parameter} for city {city_id}: {avg:.2f} (from {len(values)} values)")
            return avg
            
        except Exception as e:
            logger.error(f"Fel vid beräkning av 24h medelvärde för {parameter}: {e}")
            return None
    
    def get_latest_pollutant_values(self, city_id: int) -> Optional[Dict]:
        """
        Get latest pollutant values for a city.
        
        Args:
            city_id: City ID
            
        Returns:
            Dictionary with pm25, pm10, no2, o3 values, or None if no data
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT pm25, pm10, no2, o3 
                   FROM weather_data 
                   WHERE city_id = ? 
                   AND (pm25 IS NOT NULL OR pm10 IS NOT NULL OR no2 IS NOT NULL OR o3 IS NOT NULL)
                   ORDER BY timestamp DESC 
                   LIMIT 1""",
                (city_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    'pm25': row['pm25'],
                    'pm10': row['pm10'],
                    'no2': row['no2'],
                    'o3': row['o3']
                }
            return None
        except Exception as e:
            logger.warning(f"Fel vid hämtning av senaste pollutant-värden: {e}")
            return None
    
    def get_latest_weather(self, city_id: int) -> Optional[Dict]:
        """Get latest weather data for a city."""
        # No logger to avoid recursion - this is called frequently from GUI
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM weather_data 
                   WHERE city_id = ? 
                   ORDER BY timestamp DESC 
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
        """Get latest weather for all cities."""
        # No logger to avoid recursion
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT wd.*, c.name as city_name, c.latitude, c.longitude
                   FROM weather_data wd
                   INNER JOIN cities c ON wd.city_id = c.id
                   INNER JOIN (
                       SELECT city_id, MAX(timestamp) as max_ts
                       FROM weather_data
                       GROUP BY city_id
                   ) latest ON wd.city_id = latest.city_id AND wd.timestamp = latest.max_ts
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
