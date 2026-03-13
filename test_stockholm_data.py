"""Test data collection for Stockholm (which has OpenAQ data)."""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from controllers.weather_controller import WeatherController
from database.db_manager import DatabaseManager
import time

def test_stockholm():
    """Test data collection for Stockholm."""
    print("="*60)
    print("Testing Data Collection for Stockholm")
    print("="*60)
    
    controller = WeatherController()
    
    # Get Stockholm
    cities = controller.get_all_cities()
    stockholm = next((c for c in cities if c['name'].lower() == 'stockholm'), None)
    
    if not stockholm:
        print("[ERROR] Stockholm not found in database!")
        return
    
    print(f"\nTesting with: {stockholm['name']} (ID: {stockholm['id']})")
    print(f"Coordinates: {stockholm['latitude']}, {stockholm['longitude']}")
    
    # Check current data
    db = controller.db
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM weather_data 
        WHERE city_id = ?
    """, (stockholm['id'],))
    before_count = cursor.fetchone()['count']
    print(f"\nWeather_data records before: {before_count}")
    
    # Check for pollutant data
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM weather_data 
        WHERE city_id = ? 
        AND (pm25 IS NOT NULL OR pm10 IS NOT NULL OR no2 IS NOT NULL OR o3 IS NOT NULL)
    """, (stockholm['id'],))
    pollutant_count = cursor.fetchone()['count']
    print(f"Records with pollutant data: {pollutant_count}")
    
    # Trigger update
    print("\nTriggering weather update...")
    try:
        controller._update_city_weather(stockholm)
        print("[OK] Update completed")
    except Exception as e:
        print(f"[ERROR] Update failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    time.sleep(1)
    
    # Check new data
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM weather_data 
        WHERE city_id = ?
    """, (stockholm['id'],))
    after_count = cursor.fetchone()['count']
    print(f"Weather_data records after: {after_count}")
    
    # Check latest record with pollutants
    cursor.execute("""
        SELECT temperature, humidity, wind_speed, pm25, pm10, no2, o3, source, timestamp
        FROM weather_data
        WHERE city_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
    """, (stockholm['id'],))
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
        
        # Check if we have pollutant data
        has_pollutants = latest['pm25'] is not None or latest['pm10'] is not None or latest['no2'] is not None or latest['o3'] is not None
        if has_pollutants:
            print("\n[OK] Latest record HAS pollutant data!")
        else:
            print("\n[WARNING] Latest record has NO pollutant data")
    
    # Check 24h data for PM2.5
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    CET = ZoneInfo("Europe/Stockholm")
    yesterday = datetime.now(CET) - timedelta(hours=24)
    
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM weather_data 
        WHERE city_id = ? 
        AND timestamp >= ?
        AND pm25 IS NOT NULL
    """, (stockholm['id'], yesterday.isoformat()))
    pm25_24h_count = cursor.fetchone()['count']
    print(f"\nPM2.5 records in last 24h: {pm25_24h_count}")
    
    if pm25_24h_count > 0:
        print("[OK] Sufficient data for PM2.5 (24h average) calculation")
    else:
        print("[WARNING] Not enough PM2.5 data for 24h average")
    
    print("\n" + "="*60)
    print("Test complete")
    print("="*60)

if __name__ == "__main__":
    test_stockholm()
