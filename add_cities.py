"""Add Uppsala and Värnamo to the database."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager

def main():
    db = DatabaseManager()
    
    cities_to_add = [
        {"name": "Uppsala", "lat": 59.8586, "lon": 17.6389},
        {"name": "Värnamo", "lat": 57.1861, "lon": 14.0400}
    ]
    
    print("Lägger till städer:")
    print("=" * 60)
    
    for city in cities_to_add:
        try:
            # Check if city already exists
            existing_cities = db.get_all_cities()
            existing_names = {c['name'].lower() for c in existing_cities}
            
            if city['name'].lower() in existing_names:
                print(f"[SKIP] {city['name']} finns redan i databasen")
            else:
                city_id = db.add_city(city['name'], city['lat'], city['lon'])
                print(f"[OK] Lade till: {city['name']} (ID: {city_id}, lat: {city['lat']}, lon: {city['lon']})")
        except ValueError as e:
            print(f"[ERROR] Kunde inte lägga till {city['name']}: {e}")
        except Exception as e:
            print(f"[ERROR] Oväntat fel vid tillägg av {city['name']}: {e}")
    
    # Verify
    all_cities = db.get_all_cities()
    print(f"\n{'='*60}")
    print(f"Totalt antal städer nu: {len(all_cities)}")
    
    # Check if cities were added
    city_names = {c['name'] for c in all_cities}
    for city in cities_to_add:
        if city['name'] in city_names:
            print(f"[OK] {city['name']} finns i databasen")
        else:
            print(f"[FAIL] {city['name']} saknas i databasen")

if __name__ == "__main__":
    main()
