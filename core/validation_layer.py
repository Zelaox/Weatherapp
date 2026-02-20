"""Validation layer - no fallbacks, just validation."""

from typing import Optional
from core.sensor_provider import SensorReading


class ValidationLayer:
    """Validation layer - no fallbacks."""
    
    def validate_reading(self, reading: SensorReading) -> tuple[bool, Optional[str]]:
        """
        Validate sensor reading.
        
        Args:
            reading: Sensor reading to validate
            
        Returns:
            (is_valid, error_message)
        """
        if reading.value is None:
            return False, "Value is None"
        
        if not isinstance(reading.value, (int, float)):
            return False, f"Value is not numeric: {type(reading.value)}"
        
        # Allow negative values for some parameters (e.g., temperature can be negative)
        # But reject obviously invalid values
        if abs(reading.value) > 1e10:  # Unreasonably large
            return False, f"Value is unreasonably large: {reading.value}"
        
        if not reading.parameter:
            return False, "Parameter name is empty"
        
        if not reading.timestamp:
            return False, "Timestamp is missing"
        
        return True, None
