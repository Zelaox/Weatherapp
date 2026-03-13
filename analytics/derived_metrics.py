"""Derived metrics calculator."""

from typing import List, Dict, Optional
import logging
from database.db_manager import DatabaseManager

logger = logging.getLogger("WeatherApp.analytics.derived_metrics")

# Declarativ beskrivning av vilka input-parametrar som krävs per index.
# Detta används av debug-verktyg för att dynamiskt se vilka parametrar som
# behövs och om de finns i databasen – ingen hårdkodning på flera ställen.
ANALYTICAL_INPUTS: Dict[str, List[str]] = {
    "solar_index": ["solar_radiation", "uv_index", "sunshine_duration"],
    # För framtida index (storm_risk, smog_risk) lämnas deklarationerna här
    # även om själva beräkningarna inte är implementerade ännu.
    "storm_risk": [
        "cape",
        "convective_precipitation",
        "precipitation_probability",
        "humidity",
        "wind_speed",
    ],
    "smog_risk": [
        "o3",
        "solar_radiation",
        "wind_speed",
    ],
}


class DerivedMetricsCalculator:
    """Calculates derived metrics from weather data."""
    
    def __init__(self, db: DatabaseManager):
        """
        Initialize derived metrics calculator.
        
        Args:
            db: DatabaseManager instance
        """
        self.db = db
    
    def calculate(self, data: List[Dict]) -> Dict:
        """Calculate derived metrics from data."""
        # Placeholder implementation
        return {}
    
    def _normalize_value(self, value: Optional[float], parameter: str) -> Optional[float]:
        """
        Normalize a parameter value using winsorized bounds.
        
        Args:
            value: Parameter value (can be None)
            parameter: Parameter name (e.g., 'solar_radiation', 'uv_index')
            
        Returns:
            Normalized value [0, 1] or None if value is None or bounds unavailable
        """
        if value is None:
            return None
        
        # Get winsorized bounds (p5, p95)
        bounds = self.db.get_parameter_winsorized_bounds(parameter, 5.0, 95.0)
        if bounds is None or bounds[0] is None or bounds[1] is None:
            logger.debug(f"Could not get winsorized bounds for {parameter}, skipping normalization")
            return None
        
        lo, hi = bounds
        
        # Avoid division by zero
        if hi <= lo:
            logger.warning(f"Invalid bounds for {parameter}: lo={lo}, hi={hi}")
            return None
        
        # Normalize: clamp to [0, 1]
        normalized = (value - lo) / (hi - lo)
        return max(0.0, min(1.0, normalized))
    
    def calculate_solar_index(self, city_id: int) -> Optional[float]:
        """
        Calculate solar index for a city.
        
        Formula: w1*normalize(solar_radiation) + w2*normalize(uv_index) + w3*normalize(sunshine_duration)
        
        Args:
            city_id: City ID
            
        Returns:
            Solar index [0, 1] or None if insufficient data
        """
        try:
            # Get latest weather data
            weather = self.db.get_latest_weather(city_id)
            if not weather:
                logger.debug(f"No weather data for city {city_id}")
                return None
            
            # Get weights from calibration_parameters
            w1 = self.db.get_calibration_parameter('solar_index_radiation_weight')
            w2 = self.db.get_calibration_parameter('solar_index_uv_weight')
            w3 = self.db.get_calibration_parameter('solar_index_sunshine_weight')
            
            # Default weights if not configured
            if w1 is None:
                w1 = 0.5
            else:
                w1 = float(w1)
            if w2 is None:
                w2 = 0.3
            else:
                w2 = float(w2)
            if w3 is None:
                w3 = 0.2
            else:
                w3 = float(w3)
            
            # Normalize weights to sum to 1.0
            total_weight = w1 + w2 + w3
            if total_weight > 0:
                w1 = w1 / total_weight
                w2 = w2 / total_weight
                w3 = w3 / total_weight
            else:
                # Fallback if all weights are zero
                w1, w2, w3 = 0.5, 0.3, 0.2
            
            # Get and normalize values
            solar_rad_norm = self._normalize_value(weather.get('solar_radiation'), 'solar_radiation')
            uv_norm = self._normalize_value(weather.get('uv_index'), 'uv_index')
            sunshine_norm = self._normalize_value(weather.get('sunshine_duration'), 'sunshine_duration')
            
            # Calculate weighted sum (only include terms with valid normalized values)
            terms = []
            weights = []
            
            if solar_rad_norm is not None:
                terms.append(solar_rad_norm)
                weights.append(w1)
            
            if uv_norm is not None:
                terms.append(uv_norm)
                weights.append(w2)
            
            if sunshine_norm is not None:
                terms.append(sunshine_norm)
                weights.append(w3)
            
            # Need at least one valid term
            if not terms:
                logger.debug(f"Insufficient solar data for city {city_id} (all values None or unnormalizable)")
                return None
            
            # Normalize weights to sum to 1.0 for available terms
            total_available_weight = sum(weights)
            if total_available_weight > 0:
                weights = [w / total_available_weight for w in weights]
            else:
                # Equal weights if all are zero
                weights = [1.0 / len(weights)] * len(weights)
            
            # Calculate weighted sum
            solar_index = sum(term * weight for term, weight in zip(terms, weights))
            
            # Clamp to [0, 1]
            solar_index = max(0.0, min(1.0, solar_index))
            
            logger.debug(f"Calculated solar_index={solar_index:.3f} for city {city_id} (terms: {len(terms)})")
            return solar_index
            
        except Exception as e:
            logger.error(f"Error calculating solar_index for city {city_id}: {e}", exc_info=True)
            return None
