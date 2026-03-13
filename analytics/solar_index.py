"""Solar index calculator wrapper."""

from typing import Optional
import logging

from database.db_manager import DatabaseManager
from analytics.derived_metrics import DerivedMetricsCalculator


logger = logging.getLogger("WeatherApp.analytics.solar_index")


class SolarIndexCalculator:
    """
    Thin wrapper around DerivedMetricsCalculator for backward compatible API.

    WeatherController._compute_analytical_indices expects a class with
    a calculate(city_id: int) -> Optional[float] method.
    """

    def __init__(self, db: DatabaseManager):
        self._db = db
        self._derived = DerivedMetricsCalculator(db)

    def calculate(self, city_id: int) -> Optional[float]:
        """Calculate solar index for a given city."""
        logger.debug("SolarIndexCalculator.calculate() for city_id=%s", city_id)
        return self._derived.calculate_solar_index(city_id)

