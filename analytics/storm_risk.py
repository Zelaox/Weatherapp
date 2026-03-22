"""Storm risk calculator.

Implements a meteorologically reasonable storm_risk index in the range [0, 1]
based on CAPE and convective / humidity parameters as described in
docs/ANALYTICAL_MAP.md.
"""

from typing import Optional
import logging

from database.db_manager import DatabaseManager
from analytics.normalization_engine import NormalizationEngine


logger = logging.getLogger("WeatherApp.analytics.storm_risk")


class StormRiskCalculator:
    """Calculate storm_risk for a city from latest weather data."""

    def __init__(self, db: DatabaseManager):
        self._db = db
        self._norm = NormalizationEngine(db)

    # --- Normalisation helpers -------------------------------------------------
    def _normalize(self, value: Optional[float], parameter: str) -> Optional[float]:
        """Normalize value to [0, 1] using normalization_profile + winsor bounds."""
        if value is None:
            return None
        out, _ = self._norm.normalize(parameter, value, debug_trace=False)
        return out

    def _cape_factor(self, cape: float) -> float:
        """Piecewise scaling factor for CAPE from cape_piecewise_segment (DB)."""
        return self._db.get_cape_storm_risk_factor(cape)

    # --- Public API ------------------------------------------------------------
    def calculate(self, city_id: int) -> Optional[float]:
        """Calculate storm_risk in [0, 1] for the given city."""
        try:
            weather = self._db.get_latest_weather(city_id)
            if not weather:
                logger.debug("StormRisk: no weather data for city_id=%s", city_id)
                return None

            cape = weather.get("cape")
            conv_precip = weather.get("convective_precipitation")
            precip_prob = weather.get("precipitation_probability")
            humidity = weather.get("humidity")
            wind_speed = weather.get("wind_speed")

            # Normalize inputs
            conv_norm = self._normalize(conv_precip, "convective_precipitation")
            precip_norm = self._normalize(precip_prob, "precipitation_probability")
            hum_norm = self._normalize(humidity, "humidity")
            wind_norm = self._normalize(wind_speed, "wind_speed")

            terms = []

            # Weights – if calibration parameters exist, use them; otherwise fall back
            w_conv = self._get_weight("storm_risk_convective_weight", default=0.4)
            w_precip = self._get_weight("storm_risk_precip_prob_weight", default=0.3)
            w_hum = self._get_weight("storm_risk_humidity_weight", default=0.2)
            w_wind = self._get_weight("storm_risk_wind_weight", default=0.1)

            base_risk = 0.0
            weight_sum = 0.0

            if conv_norm is not None:
                base_risk += w_conv * conv_norm
                weight_sum += w_conv
            if precip_norm is not None:
                base_risk += w_precip * precip_norm
                weight_sum += w_precip
            if hum_norm is not None:
                base_risk += w_hum * hum_norm
                weight_sum += w_hum
            if wind_norm is not None:
                # Higher wind should DECREASE storm risk (more mixing)
                base_risk -= w_wind * wind_norm
                weight_sum += w_wind

            if weight_sum <= 0.0:
                logger.debug(
                    "StormRisk: insufficient normalized data for city_id=%s", city_id
                )
                return None

            # Normalize base_risk by total positive weight to keep it within a stable range
            base_risk = base_risk / weight_sum

            # CAPE gate: if no CAPE, no storm risk
            if cape is None:
                logger.debug("StormRisk: CAPE is None for city_id=%s -> risk=0", city_id)
                return 0.0

            cape_factor = self._cape_factor(float(cape))
            storm_risk = base_risk * cape_factor
            storm_risk = max(0.0, min(1.0, storm_risk))

            logger.debug(
                "StormRisk: city_id=%s base_risk=%.3f cape=%.1f factor=%.2f score=%.3f",
                city_id,
                base_risk,
                cape,
                cape_factor,
                storm_risk,
            )
            return storm_risk

        except Exception as exc:
            logger.error("StormRisk: error calculating for city_id=%s: %s", city_id, exc, exc_info=True)
            return None

    # --- Calibration helpers ---------------------------------------------------
    def _get_weight(self, key: str, default: float) -> float:
        """Read a weight from calibration_parameters with a safe default."""
        try:
            raw = self._db.get_calibration_parameter(key)
            if raw is None:
                return default
            return float(raw)
        except Exception:
            return default

