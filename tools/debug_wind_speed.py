"""Debug script to verify wind_speed unit conversion."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager  # type: ignore  # noqa: E402
from utils.logger import WeatherLogger  # type: ignore  # noqa: E402


def main() -> int:
    logger = WeatherLogger()
    db = DatabaseManager()

    print("=" * 60)
    print("WIND SPEED CONVERSION DEBUG REPORT")
    print("=" * 60)

    # 1) Backfill data (openmeteo_backfill)
    print("\n1. BACKFILL DATA (openmeteo_backfill):")
    backfill_stats = db.debug_wind_speed_conversion(source_filter="openmeteo_backfill")
    print("\nStatistics by city:")
    for stat in backfill_stats["statistics"][:10]:
        avg_wind = stat.get("avg_wind")
        max_wind = stat.get("max_wind")
        high_cnt = stat.get("high_wind_count")
        print(
            f"  City {stat['city_id']}: "
            f"avg={avg_wind:.2f} m/s, "
            f"max={max_wind:.2f} m/s, "
            f"high_wind_count={high_cnt}"
        )

    print("\nHigh wind speed samples (>15 m/s):")
    for sample in backfill_stats["high_wind_samples"][:5]:
        print(
            f"  ID {sample['id']}: {sample['wind_speed']:.2f} m/s "
            f"(city_id={sample['city_id']}, source={sample['source']})"
        )

    # 2) Live data (openmeteo)
    print("\n2. LIVE DATA (openmeteo):")
    live_stats = db.debug_wind_speed_conversion(source_filter="openmeteo")
    if live_stats["statistics"]:
        for stat in live_stats["statistics"][:5]:
            avg_wind = stat.get("avg_wind")
            print(f"  City {stat['city_id']}: avg={avg_wind:.2f} m/s")
    else:
        print("  No live data found")

    # 3) Expected range
    print(f"\n3. EXPECTED RANGE: {backfill_stats['expected_range']}")

    print("\n" + "=" * 60)
    print("If average wind speeds are >10 m/s, unit conversion may be missing.")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

