"""Test script to verify all weather providers are working and sending data."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.logger import WeatherLogger
from utils.config_loader import ConfigLoader
from providers.openmeteo_provider import OpenMeteoProvider
from providers.openaq_provider import OpenAQProvider

# Test coordinates (Stockholm)
TEST_LAT = 59.3293
TEST_LON = 18.0686

def test_provider(provider, name, lat, lon):
    """Test a single provider."""
    print(f"\n{'='*60}")
    print(f"Testing {name}")
    print(f"{'='*60}")
    
    # Check availability
    try:
        is_available = provider.is_available()
        print(f"[OK] Provider available: {is_available}")
    except Exception as e:
        print(f"[ERROR] Error checking availability: {e}")
        return False
    
    # Test get_current_weather
    print(f"\nTesting get_current_weather({lat}, {lon})...")
    try:
        weather_data = provider.get_current_weather(lat, lon)
        if weather_data:
            print(f"[OK] Weather data received:")
            print(f"  - Temperature: {weather_data.get('temperature', 'N/A')}°C")
            print(f"  - Humidity: {weather_data.get('humidity', 'N/A')}%")
            print(f"  - Wind Speed: {weather_data.get('wind_speed', 'N/A')} m/s")
            print(f"  - AQI: {weather_data.get('aqi', 'N/A')}")
            print(f"  - Source: {weather_data.get('source', 'N/A')}")
            print(f"  - Timestamp: {weather_data.get('timestamp', 'N/A')}")
        else:
            print(f"[ERROR] No weather data returned (None)")
            return False
    except Exception as e:
        print(f"[ERROR] Error getting weather data: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test get_air_quality
    print(f"\nTesting get_air_quality({lat}, {lon})...")
    try:
        air_quality = provider.get_air_quality(lat, lon)
        if air_quality:
            print(f"[OK] Air quality data received:")
            pollutants = ['pm25', 'pm10', 'no2', 'o3', 'co', 'so2']
            for pollutant in pollutants:
                value = air_quality.get(pollutant)
                if value is not None:
                    print(f"  - {pollutant.upper()}: {value} µg/m³")
                else:
                    print(f"  - {pollutant.upper()}: N/A")
        else:
            print(f"[WARNING] No air quality data returned (None) - this may be normal for some providers")
    except Exception as e:
        print(f"[ERROR] Error getting air quality data: {e}")
        import traceback
        traceback.print_exc()
    
    return True

def main():
    """Test all providers."""
    print("="*60)
    print("Weather Provider Test Script")
    print("="*60)
    print(f"Test coordinates: {TEST_LAT}, {TEST_LON} (Stockholm)")
    
    logger = WeatherLogger()
    config = ConfigLoader()
    
    results = {}
    
    # Test Open-Meteo (no API key required)
    print("\n" + "="*60)
    print("1. Testing Open-Meteo Provider")
    print("="*60)
    try:
        openmeteo = OpenMeteoProvider(logger)
        results['openmeteo'] = test_provider(openmeteo, "Open-Meteo", TEST_LAT, TEST_LON)
    except Exception as e:
        print(f"✗ Failed to initialize Open-Meteo: {e}")
        results['openmeteo'] = False
    
    # Test OpenAQ (requires API key)
    print("\n" + "="*60)
    print("2. Testing OpenAQ Provider")
    print("="*60)
    try:
        api_key = config.get_api_key("openaq")
        if api_key:
            openaq = OpenAQProvider(api_key, logger)
            results['openaq'] = test_provider(openaq, "OpenAQ", TEST_LAT, TEST_LON)
        else:
            print("[WARNING] OpenAQ API key not found in config - skipping")
            results['openaq'] = None
    except Exception as e:
        print(f"[ERROR] Failed to initialize OpenAQ: {e}")
        results['openaq'] = False
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for name, result in results.items():
        if result is True:
            print(f"[OK] {name}: WORKING")
        elif result is False:
            print(f"[ERROR] {name}: FAILED")
        else:
            print(f"[SKIP] {name}: SKIPPED (no API key)")
    
    working_count = sum(1 for r in results.values() if r is True)
    total_count = len([r for r in results.values() if r is not None])
    
    print(f"\nWorking providers: {working_count}/{total_count}")
    
    if working_count == 0:
        print("\n[WARNING] No providers are working!")
        return 1
    elif working_count < total_count:
        print(f"\n[WARNING] Only {working_count} of {total_count} providers are working")
        return 0
    else:
        print("\n[OK] All providers are working!")
        return 0

if __name__ == "__main__":
    sys.exit(main())
