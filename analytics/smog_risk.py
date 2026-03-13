"""Smog risk calculator.

Calculates a smog_risk index in [0, 1] based on ozone, solar radiation,
and wind speed as described in docs/ANALYTICAL_MAP.md.
"""

from typing import Optional
import logging

from database.db_manager import DatabaseManager


logger = logging.getLogger("WeatherApp.analytics.smog_risk")


class SmogRiskCalculator:
    """Calculate smog_risk for a city from latest weather data."""

    def __init__(self, db: DatabaseManager):
        self._db = db

    def _normalize(self, value: Optional[float], parameter: str) -> Optional[float]:
        """Normalize value to [0, 1] using winsorized bounds."""
        if value is None:
            return None

        bounds = self._db.get_parameter_winsorized_bounds(parameter, 5.0, 95.0)
        if not bounds or bounds[0] is None or bounds[1] is None:
            logger.debug(
                "SmogRisk: no winsorized bounds for %s, cannot normalize", parameter
            )
            return None

        lo, hi = bounds
        if hi <= lo:
            logger.warning("SmogRisk: invalid bounds for %s: lo=%s hi=%s", parameter, lo, hi)
            return None

        norm = (value - lo) / (hi - lo)
        return max(0.0, min(1.0, norm))

    def calculate(self, city_id: int) -> Optional[float]:
        """Calculate smog_risk in [0, 1] for the given city."""
        try:
            weather = self._db.get_latest_weather(city_id)
            if not weather:
                logger.debug("SmogRisk: no weather data for city_id=%s", city_id)
                return None

            o3 = weather.get("o3")
            solar_radiation = weather.get("solar_radiation")
            wind_speed = weather.get("wind_speed")

            o3_norm = self._normalize(o3, "o3")
            solar_norm = self._normalize(solar_radiation, "solar_radiation")
            wind_norm = self._normalize(wind_speed, "wind_speed")

            # Weights from calibration_parameters, with safe defaults
            w_o3 = self._get_weight("smog_risk_o3_weight", default=0.5)
            w_solar = self._get_weight("smog_risk_solar_weight", default=0.3)
            w_wind = self._get_weight("smog_risk_wind_weight", default=0.2)

            score = 0.0
            weight_sum = 0.0

            if o3_norm is not None:
                score += w_o3 * o3_norm
                weight_sum += w_o3
            if solar_norm is not None:
                score += w_solar * solar_norm
                weight_sum += w_solar
            if wind_norm is not None:
                # Higher wind reduces smog risk
                score -= w_wind * wind_norm
                weight_sum += w_wind

            if weight_sum <= 0.0:
                logger.debug("SmogRisk: insufficient data for city_id=%s", city_id)
                return None

            score = score / weight_sum
            score = max(0.0, min(1.0, score))

            logger.debug(
                "SmogRisk: city_id=%s o3=%.3f solar=%.3f wind=%.3f score=%.3f",
                city_id,
                o3 if o3 is not None else float("nan"),
                solar_radiation if solar_radiation is not None else float("nan"),
                wind_speed if wind_speed is not None else float("nan"),
                score,
            )
            return score

        except Exception as exc:
            logger.error("SmogRisk: error calculating for city_id=%s: %s", city_id, exc, exc_info=True)
            return None

    def _get_weight(self, key: str, default: float) -> float:
        """Read a weight from calibration_parameters with a safe default."""
        try:
            raw = self._db.get_calibration_parameter(key)
            if raw is None:
                return default
            return float(raw)
        except Exception:
            return default

