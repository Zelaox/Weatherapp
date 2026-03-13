"""Script to add all Swedish cities from city_loader to the database."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from database.db_manager import DatabaseManager
from utils.city_loader import SWEDISH_CITIES
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AddCities")

def main():
    """Add all cities from SWEDISH_CITIES to the database."""
    logger.info("=" * 60)
    logger.info("Adding Swedish cities to database")
    logger.info("=" * 60)
    
    try:
        # Initialize database
        db = DatabaseManager()
        logger.info("Database connection established")
        
        # Get existing cities
        existing_cities = db.get_all_cities()
        existing_names = {city['name'].lower() for city in existing_cities}
        logger.info(f"Found {len(existing_cities)} existing cities in database")
        
        # Filter out cities that already exist
        cities_to_add = [
            city for city in SWEDISH_CITIES
            if city['name'].lower() not in existing_names
        ]
        
        if not cities_to_add:
            logger.info("All cities from SWEDISH_CITIES are already in the database!")
            return
        
        logger.info(f"Adding {len(cities_to_add)} new cities...")
        
        # Add cities
        added_count = 0
        skipped_count = 0
        
        for city in cities_to_add:
            try:
                city_id = db.add_city(city['name'], city['lat'], city['lon'])
                logger.info(f"✓ Added: {city['name']} (ID: {city_id})")
                added_count += 1
            except ValueError as e:
                # City already exists (race condition or case sensitivity issue)
                logger.debug(f"⊘ Skipped {city['name']}: {e}")
                skipped_count += 1
            except Exception as e:
                logger.error(f"✗ Failed to add {city['name']}: {e}")
        
        logger.info("=" * 60)
        logger.info(f"Summary:")
        logger.info(f"  Added: {added_count}")
        logger.info(f"  Skipped: {skipped_count}")
        logger.info(f"  Total in database: {len(db.get_all_cities())}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
