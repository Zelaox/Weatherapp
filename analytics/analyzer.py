"""Main analytics engine for weather data."""

from datetime import datetime, date
from typing import Dict, Optional, List
from database.db_manager import DatabaseManager
from analytics.statistics import StatisticsCalculator
from analytics.warnings import WarningDetector
import logging

# Get module logger
logger = logging.getLogger("WeatherApp.analytics")


class WeatherAnalyzer:
    """Main analytics engine for weather data analysis."""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize analyzer.
        
        Args:
            db_manager: Database manager instance
        """
        logger.info("Initialiserar analysmotor...")
        self.db = db_manager
        self.stats = StatisticsCalculator(db_manager)
        self.warning_detector = WarningDetector(db_manager)
        logger.info("Analysmotor initialiserad")
    
    def get_rankings(self, timeframe: str = '24h') -> Dict:
        """
        Get all rankings for a timeframe.
        
        Args:
            timeframe: '1h', '24h', 'today', 'week'
            
        Returns:
            Dictionary with all rankings
        """
        logger.debug(f"Hämtar rankings för tidsperiod: {timeframe}")
        rankings = {
            'coldest': self.stats.find_coldest_city(timeframe),
            'warmest': self.stats.find_warmest_city(timeframe),
            'best_air': self.stats.find_best_air_quality(timeframe),
            'worst_air': self.stats.find_worst_air_quality(timeframe)
        }
        logger.debug(f"Rankings hämtade: {len([r for r in rankings.values() if r])} resultat")
        return rankings
    
    def update_daily_stats(self, target_date: Optional[date] = None):
        """
        Update daily statistics for a date.
        
        Args:
            target_date: Date to update (defaults to today)
        """
        if target_date is None:
            target_date = date.today()
        
        date_str = target_date.isoformat()
        
        # Get rankings for today
        coldest = self.stats.find_coldest_city('today')
        warmest = self.stats.find_warmest_city('today')
        best_air = self.stats.find_best_air_quality('today')
        worst_air = self.stats.find_worst_air_quality('today')
        
        self.db.update_daily_stats(
            date_str,
            coldest['city_id'] if coldest else None,
            warmest['city_id'] if warmest else None,
            best_air['city_id'] if best_air else None,
            worst_air['city_id'] if worst_air else None
        )
    
    def get_city_trend(self, city_id: int, hours: int = 24) -> List[Dict]:
        """
        Get trend data for a city.
        
        Args:
            city_id: City ID
            hours: Number of hours to look back
            
        Returns:
            List of data points
        """
        return self.stats.get_trend_24h(city_id)
    
    def get_city_statistics(self, city_id: int, timeframe: str = '24h') -> Dict:
        """
        Get comprehensive statistics for a city.
        
        Args:
            city_id: City ID
            timeframe: Timeframe for analysis
            
        Returns:
            Dictionary with statistics
        """
        hours = self.stats._timeframe_to_hours(timeframe)
        history = self.db.get_weather_history(city_id, hours=hours)
        
        if not history:
            return {}
        
        temperatures = [h['temperature'] for h in history]
        humidities = [h['humidity'] for h in history]
        wind_speeds = [h['wind_speed'] for h in history]
        aqis = [h['aqi'] for h in history if h['aqi'] is not None]
        
        return {
            'avg_temperature': sum(temperatures) / len(temperatures) if temperatures else None,
            'min_temperature': min(temperatures) if temperatures else None,
            'max_temperature': max(temperatures) if temperatures else None,
            'avg_humidity': sum(humidities) / len(humidities) if humidities else None,
            'avg_wind_speed': sum(wind_speeds) / len(wind_speeds) if wind_speeds else None,
            'avg_aqi': sum(aqis) / len(aqis) if aqis else None,
            'min_aqi': min(aqis) if aqis else None,
            'max_aqi': max(aqis) if aqis else None,
            'data_points': len(history)
        }
    
    def get_all_cities_averages(self, timeframe: str = 'latest') -> Dict:
        """
        Get average values across all cities.
        
        Args:
            timeframe: 'latest' (current values) or '24h' (24h average)
            
        Returns:
            Dictionary with average values and metadata
        """
        # Get ALL cities from database (not just those with weather data)
        all_cities = self.db.get_all_cities()
        total_city_count = len(all_cities)
        
        # Get total data points count (with error handling)
        try:
            total_data_points = self.db.get_total_data_points_count()
        except Exception as e:
            logger.error(f"Fel vid hämtning av totala datapunkter: {e}")
            total_data_points = None
        
        # Get unique cities in data count (optional, with error handling)
        try:
            unique_cities_in_data = self.db.get_unique_cities_in_data_count()
        except Exception as e:
            logger.error(f"Fel vid hämtning av unika städer i data: {e}")
            unique_cities_in_data = None
        
        if timeframe == 'latest':
            # Get latest weather for all cities
            all_weather = self.db.get_all_latest_weather()
            
            if not all_weather:
                return {
                    'avg_temperature': None,
                    'avg_humidity': None,
                    'avg_wind_speed': None,
                    'avg_aqi': None,
                    'city_count': total_city_count,  # Total cities in database
                    'cities_with_data': 0,
                    'data_points': total_data_points,  # Total rows in weather_data table
                    'unique_cities_in_data': unique_cities_in_data,
                    'last_update': None
                }
            
            # Extract values, filtering out None
            temperatures = [w['temperature'] for w in all_weather if w.get('temperature') is not None]
            humidities = [w['humidity'] for w in all_weather if w.get('humidity') is not None]
            wind_speeds = [w['wind_speed'] for w in all_weather if w.get('wind_speed') is not None]
            pm25_values = [w['pm25'] for w in all_weather if w.get('pm25') is not None]
            
            # Log data availability for debugging
            logger.info(f"Found {len(pm25_values)} cities with PM2.5 data out of {len(all_weather)} total weather records")
            if pm25_values:
                logger.debug(f"PM2.5 sample values: {pm25_values[:5]}")
            
            # Get latest timestamp
            timestamps = [w.get('timestamp') for w in all_weather if w.get('timestamp')]
            last_update = max(timestamps) if timestamps else None
            
            # For "latest" timeframe: show average of current PM2.5 values
            # But AQI should be calculated from 24h rolling average per city, then averaged
            # Get 24h rolling average for each city that has current PM2.5 data
            from utils.aqi_calculator import calculate_aqi_from_pm25_24h
            pm25_24h_averages = []
            for weather in all_weather:
                if weather.get('pm25') is not None:
                    city_id = weather.get('city_id')
                    if city_id:
                        pm25_24h = self.db.get_24h_rolling_average(city_id, 'pm25')
                        if pm25_24h is not None:
                            pm25_24h_averages.append(pm25_24h)
            
            # Calculate average PM2.5 (current values for display)
            avg_pm25 = sum(pm25_values) / len(pm25_values) if pm25_values else None
            
            # Calculate AQI from average of 24h rolling averages (if available)
            # Otherwise calculate from current average (less accurate but better than nothing)
            if pm25_24h_averages:
                avg_pm25_24h = sum(pm25_24h_averages) / len(pm25_24h_averages)
                avg_aqi = calculate_aqi_from_pm25_24h(avg_pm25_24h)
            elif avg_pm25 is not None:
                # Fallback: use current average (not ideal but shows something)
                avg_aqi = calculate_aqi_from_pm25_24h(avg_pm25)
            else:
                avg_aqi = None
            
            return {
                'avg_temperature': sum(temperatures) / len(temperatures) if temperatures else None,
                'avg_humidity': sum(humidities) / len(humidities) if humidities else None,
                'avg_wind_speed': sum(wind_speeds) / len(wind_speeds) if wind_speeds else None,
                'avg_pm25': avg_pm25,
                'avg_aqi': avg_aqi,
                'city_count': total_city_count,  # Total cities in database
                'cities_with_data': len(all_weather),  # Cities that have weather data
                'cities_with_pm25': len(pm25_values),  # Cities with PM2.5 data
                'data_points': total_data_points,  # Total rows in weather_data table
                'unique_cities_in_data': unique_cities_in_data,
                'last_update': last_update
            }
        else:
            # 24h average: get history for all cities and calculate
            if not all_cities:
                return {
                    'avg_temperature': None,
                    'avg_humidity': None,
                    'avg_wind_speed': None,
                    'avg_aqi': None,
                    'city_count': 0,
                    'cities_with_data': 0,
                    'data_points': total_data_points,  # Total rows in weather_data table
                    'unique_cities_in_data': unique_cities_in_data,
                    'last_update': None
                }
            
            # Get 24h rolling averages for each city
            pm25_averages = []
            temperatures = []
            humidities = []
            wind_speeds = []
            timestamps = []
            cities_with_data = 0
            
            for city in all_cities:
                # Get 24h rolling average PM2.5
                pm25_avg = self.db.get_24h_rolling_average(city['id'], 'pm25')
                if pm25_avg is not None:
                    pm25_averages.append(pm25_avg)
                    cities_with_data += 1
                
                # Get latest values for other metrics
                latest = self.db.get_latest_weather(city['id'])
                if latest:
                    if latest.get('temperature') is not None:
                        temperatures.append(latest['temperature'])
                    if latest.get('humidity') is not None:
                        humidities.append(latest['humidity'])
                    if latest.get('wind_speed') is not None:
                        wind_speeds.append(latest['wind_speed'])
                    if latest.get('timestamp'):
                        timestamps.append(latest['timestamp'])
            
            # Calculate average PM2.5 and AQI from it
            from utils.aqi_calculator import calculate_aqi_from_pm25_24h
            avg_pm25 = sum(pm25_averages) / len(pm25_averages) if pm25_averages else None
            avg_aqi = calculate_aqi_from_pm25_24h(avg_pm25) if avg_pm25 is not None else None
            
            last_update = max(timestamps) if timestamps else None
            
            return {
                'avg_temperature': sum(temperatures) / len(temperatures) if temperatures else None,
                'avg_humidity': sum(humidities) / len(humidities) if humidities else None,
                'avg_wind_speed': sum(wind_speeds) / len(wind_speeds) if wind_speeds else None,
                'avg_pm25': avg_pm25,
                'avg_aqi': avg_aqi,
                'city_count': total_city_count,  # Total cities in database
                'cities_with_data': cities_with_data,  # Cities that have PM2.5 data
                'data_points': total_data_points,  # Total rows in weather_data table
                'unique_cities_in_data': unique_cities_in_data,
                'last_update': last_update
            }
    
    def get_national_warning_status(self) -> Dict:
        """
        Get national warning status based on average PM2.5.
        
        Returns:
            Dictionary with warning information (level, name, color, pm25, aqi)
        """
        # Get 24h average PM2.5 across all cities
        averages = self.get_all_cities_averages('24h')
        avg_pm25 = averages.get('avg_pm25')
        
        # Get warning from detector
        return self.warning_detector.get_national_warning(avg_pm25)
    
    def get_regional_warnings(self) -> List[Dict]:
        """
        Get regional warnings for cities over thresholds.
        
        Returns:
            List of warnings with city names, PM2.5 values, and severity
        """
        return self.warning_detector.get_regional_warnings()
    
    def get_max_pm25_cities(self, limit: int = 10) -> List[Dict]:
        """
        Get cities with highest PM2.5 values.
        
        Args:
            limit: Maximum number of cities to return
            
        Returns:
            List of cities sorted by PM2.5 (highest first)
        """
        cities = self.db.get_all_cities()
        city_data = []
        
        for city in cities:
            pm25_avg = self.db.get_24h_rolling_average(city['id'], 'pm25')
            if pm25_avg is not None:
                level = self.warning_detector.get_warning_level(pm25_avg)
                from utils.aqi_calculator import calculate_aqi_from_pm25_24h
                aqi = calculate_aqi_from_pm25_24h(pm25_avg)
                city_data.append({
                    'city_id': city['id'],
                    'city_name': city['name'],
                    'pm25': pm25_avg,
                    'aqi': aqi,
                    'level': level,
                    'level_name': self.warning_detector.LEVEL_NAMES[level],
                    'color': self.warning_detector.LEVEL_COLORS[level]
                })
        
        # Sort by PM2.5 descending (highest first)
        city_data.sort(key=lambda x: x['pm25'], reverse=True)
        
        # Return top N cities
        return city_data[:limit]
