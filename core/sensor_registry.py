"""Database-driven sensor registry."""

from database.db_manager import DatabaseManager
from typing import List, Dict, Optional
import json
import logging

logger = logging.getLogger("WeatherApp.core.sensor_registry")


class SensorRegistry:
    """Database-driven sensor registry."""
    
    def __init__(self, db: DatabaseManager):
        """
        Initialize sensor registry.
        
        Args:
            db: Database manager instance
        """
        self.db = db
    
    def get_active_sensors(self) -> List[Dict]:
        """
        Get all active sensors from database.
        
        Returns:
            List of sensor dicts with all metadata
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM sensors WHERE enabled = 1 ORDER BY id"""
            )
            rows = cursor.fetchall()
            sensors = []
            for row in rows:
                sensor_dict = dict(row)
                # Parse config_json if present
                if sensor_dict.get('config_json'):
                    try:
                        sensor_dict['config_json'] = json.loads(sensor_dict['config_json'])
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Invalid JSON in config_json for sensor {sensor_dict.get('id')}")
                        sensor_dict['config_json'] = {}
                else:
                    sensor_dict['config_json'] = {}
                sensors.append(sensor_dict)
            return sensors
        except Exception as e:
            logger.error(f"Error getting active sensors: {e}")
            return []
    
    def get_sensors_by_provider(self, provider_type: str) -> List[Dict]:
        """
        Get sensors for a specific provider type.
        
        Args:
            provider_type: Provider type to filter by
            
        Returns:
            List of sensor dicts
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM sensors 
                   WHERE enabled = 1 AND provider_type = ? 
                   ORDER BY id""",
                (provider_type,)
            )
            rows = cursor.fetchall()
            sensors = []
            for row in rows:
                sensor_dict = dict(row)
                # Parse config_json if present
                if sensor_dict.get('config_json'):
                    try:
                        sensor_dict['config_json'] = json.loads(sensor_dict['config_json'])
                    except (json.JSONDecodeError, TypeError):
                        sensor_dict['config_json'] = {}
                else:
                    sensor_dict['config_json'] = {}
                sensors.append(sensor_dict)
            return sensors
        except Exception as e:
            logger.error(f"Error getting sensors by provider {provider_type}: {e}")
            return []
    
    def get_sensor(self, sensor_id: int) -> Optional[Dict]:
        """
        Get single sensor by ID.
        
        Args:
            sensor_id: Sensor ID
            
        Returns:
            Sensor dict or None if not found
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM sensors WHERE id = ?""",
                (sensor_id,)
            )
            row = cursor.fetchone()
            if row:
                sensor_dict = dict(row)
                # Parse config_json if present
                if sensor_dict.get('config_json'):
                    try:
                        sensor_dict['config_json'] = json.loads(sensor_dict['config_json'])
                    except (json.JSONDecodeError, TypeError):
                        sensor_dict['config_json'] = {}
                else:
                    sensor_dict['config_json'] = {}
                return sensor_dict
            return None
        except Exception as e:
            logger.error(f"Error getting sensor {sensor_id}: {e}")
            return None
    
    def update_sensor_status(self, sensor_id: int, error: Optional[str] = None):
        """
        Update sensor error status.
        
        Args:
            sensor_id: Sensor ID
            error: Error message (None to clear error)
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            if error is None:
                # Clear error
                cursor.execute(
                    """UPDATE sensors 
                       SET last_error = NULL, error_count = 0 
                       WHERE id = ?""",
                    (sensor_id,)
                )
            else:
                # Set error and increment error_count
                cursor.execute(
                    """UPDATE sensors 
                       SET last_error = ?, error_count = error_count + 1 
                       WHERE id = ?""",
                    (error, sensor_id)
                )
            conn.commit()
        except Exception as e:
            logger.error(f"Error updating sensor status for {sensor_id}: {e}")
