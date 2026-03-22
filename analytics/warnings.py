"""Warning detection for dangerous PM2.5 levels."""

from typing import List, Dict, Optional
from database.db_manager import DatabaseManager
from utils.aqi_calculator import calculate_aqi_from_pm25_24h


# Canonical level order with AQI display ranges.
# Defined once here; consumed only by get_threshold_metadata().
# Never imported by external modules — they call the public staticmethod instead.
_LEVEL_ORDER: List[tuple] = [
    ("good",                "0–50"),
    ("moderate",            "51–100"),
    ("unhealthy_sensitive", "101–150"),
    ("unhealthy",           "151–200"),
    ("very_unhealthy",      "201–300"),
    ("hazardous",           "301–500"),
]


class WarningDetector:
    """Detect dangerous PM2.5 levels and generate warnings."""
    
    # WHO/EPA thresholds (24h average PM2.5 in µg/m³)
    THRESHOLDS = {
        'good': 12.0,                    # AQI 0-50
        'moderate': 35.4,                 # AQI 51-100
        'unhealthy_sensitive': 55.4,     # AQI 101-150
        'unhealthy': 150.4,              # AQI 151-200
        'very_unhealthy': 250.4,         # AQI 201-300
        'hazardous': 500.4               # AQI 301-500
    }
    
    # Warning level names in Swedish
    LEVEL_NAMES = {
        'good': 'Bra',
        'moderate': 'Acceptabelt',
        'unhealthy_sensitive': 'För känsliga personer',
        'unhealthy': 'Ohälsosamt',
        'very_unhealthy': 'Mycket ohälsosamt',
        'hazardous': 'Farligt'
    }
    
    # Color codes for warning levels
    LEVEL_COLORS = {
        'good': '#00e400',              # Green
        'moderate': '#ffff00',           # Yellow
        'unhealthy_sensitive': '#ff7e00',  # Orange
        'unhealthy': '#ff0000',         # Red
        'very_unhealthy': '#8f3f97',    # Purple
        'hazardous': '#7e0023'           # Maroon
    }
    
    @staticmethod
    def get_threshold_metadata() -> List[Dict]:
        """
        Return threshold metadata for all AQI levels, ordered by ascending PM2.5.

        No instance required. No database access. Pure class-level data.
        This is the single stable public API for any consumer that needs
        threshold/color/label data without constructing a WarningDetector instance.

        Returns:
            List of dicts, one per level, in ascending PM2.5 order:
            [
                {
                    "level_key":  str,    # internal key, e.g. "good"
                    "threshold":  float,  # upper PM2.5 boundary (µg/m³)
                    "level_name": str,    # Swedish label, e.g. "Bra"
                    "color":      str,    # hex color, e.g. "#00e400"
                    "aqi_range":  str,    # display string, e.g. "0–50"
                },
                ...
            ]
        """
        return [
            {
                "level_key":  key,
                "threshold":  WarningDetector.THRESHOLDS[key],
                "level_name": WarningDetector.LEVEL_NAMES[key],
                "color":      WarningDetector.LEVEL_COLORS[key],
                "aqi_range":  aqi_range,
            }
            for key, aqi_range in _LEVEL_ORDER
        ]

    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize warning detector.
        
        Args:
            db_manager: Database manager instance
        """
        self.db = db_manager
    
    def get_warning_level(self, pm25: float) -> str:
        """
        Get warning level for a PM2.5 value.
        
        Args:
            pm25: PM2.5 value in µg/m³
            
        Returns:
            Warning level key ('good', 'moderate', etc.)
        """
        if pm25 <= self.THRESHOLDS['good']:
            return 'good'
        elif pm25 <= self.THRESHOLDS['moderate']:
            return 'moderate'
        elif pm25 <= self.THRESHOLDS['unhealthy_sensitive']:
            return 'unhealthy_sensitive'
        elif pm25 <= self.THRESHOLDS['unhealthy']:
            return 'unhealthy'
        elif pm25 <= self.THRESHOLDS['very_unhealthy']:
            return 'very_unhealthy'
        else:
            return 'hazardous'
    
    def get_national_warning(self, avg_pm25: Optional[float]) -> Dict:
        """
        Get national-level warning based on average PM2.5.
        
        Args:
            avg_pm25: Average PM2.5 across all cities (24h rolling average)
            
        Returns:
            Dictionary with warning information
        """
        if avg_pm25 is None:
            return {
                'level': 'unknown',
                'name': 'Ingen data',
                'color': '#cccccc',
                'message': 'Ingen PM2.5-data tillgänglig för nationell varning',
                'pm25': None,
                'aqi': None
            }
        
        level = self.get_warning_level(avg_pm25)
        aqi = calculate_aqi_from_pm25_24h(avg_pm25)
        
        return {
            'level': level,
            'name': self.LEVEL_NAMES[level],
            'color': self.LEVEL_COLORS[level],
            'message': f'Nationellt snitt PM2.5: {avg_pm25:.1f} µg/m³ (AQI: {aqi:.0f})',
            'pm25': avg_pm25,
            'aqi': aqi
        }
    
    def get_regional_warnings(self) -> List[Dict]:
        """
        Get regional warnings for cities over thresholds.
        
        Returns:
            List of warnings with city names, PM2.5 values, and severity
        """
        warnings = []
        cities = self.db.get_all_cities()
        
        for city in cities:
            pm25_avg = self.db.get_parameter_for_city_or_nearest(city['id'], 'pm25', hours=24)[0]
            if pm25_avg is not None:
                level = self.get_warning_level(pm25_avg)
                
                # Only include cities with unhealthy or worse
                if level in ['unhealthy_sensitive', 'unhealthy', 'very_unhealthy', 'hazardous']:
                    aqi = calculate_aqi_from_pm25_24h(pm25_avg)
                    warnings.append({
                        'city_id': city['id'],
                        'city_name': city['name'],
                        'pm25': pm25_avg,
                        'aqi': aqi,
                        'level': level,
                        'level_name': self.LEVEL_NAMES[level],
                        'color': self.LEVEL_COLORS[level]
                    })
        
        # Sort by PM2.5 descending (worst first)
        warnings.sort(key=lambda x: x['pm25'], reverse=True)
        return warnings
    
    def get_cities_over_threshold(self, threshold: float) -> List[Dict]:
        """
        Get all cities with PM2.5 above a specific threshold.
        
        Args:
            threshold: PM2.5 threshold in µg/m³
            
        Returns:
            List of cities with PM2.5 above threshold
        """
        cities_over = []
        cities = self.db.get_all_cities()
        
        for city in cities:
            pm25_avg = self.db.get_parameter_for_city_or_nearest(city['id'], 'pm25', hours=24)[0]
            if pm25_avg is not None and pm25_avg > threshold:
                aqi = calculate_aqi_from_pm25_24h(pm25_avg)
                cities_over.append({
                    'city_id': city['id'],
                    'city_name': city['name'],
                    'pm25': pm25_avg,
                    'aqi': aqi,
                    'level': self.get_warning_level(pm25_avg),
                    'level_name': self.LEVEL_NAMES[self.get_warning_level(pm25_avg)],
                    'color': self.LEVEL_COLORS[self.get_warning_level(pm25_avg)]
                })
        
        # Sort by PM2.5 descending
        cities_over.sort(key=lambda x: x['pm25'], reverse=True)
        return cities_over
    
    def get_warning_statistics(self) -> Dict:
        """
        Get statistics about warning levels across all cities.
        
        Returns:
            Dictionary with counts of cities in each warning level
        """
        stats = {
            'good': 0,
            'moderate': 0,
            'unhealthy_sensitive': 0,
            'unhealthy': 0,
            'very_unhealthy': 0,
            'hazardous': 0,
            'no_data': 0,
            'total': 0
        }
        
        cities = self.db.get_all_cities()
        stats['total'] = len(cities)
        
        for city in cities:
            pm25_avg = self.db.get_parameter_for_city_or_nearest(city['id'], 'pm25', hours=24)[0]
            if pm25_avg is None:
                stats['no_data'] += 1
            else:
                level = self.get_warning_level(pm25_avg)
                stats[level] += 1
        
        return stats
