"""Script to add all parameters/pollutants to parameter_registry table."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from database.db_manager import DatabaseManager
import logging
import sqlite3

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AddParameters")

def main():
    """Add all parameters to parameter_registry table."""
    logger.info("=" * 60)
    logger.info("Adding parameters/pollutants to parameter_registry")
    logger.info("=" * 60)
    
    try:
        # Initialize database
        db = DatabaseManager()
        logger.info("Database connection established")
        
        # Get connection
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Check if parameter_registry table exists, create if not
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parameter_registry'")
        has_table = cursor.fetchone() is not None
        
        if not has_table:
            logger.info("Creating parameter_registry table...")
            cursor.execute("""
                CREATE TABLE parameter_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parameter_name TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT,
                    min_value REAL,
                    max_value REAL,
                    variation_threshold REAL,
                    variation_mode TEXT DEFAULT 'none',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_parameter_registry_name ON parameter_registry(parameter_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_parameter_registry_category ON parameter_registry(category)")
            conn.commit()
            logger.info("parameter_registry table created")
        
        # Get existing parameters
        cursor.execute("SELECT parameter_name FROM parameter_registry")
        existing_params = {row[0] for row in cursor.fetchall()}
        logger.info(f"Found {len(existing_params)} existing parameters in database")
        
        # Define all parameters
        parameters = [
            # Air Quality Pollutants
            ('pm25', 'PM2.5', 'µg/m³', 'air_quality', 'Particulate matter 2.5 micrometers or smaller', 'percentile'),
            ('pm10', 'PM10', 'µg/m³', 'air_quality', 'Particulate matter 10 micrometers or smaller', 'percentile'),
            ('no2', 'NO₂', 'µg/m³', 'air_quality', 'Nitrogen dioxide', 'percentile'),
            ('o3', 'O₃', 'µg/m³', 'air_quality', 'Ozone', 'percentile'),
            ('co', 'CO', 'µg/m³', 'air_quality', 'Carbon monoxide', 'percentile'),
            ('so2', 'SO₂', 'µg/m³', 'air_quality', 'Sulfur dioxide', 'percentile'),
            ('nh3', 'NH₃', 'µg/m³', 'air_quality', 'Ammonia', 'percentile'),
            ('bc', 'Black Carbon', 'µg/m³', 'air_quality', 'Black carbon (soot)', 'percentile'),
            
            # Weather Parameters
            ('temperature', 'Temperatur', '°C', 'weather', 'Air temperature', 'range'),
            ('humidity', 'Luftfuktighet', '%', 'weather', 'Relative humidity', 'range'),
            ('wind_speed', 'Vindhastighet', 'm/s', 'weather', 'Wind speed', 'range'),
            ('wind_direction', 'Vindriktning', '°', 'weather', 'Wind direction in degrees', 'range'),
            ('pressure', 'Lufttryck', 'hPa', 'weather', 'Atmospheric pressure', 'range'),
            ('precipitation', 'Nederbörd', 'mm', 'weather', 'Precipitation amount', 'range'),
            ('cloud_cover', 'Molnighet', '%', 'weather', 'Cloud cover percentage', 'range'),
            ('visibility', 'Sikt', 'km', 'weather', 'Visibility distance', 'range'),
            ('uv_index', 'UV-index', '', 'weather', 'Ultraviolet index', 'range'),
            ('dew_point', 'Daggpunkt', '°C', 'weather', 'Dew point temperature', 'range'),
            ('feels_like', 'Känns som', '°C', 'weather', 'Feels like temperature', 'range'),
            ('heat_index', 'Värmeindex', '°C', 'weather', 'Heat index', 'range'),
            ('wind_chill', 'Vindavkylning', '°C', 'weather', 'Wind chill temperature', 'range'),
            
            # Air Quality Index
            ('aqi', 'Luftkvalitetsindex', '', 'air_quality', 'Air Quality Index', 'range'),
        ]
        
        # Filter out parameters that already exist
        parameters_to_add = [
            p for p in parameters
            if p[0] not in existing_params
        ]
        
        if not parameters_to_add:
            logger.info("All parameters are already in the database!")
            return
        
        logger.info(f"Adding {len(parameters_to_add)} new parameters...")
        
        # Add parameters
        added_count = 0
        skipped_count = 0
        
        for param_name, display_name, unit, category, description, variation_mode in parameters_to_add:
            try:
                cursor.execute("""
                    INSERT INTO parameter_registry 
                    (parameter_name, display_name, unit, category, description, variation_mode)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (param_name, display_name, unit, category, description, variation_mode))
                logger.info(f"✓ Added: {display_name} ({param_name})")
                added_count += 1
            except sqlite3.IntegrityError:
                logger.debug(f"⊘ Skipped {param_name}: already exists")
                skipped_count += 1
            except Exception as e:
                logger.error(f"✗ Failed to add {param_name}: {e}")
        
        conn.commit()
        
        logger.info("=" * 60)
        logger.info(f"Summary:")
        logger.info(f"  Added: {added_count}")
        logger.info(f"  Skipped: {skipped_count}")
        cursor.execute("SELECT COUNT(*) as count FROM parameter_registry")
        total_count = cursor.fetchone()['count']
        logger.info(f"  Total in database: {total_count}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
