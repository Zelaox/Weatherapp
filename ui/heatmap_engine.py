"""Heatmap engine - reads from DB, not API."""

from database.db_manager import DatabaseManager
from typing import List, Dict
import logging

logger = logging.getLogger("WeatherApp.ui.heatmap_engine")


class HeatmapEngine:
    """Heatmap engine - reads from DB, not API."""
    
    def __init__(self, db: DatabaseManager):
        """
        Initialize heatmap engine.
        
        Args:
            db: Database manager instance
        """
        self.db = db
    
    def get_heatmap_data(self) -> List[Dict]:
        """
        Get heatmap data from database.
        
        Returns:
            List of {lat, lon, value} dicts
        """
        try:
            readings = self.db.get_latest_sensor_readings()
            return [
                {
                    'lat': r['latitude'],
                    'lon': r['longitude'],
                    'value': r['last_value']
                }
                for r in readings
            ]
        except Exception as e:
            logger.error(f"Error getting heatmap data: {e}")
            return []
