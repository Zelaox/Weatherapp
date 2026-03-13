"""Check database timestamps to verify data is being saved."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager
from datetime import datetime
from zoneinfo import ZoneInfo

CET = ZoneInfo("Europe/Stockholm")

def main():
    db = DatabaseManager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("=" * 60)
    print("DATABAS-KONTROLL: Timestamps och data")
    print("=" * 60)
    print(f"\nDatabase path: {db.db_path}")
    
    # Check latest timestamp overall
    cursor.execute("SELECT MAX(timestamp) as latest, COUNT(*) as count FROM weather_data")
    row = cursor.fetchone()
    latest_overall = row[0]
    total_count = row[1]
    
    print(f"\nTotalt antal rader i weather_data: {total_count}")
    print(f"Senaste timestamp (överallt): {latest_overall}")
    
    if latest_overall:
        try:
            if isinstance(latest_overall, str):
                latest_dt = datetime.fromisoformat(latest_overall.replace('Z', '+00:00'))
            else:
                latest_dt = latest_overall
            
            now = datetime.now(CET)
            if latest_dt.tzinfo:
                latest_dt = latest_dt.astimezone(CET)
            
            age_minutes = (now - latest_dt).total_seconds() / 60.0
            print(f"Ålder på senaste data: {age_minutes:.1f} minuter")
        except Exception as e:
            print(f"Kunde inte beräkna ålder: {e}")
    
    # Check top 10 cities with latest data
    print("\n" + "=" * 60)
    print("Top 10 städer (senaste timestamp):")
    print("=" * 60)
    cursor.execute("""
        SELECT 
            w.city_id,
            c.name,
            MAX(w.timestamp) as latest,
            COUNT(*) as count
        FROM weather_data w
        LEFT JOIN cities c ON w.city_id = c.id
        GROUP BY w.city_id, c.name
        ORDER BY latest DESC
        LIMIT 10
    """)
    
    for row in cursor.fetchall():
        city_id = row[0]
        city_name = row[1] or f"City {city_id}"
        latest = row[2]
        count = row[3]
        print(f"  {city_name} (ID {city_id}): {latest} ({count} rader)")
    
    # Check recent data (last hour)
    print("\n" + "=" * 60)
    print("Data från senaste timmen:")
    print("=" * 60)
    cursor.execute("""
        SELECT 
            w.city_id,
            c.name,
            w.timestamp,
            w.temperature,
            w.humidity,
            w.wind_speed
        FROM weather_data w
        LEFT JOIN cities c ON w.city_id = c.id
        WHERE w.timestamp >= datetime('now', '-1 hour')
        ORDER BY w.timestamp DESC
        LIMIT 20
    """)
    
    rows = cursor.fetchall()
    if rows:
        print(f"Hittade {len(rows)} rader från senaste timmen:")
        for row in rows:
            city_id = row[0]
            city_name = row[1] or f"City {city_id}"
            timestamp = row[2]
            temp = row[3]
            hum = row[4]
            wind = row[5]
            print(f"  {city_name}: {timestamp} - Temp: {temp}°C, Hum: {hum}%, Wind: {wind} m/s")
    else:
        print("INGEN DATA från senaste timmen!")
    
    # Check what get_latest_weather_for_all_cities returns
    print("\n" + "=" * 60)
    print("Vad get_latest_weather_for_all_cities() returnerar:")
    print("=" * 60)
    latest_weather = db.get_latest_weather_for_all_cities()
    if latest_weather:
        timestamps = [w.get('timestamp') for w in latest_weather if w.get('timestamp')]
        if timestamps:
            max_ts = max(timestamps)
            print(f"Max timestamp från get_latest_weather_for_all_cities(): {max_ts}")
            try:
                if isinstance(max_ts, str):
                    max_dt = datetime.fromisoformat(max_ts.replace('Z', '+00:00'))
                else:
                    max_dt = max_ts
                
                if max_dt.tzinfo:
                    max_dt = max_dt.astimezone(CET)
                
                now = datetime.now(CET)
                age_minutes = (now - max_dt).total_seconds() / 60.0
                print(f"Ålder: {age_minutes:.1f} minuter")
            except Exception as e:
                print(f"Kunde inte beräkna ålder: {e}")
        else:
            print("Inga timestamps i resultatet!")
    else:
        print("get_latest_weather_for_all_cities() returnerade inget!")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
