"""Derived metrics calculator."""

from typing import List, Dict, Optional
import logging
from database.db_manager import DatabaseManager
from analytics.normalization_engine import NormalizationEngine
from analytics.solar_composite import calculate_solar_index_from_composite

logger = logging.getLogger("WeatherApp.analytics.derived_metrics")

# Declarativ beskrivning av vilka input-parametrar som krävs per index.
# Detta används av debug-verktyg för att dynamiskt se vilka parametrar som
# behövs och om de finns i databasen – ingen hårdkodning på flera ställen.
ANALYTICAL_INPUTS: Dict[str, List[str]] = {
    "solar_index": ["solar_radiation", "uv_index", "sunshine_duration"],
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
        self._norm = NormalizationEngine(db)

    def calculate(self, data: List[Dict]) -> Dict:
        """Calculate derived metrics from data."""
        return {}

    def _normalize_value(self, value: Optional[float], parameter: str) -> Optional[float]:
        """Normalize using NormalizationEngine (DB normalization_profile)."""
        out, _ = self._norm.normalize(parameter, value, debug_trace=False)
        return out

    def calculate_solar_index(self, city_id: int, *, debug_trace: bool = False) -> Optional[float]:
        """
        Calculate solar index for a city from composite_index_definition + profiles.

        Weights and combine mode come from DB (composite_index_definition), not code defaults.
        """
        try:
            weather = self.db.get_latest_weather(city_id)
            if not weather:
                logger.debug(f"No weather data for city {city_id}")
                return None
            idx, _tr = calculate_solar_index_from_composite(
                self.db, dict(weather), self._norm, debug_trace=debug_trace
            )
            if idx is not None:
                logger.debug(f"Calculated solar_index={idx:.3f} for city {city_id}")
            return idx
        except Exception as e:
            logger.error(f"Error calculating solar_index for city {city_id}: {e}", exc_info=True)
            return None
