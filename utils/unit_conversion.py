"""Generic, DB-driven unit conversion helpers.

This module centralizes unit conversion logic so that providers and
backfill scripts use the same rules. Target units always come from
`parameter_registry.unit`; source units are defined per provider and
parameter in a minimal mapping that can be migrated into DB metadata
later.
"""

from __future__ import annotations

from typing import Optional

from database.db_manager import DatabaseManager
from utils.logger import WeatherLogger


def convert_parameter_unit(
    db: DatabaseManager,
    param_name: str,
    raw_value: float,
    provider_name: str,
    logger: Optional[WeatherLogger] = None,
) -> float:
    """
    Convert parameter value from provider unit to database unit.

    Target unit is read from parameter_registry (single source of truth).
    Source unit is provider-specific and minimal; extending it should
    preferably be done via DB metadata over time.
    """
    if logger is None:
        logger = WeatherLogger()

    # Read target unit from parameter_registry
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT unit FROM parameter_registry WHERE parameter_name = ?",
            (param_name,),
        )
        row = cursor.fetchone()
    except Exception:
        # If registry lookup fails, fail-safe: keep original value
        return raw_value

    if not row:
        # Parameter not in registry, return as-is
        return raw_value

    # sqlite3.Row is configured in DatabaseManager; support both index and key access
    target_unit = row["unit"] if hasattr(row, "keys") else row[0]

    # Provider-specific source unit mapping.
    # According to Open-Meteo docs, wind_speed_10m is returned in km/h by default.
    provider_source_units = {
        "openmeteo": {
            "wind_speed": "km/h",
        },
        "openweather": {
            "wind_speed": "m/s",
        },
    }

    source_unit = provider_source_units.get(provider_name, {}).get(param_name)
    if not source_unit or source_unit == target_unit:
        return raw_value

    # Conversion factors for common wind speed units → m/s
    conversion_factors = {
        ("km/h", "m/s"): 1.0 / 3.6,
        ("knots", "m/s"): 0.514444,
        ("mph", "m/s"): 0.44704,
    }

    factor = conversion_factors.get((source_unit, target_unit))
    if factor:
        return raw_value * factor

    # Unknown conversion, log and return raw value
    logger.warning(
        f"[UNITS] Unknown unit conversion: {source_unit} -> {target_unit} "
        f"for {param_name} from {provider_name}, returning raw value"
    )
    return raw_value

