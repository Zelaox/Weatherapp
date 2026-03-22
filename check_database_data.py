"""Check if there's enough data in the database to display what's shown in the GUI."""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from database.db_manager import DatabaseManager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import sqlite3

CET = ZoneInfo("Europe/Stockholm")

def check_database_data():
    """Check database for available data."""
    print("="*60)
    print("Database Data Check")
    print("="*60)
    
    db = DatabaseManager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # Check cities
    cursor.execute("SELECT COUNT(*) as count FROM cities")
    city_count = cursor.fetchone()['count']
    print(f"\nCities in database: {city_count}")
    
    if city_count == 0:
        print("[WARNING] No cities in database!")
        return
    
    # Get first city as example
    cursor.execute("SELECT id, name, latitude, longitude FROM cities LIMIT 1")
    city = cursor.fetchone()
    if city:
        city_id = city['id']
        city_name = city['name']
        print(f"\nChecking data for: {city_name} (ID: {city_id})")
        
        # Check weather_data
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM weather_data 
            WHERE city_id = ?
        """, (city_id,))
        weather_count = cursor.fetchone()['count']
        print(f"\nTotal weather_data records: {weather_count}")
        
        if weather_count == 0:
            print("[WARNING] No weather data in database!")
            return
        
        # Check recent data (last 24 hours)
        now = datetime.now(CET)
        yesterday = now - timedelta(hours=24)
        
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM weather_data 
            WHERE city_id = ? 
            AND timestamp >= ?
        """, (city_id, yesterday.isoformat()))
        recent_count = cursor.fetchone()['count']
        print(f"Records in last 24 hours: {recent_count}")
        
        # Check what parameters have data
        print("\nParameters with data in last 24 hours:")
        parameters = ['temperature', 'humidity', 'wind_speed', 'pm25', 'pm10', 'no2', 'o3']
        
        for param in parameters:
            cursor.execute(f"""
                SELECT COUNT(*) as count 
                FROM weather_data 
                WHERE city_id = ? 
                AND timestamp >= ?
                AND {param} IS NOT NULL
            """, (city_id, yesterday.isoformat()))
            count = cursor.fetchone()['count']
            if count > 0:
                # Get sample value
                cursor.execute(f"""
                    SELECT {param} 
                    FROM weather_data 
                    WHERE city_id = ? 
                    AND timestamp >= ?
                    AND {param} IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (city_id, yesterday.isoformat()))
                sample = cursor.fetchone()
                value = sample[0] if sample else None
                print(f"  [OK] {param}: {count} records (latest: {value})")
            else:
                print(f"  [MISSING] {param}: No data")
        
        # Check for 24h rolling average data (PM2.5)
        print("\n24h rolling average check:")
        try:
            pm25_24h = db.get_parameter_for_city_or_nearest(city_id, 'pm25', hours=24)[0]
            if pm25_24h is not None:
                print(f"  [OK] PM2.5 (24h average): {pm25_24h:.2f} µg/m³")
            else:
                print(f"  [MISSING] PM2.5 (24h average): No data")
        except Exception as e:
            print(f"  [ERROR] PM2.5 (24h average): {e}")
        
        # Check latest weather data
        print("\nLatest weather data:")
        cursor.execute("""
            SELECT temperature, humidity, wind_speed, pm25, pm10, no2, o3, timestamp, source
            FROM weather_data
            WHERE city_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (city_id,))
        latest = cursor.fetchone()
        if latest:
            print(f"  Timestamp: {latest['timestamp']}")
            print(f"  Source: {latest['source']}")
            print(f"  Temperature: {latest['temperature']}°C")
            print(f"  Humidity: {latest['humidity']}%")
            print(f"  Wind Speed: {latest['wind_speed']} m/s")
            print(f"  PM2.5: {latest['pm25'] if latest['pm25'] is not None else 'N/A'}")
            print(f"  PM10: {latest['pm10'] if latest['pm10'] is not None else 'N/A'}")
            print(f"  NO2: {latest['no2'] if latest['no2'] is not None else 'N/A'}")
            print(f"  O3: {latest['o3'] if latest['o3'] is not None else 'N/A'}")
        
        # Check sensors table
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM sensors 
            WHERE city_id = ?
        """, (city_id,))
        sensor_count = cursor.fetchone()['count']
        print(f"\nSensors for this city: {sensor_count}")
        
        # Check sensor_readings
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM sensor_readings sr
            JOIN sensors s ON sr.sensor_id = s.id
            WHERE s.city_id = ?
        """, (city_id,))
        reading_count = cursor.fetchone()['count']
        print(f"Sensor readings: {reading_count}")
        
        # Check if we have enough data for inversion risk calculation
        print("\nInversion risk calculation check:")
        # Need at least some historical data
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM weather_data 
            WHERE city_id = ? 
            AND pm25 IS NOT NULL
            AND wind_speed IS NOT NULL
            AND humidity IS NOT NULL
        """, (city_id,))
        inversion_data_count = cursor.fetchone()['count']
        if inversion_data_count >= 10:
            print(f"  [OK] Sufficient data for inversion risk: {inversion_data_count} records")
        else:
            print(f"  [WARNING] Limited data for inversion risk: {inversion_data_count} records (need at least 10)")
    
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    print("Check the output above to see if there's enough data to display")
    print("in the GUI. Missing parameters will show as 'N/A' or 'Ingen data'.")

if __name__ == "__main__":
    check_database_data()
