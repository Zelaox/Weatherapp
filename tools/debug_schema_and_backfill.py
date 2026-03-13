"""CLI-verktyg för att debugga schema vs backfill (ingen hardcoding av kolumner).

Kör:
    python tools/debug_schema_and_backfill.py

Rapporterar:
    - weather_data-kolumner
    - vilka parametrar backfill använder (via parameter_registry)
    - saknade kolumner i weather_data
    - migrations på disk och förväntade kolumner vs faktiska
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager  # type: ignore  # noqa: E402
from utils.logger import WeatherLogger  # type: ignore  # noqa: E402


def main() -> int:
    logger = WeatherLogger()
    db = DatabaseManager()

    logger.info("=== SCHEMA/BACKFILL DEBUG START ===")

    # 1) Schema health
    schema_health: Dict[str, Any] = db.get_schema_health()
    tables = schema_health.get("tables", [])
    columns = schema_health.get("columns", {})
    migrations = schema_health.get("migrations_on_disk", [])
    expected = schema_health.get("expected_columns", {})
    missing = schema_health.get("missing_columns", {})

    logger.info(f"Tabeller i databasen: {sorted(tables)}")
    logger.info("Kolumner i key-tabeller:")
    for table, cols in columns.items():
        logger.info(f"  {table}: {cols}")

    logger.info(f"Migrations på disk: {migrations}")
    logger.info(f"Förväntade kolumner per migration: {expected}")
    logger.info(f"Saknade kolumner vs förväntat: {missing}")

    # 2) Backfill vs schema-diagnos
    diag = db.diagnose_backfill_schema()
    weather_cols = diag.get("weather_columns", [])
    backfill_params = diag.get("backfill_parameters", [])
    missing_in_db = diag.get("missing_in_db", [])

    logger.info("=== BACKFILL vs SCHEMA ===")
    logger.info(f"weather_data kolumner: {weather_cols}")
    logger.info(f"Backfill-parametrar (från parameter_registry): {backfill_params}")
    logger.info(f"Saknade kolumner i weather_data (som backfill använder): {missing_in_db}")

    # 3) Sammanfattning till stdout
    print("=" * 60)
    print("SCHEMA / BACKFILL DEBUG RAPPORT")
    print("=" * 60)
    print("\n[weather_data kolumner]")
    print(", ".join(weather_cols))

    print("\n[Backfill-parametrar (parameter_registry weather/solar/storm)]")
    print(", ".join(backfill_params))

    print("\n[Saknade kolumner i weather_data (kritisk lista)]")
    if missing_in_db:
        for col in missing_in_db:
            print(f"  - {col}")
    else:
        print("  Inga saknade kolumner upptäckta.")

    print("\n[Migrations på disk]")
    for m in migrations:
        print(f"  - {m}")

    print("\n[Saknade kolumner vs deklarerade migrations]")
    if missing:
        for table, cols in missing.items():
            print(f"  {table}: {cols}")
    else:
        print("  Inga mismatch mot deklarerade expected_columns.")

    print("\nTips:")
    print("  - Om t.ex. 'cape' saknas i weather_data men finns i backfill-parametrar:")
    print("    kör migrations för weather-kolumner (t.ex. migration_add_weather_columns.sql)")
    print("    och kör sedan detta debug-skript igen tills listan är tom.")
    print("=" * 60)

    logger.info("=== SCHEMA/BACKFILL DEBUG SLUT ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

