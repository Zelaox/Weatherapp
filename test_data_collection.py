"""Test script to manually trigger data collection and see if OpenAQ data is saved."""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from controllers.weather_controller import WeatherController
from database.db_manager import DatabaseManager
import time

def test_data_collection():
    """Test data collection for one city."""
    print("="*60)
    print("Testing Data Collection")
    print("="*60)
    
    # Initialize controller
    print("\nInitializing WeatherController...")
    controller = WeatherController()
    
    # Get first city
    cities = controller.get_all_cities()
    if not cities:
        print("[ERROR] No cities in database!")
        return
    
    test_city = cities[0]
    print(f"\nTesting with city: {test_city['name']} (ID: {test_city['id']})")
    print(f"Coordinates: {test_city['latitude']}, {test_city['longitude']}")
    
    # Check current data count
    db = controller.db
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM weather_data 
        WHERE city_id = ?
    """, (test_city['id'],))
    before_count = cursor.fetchone()['count']
    print(f"\nWeather_data records before: {before_count}")
    
    # Trigger update
    print("\nTriggering weather update...")
    try:
        controller._update_city_weather(test_city)
        print("[OK] Update completed")
    except Exception as e:
        print(f"[ERROR] Update failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Wait a bit for database to commit
    time.sleep(1)
    
    # Check new data count
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM weather_data 
        WHERE city_id = ?
    """, (test_city['id'],))
    after_count = cursor.fetchone()['count']
    print(f"Weather_data records after: {after_count}")
    
    if after_count > before_count:
        print(f"[OK] New data was saved! ({after_count - before_count} new records)")
        
        # Check latest record
        cursor.execute("""
            SELECT temperature, humidity, wind_speed, pm25, pm10, no2, o3, source, timestamp
            FROM weather_data
            WHERE city_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (test_city['id'],))
        latest = cursor.fetchone()
        if latest:
            print("\nLatest saved data:")
            print(f"  Source: {latest['source']}")
            print(f"  Temperature: {latest['temperature']}°C")
            print(f"  Humidity: {latest['humidity']}%")
            print(f"  Wind Speed: {latest['wind_speed']} m/s")
            print(f"  PM2.5: {latest['pm25'] if latest['pm25'] is not None else 'N/A'}")
            print(f"  PM10: {latest['pm10'] if latest['pm10'] is not None else 'N/A'}")
            print(f"  NO2: {latest['no2'] if latest['no2'] is not None else 'N/A'}")
            print(f"  O3: {latest['o3'] if latest['o3'] is not None else 'N/A'}")
            print(f"  Timestamp: {latest['timestamp']}")
    else:
        print("[WARNING] No new data was saved")
    
    print("\n" + "="*60)
    print("Test complete")
    print("="*60)

if __name__ == "__main__":
    test_data_collection()
