"""Detailed check of Sundsvall data to find why values are constant."""

import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from database.db_manager import DatabaseManager
import sqlite3

CET = ZoneInfo("Europe/Stockholm")

def check_detailed():
    """Check detailed data for Sundsvall."""
    db = DatabaseManager()
    
    # Get connection directly to run custom queries
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Find Sundsvall
    cursor.execute("SELECT id, name FROM cities WHERE name LIKE '%sundsvall%'")
    city = cursor.fetchone()
    if not city:
        print("[ERROR] Sundsvall not found")
        return
    
    city_id = city['id']
    city_name = city['name']
    print(f"[OK] Found {city_name} (ID: {city_id})")
    print()
    
    # Check pollutant data with timestamps
    print("[CHECKING POLLUTANT DATA]")
    print()
    
    # Get all rows with PM2.5 values
    cursor.execute("""
        SELECT id, timestamp, pm25, pm10, no2, o3, source
        FROM weather_data
        WHERE city_id = ? AND pm25 IS NOT NULL
        ORDER BY timestamp ASC
        LIMIT 20
    """, (city_id,))
    
    rows = cursor.fetchall()
    print(f"First 20 rows with PM2.5 values:")
    print(f"{'ID':<5} {'Timestamp':<25} {'PM2.5':<10} {'PM10':<10} {'NO2':<10} {'Source':<15}")
    print("-" * 90)
    
    for row in rows:
        print(f"{row['id']:<5} {str(row['timestamp']):<25} {row['pm25']:<10.4f} {row['pm10']:<10.4f} {row['no2']:<10.4f} {row['source']:<15}")
    
    print()
    
    # Check if same values are saved with different timestamps
    cursor.execute("""
        SELECT pm25, COUNT(*) as count, MIN(timestamp) as first_ts, MAX(timestamp) as last_ts
        FROM weather_data
        WHERE city_id = ? AND pm25 IS NOT NULL
        GROUP BY pm25
        ORDER BY count DESC
    """, (city_id,))
    
    pm25_groups = cursor.fetchall()
    print(f"PM2.5 value groups:")
    for group in pm25_groups:
        print(f"  Value {group['pm25']:.4f}: {group['count']} rows")
        print(f"    First: {group['first_ts']}, Last: {group['last_ts']}")
    print()
    
    # Check for duplicate measurement timestamps (if stored)
    # Note: measurement_timestamp might not be in the table, check schema
    cursor.execute("PRAGMA table_info(weather_data)")
    columns = [row['name'] for row in cursor.fetchall()]
    print(f"Columns in weather_data: {columns}")
    print()
    
    # Check source distribution
    cursor.execute("""
        SELECT source, COUNT(*) as count,
               COUNT(DISTINCT pm25) as unique_pm25,
               COUNT(DISTINCT pm10) as unique_pm10,
               COUNT(DISTINCT no2) as unique_no2
        FROM weather_data
        WHERE city_id = ? AND pm25 IS NOT NULL
        GROUP BY source
    """, (city_id,))
    
    sources = cursor.fetchall()
    print(f"Source distribution:")
    for src in sources:
        print(f"  {src['source']}: {src['count']} rows")
        print(f"    Unique PM2.5: {src['unique_pm25']}, PM10: {src['unique_pm10']}, NO2: {src['unique_no2']}")
    print()
    
    # Check if values change over time
    cursor.execute("""
        SELECT timestamp, pm25, pm10, no2, source
        FROM weather_data
        WHERE city_id = ? AND pm25 IS NOT NULL
        ORDER BY timestamp ASC
    """, (city_id,))
    
    all_rows = cursor.fetchall()
    print(f"Checking value changes over time ({len(all_rows)} rows):")
    
    prev_pm25 = None
    prev_pm10 = None
    prev_no2 = None
    changes = 0
    
    for i, row in enumerate(all_rows[:50]):  # Check first 50
        if prev_pm25 is not None:
            if row['pm25'] != prev_pm25 or row['pm10'] != prev_pm10 or row['no2'] != prev_no2:
                changes += 1
                print(f"  Change at row {i}: PM2.5 {prev_pm25:.4f} -> {row['pm25']:.4f}, "
                      f"PM10 {prev_pm10:.4f} -> {row['pm10']:.4f}, "
                      f"NO2 {prev_no2:.4f} -> {row['no2']:.4f}")
                print(f"    Timestamp: {row['timestamp']}, Source: {row['source']}")
        
        prev_pm25 = row['pm25']
        prev_pm10 = row['pm10']
        prev_no2 = row['no2']
    
    if changes == 0:
        print(f"  [WARN] No value changes detected in first 50 rows!")
    else:
        print(f"  [OK] Found {changes} value changes in first 50 rows")
    print()

if __name__ == "__main__":
    check_detailed()
