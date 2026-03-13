"""Statistics calculations for weather data."""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from database.db_manager import DatabaseManager


class StatisticsCalculator:
    """Calculate statistics from weather data."""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize statistics calculator.
        
        Args:
            db_manager: Database manager instance
        """
        self.db = db_manager
    
    def find_coldest_city(self, timeframe: str = '1h') -> Optional[Dict]:
        """
        Find coldest city in given timeframe.
        
        Args:
            timeframe: '1h', '24h', 'today', 'week'
            
        Returns:
            Dictionary with city info and temperature, or None
        """
        # Build WHERE clause dynamically based on timeframe (no hardcoding)
        where_clause, params = self._build_timeframe_filter(timeframe)
        
        # Use public method instead of private _get_connection()
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""SELECT c.id, c.name, c.latitude, c.longitude, 
                          MIN(wd.temperature) as min_temp
                   FROM cities c
                   INNER JOIN weather_data wd ON c.id = wd.city_id
                   WHERE {where_clause}
                   GROUP BY c.id, c.name, c.latitude, c.longitude
                   ORDER BY min_temp ASC
                   LIMIT 1""",
                params
            )
            row = cursor.fetchone()
            if row:
                return {
                    'city_id': row['id'],
                    'city_name': row['name'],
                    'temperature': row['min_temp'],
                    'latitude': row['latitude'],
                    'longitude': row['longitude']
                }
            return None
        except Exception:
            return None
    
    def find_warmest_city(self, timeframe: str = '1h') -> Optional[Dict]:
        """
        Find warmest city in given timeframe.
        
        Args:
            timeframe: '1h', '24h', 'today', 'week'
            
        Returns:
            Dictionary with city info and temperature, or None
        """
        # Build WHERE clause dynamically based on timeframe (no hardcoding)
        where_clause, params = self._build_timeframe_filter(timeframe)
        
        # Use public method instead of private _get_connection()
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""SELECT c.id, c.name, c.latitude, c.longitude, 
                          MAX(wd.temperature) as max_temp
                   FROM cities c
                   INNER JOIN weather_data wd ON c.id = wd.city_id
                   WHERE {where_clause}
                   GROUP BY c.id, c.name, c.latitude, c.longitude
                   ORDER BY max_temp DESC
                   LIMIT 1""",
                params
            )
            row = cursor.fetchone()
            if row:
                return {
                    'city_id': row['id'],
                    'city_name': row['name'],
                    'temperature': row['max_temp'],
                    'latitude': row['latitude'],
                    'longitude': row['longitude']
                }
            return None
        except Exception:
            return None
    
    def find_best_air_quality(self, timeframe: str = '24h') -> Optional[Dict]:
        """
        Find city with best air quality (lowest 24h rolling average PM2.5).
        
        Args:
            timeframe: '1h', '24h', 'today', 'week'
            
        Returns:
            Dictionary with city info and PM2.5, or None
        """
        # Use 24h rolling average PM2.5 for air quality ranking
        cities = self.db.get_all_cities()
        if not cities:
            return None
        
        best_city = None
        best_pm25 = None
        
        for city in cities:
            pm25_avg = self.db.get_24h_rolling_average(city['id'], 'pm25')
            if pm25_avg is not None:
                if best_pm25 is None or pm25_avg < best_pm25:
                    best_pm25 = pm25_avg
                    best_city = city
        
        if best_city and best_pm25 is not None:
            return {
                'city_id': best_city['id'],
                'city_name': best_city['name'],
                'pm25': best_pm25,
                'latitude': best_city['latitude'],
                'longitude': best_city['longitude']
            }
        return None
    
    def find_worst_air_quality(self, timeframe: str = '24h') -> Optional[Dict]:
        """
        Find city with worst air quality (highest 24h rolling average PM2.5).
        
        Args:
            timeframe: '1h', '24h', 'today', 'week'
            
        Returns:
            Dictionary with city info and PM2.5, or None
        """
        # Use 24h rolling average PM2.5 for air quality ranking
        cities = self.db.get_all_cities()
        if not cities:
            return None
        
        worst_city = None
        worst_pm25 = None
        
        for city in cities:
            pm25_avg = self.db.get_24h_rolling_average(city['id'], 'pm25')
            if pm25_avg is not None:
                if worst_pm25 is None or pm25_avg > worst_pm25:
                    worst_pm25 = pm25_avg
                    worst_city = city
        
        if worst_city and worst_pm25 is not None:
            return {
                'city_id': worst_city['id'],
                'city_name': worst_city['name'],
                'pm25': worst_pm25,
                'latitude': worst_city['latitude'],
                'longitude': worst_city['longitude']
            }
        return None
    
    def get_trend_24h(self, city_id: int) -> List[Dict]:
        """
        Get temperature trend for last 24 hours.
        
        Args:
            city_id: City ID
            
        Returns:
            List of temperature data points
        """
        history = self.db.get_weather_history(city_id, hours=24)
        return [
            {
                'timestamp': row['timestamp'],
                'temperature': row['temperature'],
                'humidity': row['humidity'],
                'wind_speed': row['wind_speed'],
                'aqi': row['aqi']
            }
            for row in history
        ]
    
    def _timeframe_to_hours(self, timeframe: str) -> int:
        """Convert timeframe string to hours (for backward compatibility)."""
        timeframe_map = {
            '1h': 1,
            '24h': 24,
            'today': 24,  # Deprecated: use _build_timeframe_filter instead
            'week': 168
        }
        return timeframe_map.get(timeframe.lower(), 24)
    
    def _build_timeframe_filter(self, timeframe: str) -> tuple[str, tuple]:
        """
        Build SQL WHERE clause dynamically based on timeframe.
        
        Args:
            timeframe: '1h', '24h', 'today', 'week'
            
        Returns:
            Tuple of (WHERE clause string, parameters tuple)
            No hardcoding - all time calculations are dynamic
        """
        timeframe_lower = timeframe.lower()
        
        if timeframe_lower == '1h':
            # Last 1 hour
            return ("wd.timestamp > datetime('now', '-1 hours')", ())
        
        elif timeframe_lower == '24h':
            # Last 24 hours (rolling)
            return ("wd.timestamp > datetime('now', '-24 hours')", ())
        
        elif timeframe_lower == 'today':
            # Today from midnight (CET timezone)
            # Use DATE() function to compare dates dynamically
            return ("DATE(wd.timestamp) = DATE('now', 'localtime')", ())
        
        elif timeframe_lower == 'week':
            # Last 7 days (168 hours)
            return ("wd.timestamp > datetime('now', '-168 hours')", ())
        
        else:
            # Default: last 24 hours if unknown timeframe
            return ("wd.timestamp > datetime('now', '-24 hours')", ())