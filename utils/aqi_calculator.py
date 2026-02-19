"""AQI calculation utilities based on US EPA standards."""

from typing import Optional
from database.db_manager import DatabaseManager


def calculate_aqi_from_pm25_24h(pm25_24h_avg: float) -> float:
    """
    Calculate AQI from 24h rolling average PM2.5 using official US EPA formula.
    
    Breakpoints:
    PM2.5 (µg/m³)    AQI
    0.0 – 12.0       0–50
    12.1 – 35.4      51–100
    35.5 – 55.4      101–150
    55.5 – 150.4     151–200
    150.5 – 250.4    201–300
    250.5 – 350.4    301–400
    350.5 – 500.4    401–500
    
    Args:
        pm25_24h_avg: 24-hour average PM2.5 in µg/m³
        
    Returns:
        AQI value (0-500 scale, rounded to integer)
    """
    breakpoints = [
        (0.0, 12.0, 0, 50),
        (12.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 350.4, 301, 400),
        (350.5, 500.4, 401, 500),
    ]
    
    for bp_lo, bp_hi, i_lo, i_hi in breakpoints:
        if bp_lo <= pm25_24h_avg <= bp_hi:
            aqi = ((i_hi - i_lo) / (bp_hi - bp_lo)) * (pm25_24h_avg - bp_lo) + i_lo
            return round(aqi, 0)  # Round to integer as per AQI standard
    
    # If PM2.5 > 500.4, cap at 500
    return 500


def calculate_aqi_from_pm10_24h(pm10_24h_avg: float) -> float:
    """
    Calculate AQI from 24h rolling average PM10 (US EPA formula).
    
    Args:
        pm10_24h_avg: 24-hour average PM10 in µg/m³
        
    Returns:
        AQI value (0-500 scale)
    """
    if pm10_24h_avg <= 54:
        aqi = (pm10_24h_avg / 54.0) * 50
    elif pm10_24h_avg <= 154:
        aqi = ((pm10_24h_avg - 55) / (154 - 55)) * (100 - 51) + 51
    elif pm10_24h_avg <= 254:
        aqi = ((pm10_24h_avg - 155) / (254 - 155)) * (200 - 151) + 151
    else:
        aqi = min(300, ((pm10_24h_avg - 255) / (354 - 255)) * (300 - 201) + 201)
    
    return round(aqi, 1)


def get_current_aqi(db_manager: DatabaseManager, city_id: int) -> Optional[float]:
    """
    Get current AQI for a city based on 24h rolling average.
    
    Args:
        db_manager: Database manager instance
        city_id: City ID
        
    Returns:
        AQI value (calculated from 24h avg PM2.5, or PM10 if PM2.5 unavailable)
        None if insufficient data
    """
    # Try PM2.5 first (preferred)
    pm25_avg = db_manager.get_24h_rolling_average(city_id, 'pm25')
    if pm25_avg is not None:
        return calculate_aqi_from_pm25_24h(pm25_avg)
    
    # Fallback to PM10
    pm10_avg = db_manager.get_24h_rolling_average(city_id, 'pm10')
    if pm10_avg is not None:
        return calculate_aqi_from_pm10_24h(pm10_avg)
    
    return None
