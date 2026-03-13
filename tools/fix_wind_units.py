"""One-off migration tool to fix historical wind_speed units in weather_data.

Design goals:
- No hårdkodade parametrar utanför det som redan finns i registry/migrations.
- Använder samma unit-conversion logik som övriga systemet (utils.unit_conversion.convert_parameter_unit).
- Aggressivt defensiv: ändrar bara rader som är uppenbart orimliga som m/s.

Strategi (per rad):
- Läs city_id, wind_speed, source, timestamp/measurement_timestamp.
- För rader där source antyder en provider vi känner till (t.ex. 'openmeteo', 'openmeteo_backfill', 'openweather'):
  - Läs ett tröskelvärde för "misstänkt hög vind" från calibration_parameters:
    - key: wind_speed_migration_threshold_mps, default: 20.0
  - Om wind_speed > threshold:
    - Tolkad som att värdet sannolikt ligger i fel enhet (t.ex. km/h lagrat som m/s).
    - Kör convert_parameter_unit(db, 'wind_speed', raw_value, provider_name) där:
      - provider_name = 'openmeteo' om source börjar med 'openmeteo'
      - provider_name = 'openweather' om source börjar med 'openweather'
    - Skriv tillbaka det konverterade värdet.

Detta innebär att vi återanvänder samma mapping:
- parameter_registry.unit = 'm/s' för wind_speed.
- provider_source_units i convert_parameter_unit anger t.ex. 'openmeteo' -> 'km/h'.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Tuple

# Ensure project root is on sys.path when run as a script
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager  # type: ignore  # noqa: E402
from utils.logger import WeatherLogger  # type: ignore  # noqa: E402
from utils.unit_conversion import convert_parameter_unit  # type: ignore  # noqa: E402


def _get_migration_threshold(db: DatabaseManager, logger: WeatherLogger) -> float:
    """Read wind_speed migration threshold from calibration_parameters, with safe default."""
    try:
        raw = db.get_calibration_parameter("wind_speed_migration_threshold_mps")
        if raw is None:
            return 20.0
        value = float(raw)
        if value <= 0:
            logger.warning(
                f"[MIGRATION] Ogiltigt wind_speed_migration_threshold_mps={value}, "
                f"använder default 20.0 m/s"
            )
            return 20.0
        return value
    except Exception as e:
        logger.warning(
            f"[MIGRATION] Kunde inte läsa wind_speed_migration_threshold_mps: {e}, "
            f"använder default 20.0 m/s"
        )
        return 20.0


def _detect_provider_from_source(source: str) -> str | None:
    """Infer logical provider name from weather_data.source."""
    if not source:
        return None
    s = source.lower()
    if s.startswith("openmeteo"):
        return "openmeteo"
    if s.startswith("openweather"):
        return "openweather"
    return None


def find_suspicious_rows(db: DatabaseManager, threshold: float) -> Tuple[int, int]:
    """Return counts of total and suspicious rows for debug, without modifying data."""
    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*) 
        FROM weather_data 
        WHERE wind_speed IS NOT NULL
        """
    )
    total = cursor.fetchone()[0] or 0

    cursor.execute(
        """
        SELECT COUNT(*) 
        FROM weather_data 
        WHERE wind_speed IS NOT NULL
          AND wind_speed > ?
        """,
        (threshold,),
    )
    suspicious = cursor.fetchone()[0] or 0

    return total, suspicious


def migrate_wind_units(db: DatabaseManager, logger: WeatherLogger) -> None:
    """Main migration function."""
    threshold = _get_migration_threshold(db, logger)
    logger.info(
        f"[MIGRATION] Startar fix_wind_units med threshold={threshold:.1f} m/s "
        f"för misstänkt felaktiga vindvärden."
    )

    total, suspicious = find_suspicious_rows(db, threshold)
    logger.info(
        f"[MIGRATION] weather_data rader med wind_speed!=NULL: {total}, "
        f"varav {suspicious} > {threshold:.1f} m/s"
    )

    if suspicious == 0:
        logger.info("[MIGRATION] Inga misstänkt höga vindvärden hittades – ingen ändring gjord.")
        return

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, city_id, wind_speed, source, measurement_timestamp
        FROM weather_data
        WHERE wind_speed IS NOT NULL
          AND wind_speed > ?
        ORDER BY wind_speed DESC
        """,
        (threshold,),
    )

    rows = cursor.fetchall()
    logger.info(f"[MIGRATION] Hämtade {len(rows)} rader med vind > {threshold:.1f} m/s för migrering.")

    updated = 0
    skipped = 0

    for row in rows:
        try:
            # sqlite3.Row or tuple compatible
            row_id = row["id"] if hasattr(row, "keys") else row[0]
            city_id = row["city_id"] if hasattr(row, "keys") else row[1]
            wind_speed = row["wind_speed"] if hasattr(row, "keys") else row[2]
            source = row["source"] if hasattr(row, "keys") else row[3]
            meas_ts = row["measurement_timestamp"] if hasattr(row, "keys") else row[4]

            provider = _detect_provider_from_source(str(source or ""))
            if provider is None:
                logger.warning(
                    f"[MIGRATION] Rad id={row_id}, city_id={city_id}: okänd provider i source='{source}', "
                    f"hoppar över."
                )
                skipped += 1
                continue

            if wind_speed is None:
                skipped += 1
                continue

            try:
                raw_val = float(wind_speed)
            except (ValueError, TypeError):
                logger.warning(
                    f"[MIGRATION] Rad id={row_id}, city_id={city_id}: kunde inte tolka wind_speed={wind_speed}, "
                    f"hoppar över."
                )
                skipped += 1
                continue

            # Kör samma unit-conversion som övriga systemet
            new_val = convert_parameter_unit(db, "wind_speed", raw_val, provider, logger=logger)

            # Om konverteringen inte ändrar värdet och det fortfarande är extremt högt, logga & skippa
            if abs(new_val - raw_val) < 1e-6 and new_val > threshold:
                logger.warning(
                    f"[MIGRATION] Rad id={row_id}, city_id={city_id}: convert_parameter_unit ändrade inte "
                    f"värdet (raw={raw_val}, new={new_val}), och det är fortfarande >{threshold:.1f} m/s. "
                    f"Lämnar orört."
                )
                skipped += 1
                continue

            cursor.execute(
                """
                UPDATE weather_data
                SET wind_speed = ?
                WHERE id = ?
                """,
                (new_val, row_id),
            )
            updated += 1

            logger.info(
                f"[MIGRATION] Uppdaterade rad id={row_id}, city_id={city_id}, source={source}: "
                f"wind_speed {raw_val:.2f} -> {new_val:.2f} m/s "
                f"(measurement_timestamp={meas_ts}) via provider={provider}"
            )

        except Exception as e:
            logger.warning(f"[MIGRATION] Fel vid hantering av rad: {e}")
            skipped += 1

    conn.commit()
    logger.info(
        f"[MIGRATION] Klar: uppdaterade {updated} rader, hoppade över {skipped}. "
        f"Threshold={threshold:.1f} m/s, total med vind!=NULL={total}."
    )


def main() -> int:
    logger = WeatherLogger()
    db = DatabaseManager()

    try:
        migrate_wind_units(db, logger)
        return 0
    except Exception as e:
        logger.error(f"[MIGRATION] Kritiskt fel i fix_wind_units: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

