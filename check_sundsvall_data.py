"""Script to check Sundsvall data in database for constant values issue."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from database.db_manager import DatabaseManager
from zoneinfo import ZoneInfo
import pandas as pd

CET = ZoneInfo("Europe/Stockholm")

def check_sundsvall_data():
    """Check Sundsvall data for constant values."""
    db = DatabaseManager()
    
    # Find Sundsvall city
    cities = db.get_all_cities()
    sundsvall = None
    for city in cities:
        if 'sundsvall' in city['name'].lower():
            sundsvall = city
            break
    
    if not sundsvall:
        print("[ERROR] Sundsvall hittades inte i databasen")
        print(f"Tillgängliga städer: {[c['name'] for c in cities]}")
        return
    
    print(f"[OK] Hittade Sundsvall: ID={sundsvall['id']}, {sundsvall['name']}")
    print(f"   Koordinater: ({sundsvall['latitude']}, {sundsvall['longitude']})")
    print()
    
    # Get all weather data for Sundsvall
    data = db.get_weather_data_for_city(sundsvall['id'], hours=None)
    
    if not data:
        print("[ERROR] Ingen data för Sundsvall")
        return
    
    print(f"[DATA] Totalt {len(data)} datapunkter för Sundsvall")
    print()
    
    # Convert to DataFrame
    df = pd.DataFrame(data)
    
    # Check timestamps
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df = df[df['timestamp'].notna()]
        print(f"[TIMESTAMPS] {len(df)} giltiga timestamps")
        print(f"   Första: {df['timestamp'].min()}")
        print(f"   Sista: {df['timestamp'].max()}")
        print(f"   Unika timestamps: {df['timestamp'].nunique()}")
        print()
    
    # Check each pollutant
    pollutants = ['pm25', 'pm10', 'no2', 'o3']
    
    for param in pollutants:
        if param not in df.columns:
            print(f"[ERROR] {param.upper()}: Kolumn saknas")
            continue
        
        param_data = df[df[param].notna()][param]
        
        if len(param_data) == 0:
            print(f"[WARN] {param.upper()}: Inga värden (alla None)")
            continue
        
        unique_count = param_data.nunique()
        std = param_data.std()
        mean = param_data.mean()
        min_val = param_data.min()
        max_val = param_data.max()
        
        print(f"[{param.upper()}]")
        print(f"   Antal värden: {len(param_data)}")
        print(f"   Unika värden: {unique_count}")
        print(f"   Medelvärde: {mean:.4f}")
        print(f"   Min: {min_val:.4f}")
        print(f"   Max: {max_val:.4f}")
        print(f"   Standardavvikelse: {std:.4f}")
        
        if unique_count == 1:
            print(f"   [WARN] KONSTANT DATA: Alla {len(param_data)} värden är identiska ({param_data.iloc[0]:.4f})")
        elif std < 0.01:
            print(f"   [WARN] MISSTANKT KONSTANT DATA: Mycket lag variation (std={std:.4f})")
        else:
            print(f"   [OK] Normal variation")
        
        # Show first 10 values
        print(f"   Första 10 värden: {param_data.head(10).tolist()}")
        print()
    
    # Check for duplicate timestamps
    if 'timestamp' in df.columns:
        duplicate_timestamps = df[df.duplicated(subset=['timestamp'], keep=False)]
        if len(duplicate_timestamps) > 0:
            print(f"[WARN] {len(duplicate_timestamps)} rader med duplicerade timestamps")
            print("   Forsta 5 duplicerade:")
            for idx, row in duplicate_timestamps.head(5).iterrows():
                print(f"      {row['timestamp']}: pm25={row.get('pm25')}, pm10={row.get('pm10')}, no2={row.get('no2')}")
        else:
            print("[OK] Inga duplicerade timestamps")
        print()
    
    # Check sources
    if 'source' in df.columns:
        sources = df['source'].value_counts()
        print(f"[SOURCES] Datakallor:")
        for source, count in sources.items():
            print(f"   {source}: {count} datapunkter")
        print()

if __name__ == "__main__":
    check_sundsvall_data()
