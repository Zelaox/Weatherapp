"""Check if OpenAQ sensor data is being saved to the database."""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from database.db_manager import DatabaseManager
import sqlite3

def check_sensors_data():
    """Check sensors and sensor_readings tables."""
    print("="*60)
    print("Sensors Data Check")
    print("="*60)
    
    db = DatabaseManager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # Check sensors table
    cursor.execute("SELECT COUNT(*) as count FROM sensors")
    sensor_count = cursor.fetchone()['count']
    print(f"\nTotal sensors: {sensor_count}")
    
    if sensor_count > 0:
        # Get sample sensors
        cursor.execute("""
            SELECT id, city_id, sensor_id, parameter, last_value, last_updated
            FROM sensors
            LIMIT 10
        """)
        sensors = cursor.fetchall()
        print(f"\nSample sensors:")
        for s in sensors:
            print(f"  Sensor ID {s['id']}: parameter={s['parameter']}, value={s['last_value']}, updated={s['last_updated']}")
    
    # Check sensor_readings
    cursor.execute("SELECT COUNT(*) as count FROM sensor_readings")
    reading_count = cursor.fetchone()['count']
    print(f"\nTotal sensor_readings: {reading_count}")
    
    if reading_count > 0:
        # Get sample readings
        cursor.execute("""
            SELECT sr.id, sr.sensor_id, sr.parameter, sr.value, sr.timestamp, s.city_id
            FROM sensor_readings sr
            JOIN sensors s ON sr.sensor_id = s.id
            ORDER BY sr.timestamp DESC
            LIMIT 10
        """)
        readings = cursor.fetchall()
        print(f"\nSample sensor_readings:")
        for r in readings:
            print(f"  Reading: sensor_id={r['sensor_id']}, parameter={r['parameter']}, value={r['value']}, timestamp={r['timestamp']}, city_id={r['city_id']}")
    
    # Check if OpenAQ data is being saved to weather_data
    print("\n" + "="*60)
    print("Checking if OpenAQ data is in weather_data table")
    print("="*60)
    
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM weather_data 
        WHERE source = 'openaq'
    """)
    openaq_count = cursor.fetchone()['count']
    print(f"Weather_data records from OpenAQ: {openaq_count}")
    
    if openaq_count > 0:
        cursor.execute("""
            SELECT city_id, pm25, pm10, no2, o3, timestamp, source
            FROM weather_data
            WHERE source = 'openaq'
            ORDER BY timestamp DESC
            LIMIT 5
        """)
        openaq_data = cursor.fetchall()
        print("\nSample OpenAQ data in weather_data:")
        for d in openaq_data:
            print(f"  City {d['city_id']}: PM2.5={d['pm25']}, PM10={d['pm10']}, NO2={d['no2']}, O3={d['o3']}, timestamp={d['timestamp']}")
    
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    if sensor_count == 0 and reading_count == 0 and openaq_count == 0:
        print("[WARNING] No OpenAQ data found in database!")
        print("OpenAQ provider is working but data is not being saved.")
    elif openaq_count == 0:
        print("[INFO] OpenAQ data is in sensors/sensor_readings but not in weather_data")
        print("This means data is collected but may not be displayed in main weather panel")
    else:
        print("[OK] OpenAQ data is being saved to weather_data table")

if __name__ == "__main__":
    check_sensors_data()
