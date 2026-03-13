"""Multi-city wind snapshot for debugging GUI vs DB vs external sources.

Uses the same data source as the GUI: DatabaseManager.get_all_latest_weather()
(respectively get_latest_weather per city). No hardcoded city names or thresholds.
Run from project root: python tools/wind_snapshot.py
"""

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

    # Same query path as GUI: get_all_latest_weather() for map/overview,
    # get_latest_weather(city_id) for single-city panel
    all_weather = db.get_all_latest_weather()
    if not all_weather:
        print("No weather data in DB.")
        return 0

    # Threshold for "suspicious" wind (optional, from calibration; no hardcode)
    try:
        threshold = db.get_calibration_parameter("wind_speed_warning_threshold_mps")
        if threshold is None:
            threshold = 15.0
        else:
            threshold = float(threshold)
    except Exception:
        threshold = 15.0

    print("=" * 70)
    print("WIND SNAPSHOT (same data as GUI: latest row per city)")
    print("=" * 70)
    print(f"Source: get_all_latest_weather()  |  Warning threshold: >{threshold:.1f} m/s")
    print("-" * 70)
    print(f"{'City':<25} {'wind_speed':>10} {'source':<22} {'measurement_timestamp'}")
    print("-" * 70)

    high_count = 0
    for w in sorted(all_weather, key=lambda x: (x.get("city_name") or "")):
        city_name = w.get("city_name") or "?"
        wind_speed = w.get("wind_speed")
        source = w.get("source") or "?"
        ts = w.get("measurement_timestamp") or w.get("timestamp") or "?"
        if isinstance(ts, str):
            ts_str = ts[:19] if len(ts) > 19 else ts
        else:
            ts_str = str(ts)[:19] if ts else "?"

        ws_str = f"{wind_speed:.1f} m/s" if wind_speed is not None else "–"
        if wind_speed is not None and wind_speed > threshold:
            high_count += 1
        print(f"{city_name:<25} {ws_str:>10} {source:<22} {ts_str}")

    print("-" * 70)
    print(f"Total cities: {len(all_weather)}  |  Cities with wind_speed > {threshold:.1f} m/s: {high_count}")
    print("=" * 70)
    logger.info(
        f"[WIND SNAPSHOT] {len(all_weather)} cities, {high_count} with wind_speed > {threshold:.1f} m/s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
