"""Stations tab with analytical Leaflet map showing OpenAQ sensors."""

import json
import math
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox
)
from PyQt5.QtCore import Qt, QUrl, QTimer
from datetime import datetime
from zoneinfo import ZoneInfo
import logging
from utils.parameter_formatter import format_parameter_name
from analytics.warnings import WarningDetector
from analytics.normalization_engine import NormalizationEngine
from analytics.heatmap_interpolation import compute_pm25_heatmap
from utils.local_map_server import map_document_server_url, set_map_document_html

# Try to import QWebEngineView (optional dependency)
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEnginePage
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineView = None  # type: ignore[misc, assignment]
    QWebEngineProfile = None  # type: ignore[misc, assignment]
    QWebEnginePage = None  # type: ignore[misc, assignment]
    WEBENGINE_AVAILABLE = False

logger = logging.getLogger("WeatherApp.gui.stations_tab")

# ---------------------------------------------------------------------------
# Calibration parameters are now read from DB (calibration_parameters table).
# No hardcoded constants remain — all values derive from database.
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# MapDataBuilder
# ---------------------------------------------------------------------------

class MapDataBuilder:
    """
    Builds the full enriched JSON payload consumed by the Leaflet map.

    All intelligence lives here in Python.  The JavaScript layer only
    renders — it makes no decisions.

    Sub-computations:
      A  Per-city enriched record (AQI colour, trend, inversion score, region)
      B  Relative cluster analysis (deviation from 7-day national baseline)
      C  Winsorized inversion score (outlier-robust, temporally stable)
      D  Station density map (self-calibrating heatmap radius per city)
    """

    def __init__(self, db, warning_detector: WarningDetector, debug_mode: bool = False):
        self.db = db
        self.detector = warning_detector
        self.debug_mode = bool(debug_mode)
        self._calibration_cache = None  # Cache calibration params per build() call
        self._norm_engine = NormalizationEngine(db)

    def _build_heatmap_confidence(
        self,
        n_stations: int,
        coverage_fraction: float,
        total_cells: int,
        mean_interpolation_distance_km: Optional[float],
        calib: Dict,
        *,
        debug_trace: bool = False,
    ) -> Dict:
        """
        DB-driven heatmap confidence: gated levels + weighted score from components normalized
        via normalization_profile (heatmap_conf_* keys) and calibration weights/thresholds.
        """
        low_n = float(calib["heatmap_confidence_low_min_stations"])
        unr_n = float(calib["heatmap_confidence_unreliable_min_stations"])
        low_cov = float(calib["heatmap_confidence_low_max_coverage_fraction"])
        unr_cov = float(calib["heatmap_confidence_unreliable_max_coverage_fraction"])
        w_s = float(calib["heatmap_confidence_w_station"])
        w_c = float(calib["heatmap_confidence_w_coverage"])
        w_d = float(calib["heatmap_confidence_w_distance"])
        score_unreliable_below = float(calib["heatmap_confidence_score_unreliable_below"])
        score_low_below = float(calib["heatmap_confidence_score_low_below"])
        formula_version = float(calib["heatmap_confidence_formula_version"])

        w_sum = w_s + w_c + w_d
        if abs(w_sum - 1.0) > 0.02:
            raise RuntimeError(
                f"heatmap confidence weights must sum to 1.0 (got {w_sum} from DB calibration)"
            )
        if score_unreliable_below >= score_low_below:
            raise RuntimeError(
                "heatmap_confidence_score_unreliable_below must be < heatmap_confidence_score_low_below"
            )

        eng = self._norm_engine
        s_station_t, tr_st = eng.normalize_by_profile_key(
            "heatmap_conf_station_count", float(n_stations), debug_trace=debug_trace
        )
        s_cov_t, tr_cov = eng.normalize_by_profile_key(
            "heatmap_conf_coverage_fraction", float(coverage_fraction), debug_trace=debug_trace
        )
        if s_station_t is None or s_cov_t is None:
            raise RuntimeError(
                "heatmap confidence: station or coverage normalization returned None (check normalization_profile)"
            )
        s_station = float(s_station_t)
        s_cov = float(s_cov_t)

        reasons: List[str] = []
        gate_level = "ok"
        if total_cells <= 0 or n_stations < unr_n or coverage_fraction < unr_cov:
            gate_level = "unreliable"
            if n_stations < unr_n:
                reasons.append("few_stations")
            if coverage_fraction < unr_cov:
                reasons.append("low_coverage_fraction")
        elif n_stations < low_n or coverage_fraction < low_cov:
            gate_level = "low"
            if n_stations < low_n:
                reasons.append("stations_below_low_threshold")
            if coverage_fraction < low_cov:
                reasons.append("coverage_below_low_threshold")

        mean_km = mean_interpolation_distance_km
        s_dist: Optional[float] = None
        tr_dist = None
        if mean_km is not None:
            norm_d, tr_dist = eng.normalize_by_profile_key(
                "heatmap_conf_mean_distance_km", float(mean_km), debug_trace=debug_trace
            )
            if norm_d is None:
                raise RuntimeError(
                    "heatmap confidence: mean distance normalization returned None (check normalization_profile)"
                )
            s_dist = 1.0 - float(norm_d)

        if s_dist is None:
            w_den = w_s + w_c
            if w_den <= 0:
                raise RuntimeError("heatmap_confidence_w_station + w_coverage must be > 0 when distance unknown")
            w_eff_s = w_s / w_den
            w_eff_c = w_c / w_den
            score = w_eff_s * s_station + w_eff_c * s_cov
            comp_distance = None
        else:
            score = w_s * s_station + w_c * s_cov + w_d * s_dist
            comp_distance = round(s_dist, 4)

        score = _clamp(float(score), 0.0, 1.0)

        score_level = "ok"
        if score < score_unreliable_below:
            score_level = "unreliable"
            reasons.append("score_below_unreliable_threshold")
        elif score < score_low_below:
            score_level = "low"
            reasons.append("score_below_low_threshold")

        order = {"ok": 0, "low": 1, "unreliable": 2}
        level = gate_level if order[gate_level] >= order[score_level] else score_level

        out: Dict = {
            "level": level,
            "score": round(score, 4),
            "reasons": reasons,
            "coverage_fraction": round(coverage_fraction, 4),
            "n_stations": n_stations,
            "grid_cells_total": int(total_cells),
            "mean_interpolation_distance_km": round(mean_km, 3) if mean_km is not None else None,
            "formula_version": formula_version,
            "components": {
                "station_score": round(s_station, 4),
                "coverage_score": round(s_cov, 4),
                "distance_score": comp_distance,
            },
        }
        if debug_trace:
            out["debug"] = {
                "gate_level": gate_level,
                "score_level": score_level,
                "traces": {"station": tr_st, "coverage": tr_cov, "distance": tr_dist},
            }
        return out
    
    def _get_calibration_params(self) -> Dict[str, float]:
        """
        Get all calibration parameters from DB. Fail loudly if any required key is missing.
        
        Returns:
            Dictionary of calibration parameters
            
        Raises:
            RuntimeError: If any required calibration parameter is missing from DB
        """
        if self._calibration_cache is None:
            params = self.db.get_all_calibration_parameters()
            
            # Required keys for inversion model
            required_inversion = [
                'inversion_p_low', 'inversion_p_high',
                'inversion_wind_weight', 'inversion_humidity_weight'
            ]
            # Required keys for IDW
            required_idw = [
                'idw_power', 'idw_max_r_factor', 'idw_scale_percentile'
            ]
            required_heatmap_contract = [
                "heatmap_confidence_low_min_stations",
                "heatmap_confidence_unreliable_min_stations",
                "heatmap_confidence_low_max_coverage_fraction",
                "heatmap_confidence_unreliable_max_coverage_fraction",
                "heatmap_confidence_w_station",
                "heatmap_confidence_w_coverage",
                "heatmap_confidence_w_distance",
                "heatmap_confidence_score_unreliable_below",
                "heatmap_confidence_score_low_below",
                "heatmap_confidence_formula_version",
                "map_init_size_ready_timeout_ms",
                "normalization_winsor_min_samples",
            ]

            missing = []
            for key in required_inversion + required_idw + required_heatmap_contract:
                if key not in params or params[key] is None:
                    missing.append(key)
            
            if missing:
                error_msg = (
                    f"Missing required calibration parameters in DB: {', '.join(missing)}. "
                    f"Run migration_add_calibration_parameters.sql to seed the calibration_parameters table."
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Validate weights sum to 1.0
            wind_w = params.get('inversion_wind_weight', 0)
            hum_w = params.get('inversion_humidity_weight', 0)
            if abs(wind_w + hum_w - 1.0) > 0.01:
                logger.warning(
                    f"inversion_wind_weight ({wind_w}) + inversion_humidity_weight ({hum_w}) != 1.0. "
                    f"Normalizing to sum to 1.0."
                )
                total = wind_w + hum_w
                if total > 0:
                    params['inversion_wind_weight'] = wind_w / total
                    params['inversion_humidity_weight'] = hum_w / total
            
            self._calibration_cache = params
        
        return self._calibration_cache

    def _get_map_extent(self) -> Tuple[float, float, float, float]:
        """
        Get map/heatmap geographic extent (lat_min, lat_max, lon_min, lon_max).
        From calibration_parameters if all four keys present and valid; otherwise
        bbox of all cities in DB. No hardcoded coordinates.
        """
        try:
            lat_min = self.db.get_calibration_parameter("map_extent_lat_min")
            lat_max = self.db.get_calibration_parameter("map_extent_lat_max")
            lon_min = self.db.get_calibration_parameter("map_extent_lon_min")
            lon_max = self.db.get_calibration_parameter("map_extent_lon_max")
            if all(v is not None for v in (lat_min, lat_max, lon_min, lon_max)):
                lat_min, lat_max = float(lat_min), float(lat_max)
                lon_min, lon_max = float(lon_min), float(lon_max)
                if lat_min < lat_max and lon_min < lon_max:
                    return (lat_min, lat_max, lon_min, lon_max)
        except (TypeError, ValueError):
            pass
        # Fallback: bbox from all cities in DB
        all_cities = self.db.get_all_cities()
        lats = [c["latitude"] for c in all_cities if c.get("latitude") is not None]
        lons = [c["longitude"] for c in all_cities if c.get("longitude") is not None]
        if lats and lons:
            lat_min, lat_max = min(lats), max(lats)
            lon_min, lon_max = min(lons), max(lons)
            pad_lat = (lat_max - lat_min) * 0.05
            pad_lon = (lon_max - lon_min) * 0.05
            return (
                lat_min - pad_lat, lat_max + pad_lat,
                lon_min - pad_lon, lon_max + pad_lon,
            )
        # No cities: return a minimal default box (avoid division by zero later)
        return (55.0, 56.0, 13.0, 14.0)

    def _build_heatmap_input_points(
        self,
        all_cities: List[Dict],
        city_weather_by_id: Dict[int, Dict],
    ) -> Tuple[List[Dict], Dict[str, int]]:
        """
        heatmap_input_points = list of selected_pm25 per city.
        Policy A: aggregated_24h only from own-city rolling mean (get_rolling_average), never nearest.
        """
        cfg = self.db.get_heatmap_interpolation_config_row("pm25_heatmap")
        if not cfg:
            return [], {"raw_points_count": 0, "aggregated_points_count": 0, "total_points_used": 0}
        try:
            priority, _mpr, _w = self.db.get_heatmap_dual_source_config("pm25_heatmap")
        except RuntimeError as e:
            logger.error("Heatmap dual source config: %s", e)
            return [], {"raw_points_count": 0, "aggregated_points_count": 0, "total_points_used": 0}

        raw_rows = self.db.get_station_observation_latest_pm25_rows()
        raw_by_city: Dict[int, Dict] = {}
        for r in raw_rows:
            try:
                cid = int(r["city_id"])
            except (TypeError, ValueError, KeyError):
                continue
            raw_by_city[cid] = r

        out: List[Dict] = []
        n_raw = 0
        n_agg = 0
        for city in all_cities:
            city_id = int(city["id"])
            lat = float(city["latitude"])
            lon = float(city["longitude"])
            cw = city_weather_by_id.get(city_id)
            candidates: Dict[str, Dict] = {}

            rr = raw_by_city.get(city_id)
            if rr is not None and rr.get("value") is not None:
                try:
                    v_raw = float(rr["value"])
                except (TypeError, ValueError):
                    v_raw = None
                if v_raw is not None:
                    candidates["raw_latest"] = {
                        "lat": lat,
                        "lon": lon,
                        "value": v_raw,
                        "source": "raw_latest",
                        "city_id": city_id,
                        "measurement_ts": rr.get("measurement_timestamp"),
                        "collector_ts": rr.get("collector_timestamp"),
                    }

            own_agg = self.db.get_rolling_average(city_id, "pm25", hours=24)
            if own_agg is not None:
                candidates["aggregated_24h"] = {
                    "lat": lat,
                    "lon": lon,
                    "value": float(own_agg),
                    "source": "aggregated_24h",
                    "city_id": city_id,
                    "measurement_ts": (cw.get("measurement_ts") if cw else None),
                    "collector_ts": (cw.get("timestamp") if cw else None),
                }

            chosen = None
            for token in priority:
                if token in candidates:
                    chosen = candidates[token]
                    break
            if chosen:
                out.append(chosen)
                if chosen["source"] == "raw_latest":
                    n_raw += 1
                else:
                    n_agg += 1

        meta = {
            "raw_points_count": n_raw,
            "aggregated_points_count": n_agg,
            "total_points_used": len(out),
        }
        return out, meta

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def build(self) -> Dict:
        """
        Build and return the complete map payload.

        Returns:
            {
                "cities":         [...],   # per-city enriched records
                "sensors":        [...],   # raw sensor markers
                "cluster_alerts": [...],   # regional deviation alerts
                "score_metadata": {...},   # inversion score calibration info
            }
        """
        # ---- Fetch base data ----
        all_cities = self.db.get_all_cities()
        city_weather_list = self.db.get_cities_with_weather_for_map()
        city_weather_by_id = {cw["city_id"]: cw for cw in city_weather_list}
        all_sensors  = self.db.get_all_sensors()
        national_7d  = self.db.get_national_pm25_7day_average()

        # ---- Map extent (DB-driven: calibration or bbox of all cities) ----
        map_extent = self._get_map_extent()  # (lat_min, lat_max, lon_min, lon_max)

        # ---- Get calibration parameters from DB ----
        calib = self._get_calibration_params()
        inversion_p_low = calib['inversion_p_low']
        inversion_p_high = calib['inversion_p_high']
        
        # ---- Fetch winsorized bounds once for both parameters ----
        wind_lo, wind_hi = self.db.get_parameter_winsorized_bounds(
            "wind_speed", inversion_p_low, inversion_p_high
        )
        hum_lo, hum_hi = self.db.get_parameter_winsorized_bounds(
            "humidity", inversion_p_low, inversion_p_high
        )

        bounds_available = (
            wind_lo is not None and wind_hi is not None
            and hum_lo is not None and hum_hi is not None
        )

        wind_range = (wind_hi - wind_lo) if bounds_available else None
        hum_range  = (hum_hi  - hum_lo)  if bounds_available else None

        # ---- Collect row count for metadata ----
        try:
            conn = self.db.get_connection()
            cur  = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM weather_data "
                "WHERE wind_speed IS NOT NULL AND humidity IS NOT NULL"
            )
            data_rows_used = cur.fetchone()[0]
        except Exception:
            data_rows_used = 0

        score_metadata = {
            "wind_bounds":      [wind_lo, wind_hi],
            "humidity_bounds":  [hum_lo,  hum_hi],
            "percentile_range": [inversion_p_low, inversion_p_high],
            "data_rows_used":   data_rows_used,
            "bounds_available": bounds_available,
        }

        # ---- Build per-city enriched records (all cities; PM2.5 from own or nearest station) ----
        cities_out = []
        valid_cities = []   # only cities with pm25_24h != None

        for city in all_cities:
            city_id = city["id"]
            cw = city_weather_by_id.get(city_id)

            # PM2.5: own data or nearest station within radius (read-side fallback)
            pm25_24h, _src_id, src_name, dist_km = self.db.get_parameter_for_city_or_nearest(
                city_id, "pm25", hours=24
            )
            pm25_source_label = None
            if pm25_24h is not None and dist_km is not None and dist_km > 0 and src_name:
                pm25_source_label = f"{src_name} ({dist_km:.0f} km)"

            # AQI level + colour — single source of truth: WarningDetector
            if pm25_24h is not None:
                level = self.detector.get_warning_level(pm25_24h)
                color = self.detector.LEVEL_COLORS[level]
                level_name = self.detector.LEVEL_NAMES[level]
            else:
                level = "no_data"
                color = "#cccccc"
                level_name = "Ingen data"

            # 24-hour PM2.5 trend (only when city has own weather data)
            if cw:
                history = self.db.get_weather_history(city_id, hours=24)
                trend_24h = [
                    {"ts": str(h.get("timestamp", "")), "pm25": h.get("pm25")}
                    for h in history if h.get("pm25") is not None
                ]
            else:
                trend_24h = []

            # Inversion score (requires wind/humidity from own weather)
            inversion_score = self._compute_inversion_score(
                wind_speed=cw.get("wind_speed") if cw else None,
                humidity=cw.get("humidity") if cw else None,
                wind_lo=wind_lo, wind_hi=wind_hi,
                hum_lo=hum_lo,   hum_hi=hum_hi,
                wind_range=wind_range, hum_range=hum_range,
                bounds_available=bounds_available,
                city_id=city_id,
            )

            record = {
                "city_id":          city_id,
                "city_name":        city["name"],
                "latitude":         city["latitude"],
                "longitude":        city["longitude"],
                "measurement_ts":   (cw.get("measurement_ts") if cw else None),
                "pm25_24h":         pm25_24h,
                "pm25_source_label": pm25_source_label,
                "aqi_level":        level,
                "aqi_color":        color,
                "aqi_level_name":   level_name,
                "temperature":      cw.get("temperature") if cw else None,
                "humidity":         cw.get("humidity") if cw else None,
                "wind_speed":       cw.get("wind_speed") if cw else None,
                "no2":              cw.get("no2") if cw else None,
                "o3":               cw.get("o3") if cw else None,
                "trend_24h":        trend_24h,
                "inversion_score":  inversion_score,
                "low_density":      False,
                "density_radius":   0,
                "cluster_region":   None,
            }
            cities_out.append(record)

            if pm25_24h is not None:
                valid_cities.append(record)

        # ---- Section B: regional cluster analysis ----
        cluster_alerts = self._compute_cluster_alerts(valid_cities, national_7d)

        # ---- Section D: station density ----
        self._compute_density(cities_out)

        # ---- Diagnostic: trend point count ----
        total_trend = sum(len(c["trend_24h"]) for c in cities_out)
        logger.info(
            f"[Heatmap] trend_24h: {total_trend:,} points "
            f"across {len(cities_out)} cities "
            f"(avg {total_trend // max(len(cities_out), 1)} per city)"
        )

        heatmap_input_points, heatmap_point_meta = self._build_heatmap_input_points(
            all_cities, city_weather_by_id
        )
        logger.info(
            "[Heatmap] Dual-source selection: raw=%s aggregated=%s total_input=%s",
            heatmap_point_meta.get("raw_points_count", 0),
            heatmap_point_meta.get("aggregated_points_count", 0),
            heatmap_point_meta.get("total_points_used", 0),
        )

        # ---- Format sensors for raw marker layer ----
        sensors_out = self._format_sensors(all_sensors)

        # ---- Section E: IDW grid + colour scale anchors ----
        calib = self._get_calibration_params()
        idw_scale_percentile = calib['idw_scale_percentile']
        
        if not heatmap_input_points:
            idw_grid_raw, idw_meta = [], {}
            heatmap_extra = {
                "heatmap_confidence": self._build_heatmap_confidence(
                    n_stations=0,
                    coverage_fraction=0.0,
                    total_cells=0,
                    mean_interpolation_distance_km=None,
                    calib=calib,
                    debug_trace=self.debug_mode,
                ),
                "engine_config": {},
                "heatmap_meta": dict(heatmap_point_meta),
                "warning_codes": [],
            }
        else:
            idw_grid_raw, idw_meta, heatmap_extra = compute_pm25_heatmap(
                self.db,
                heatmap_input_points,
                map_extent,
                calib,
                context_key="pm25_heatmap",
                debug_mode=self.debug_mode,
            )
            hm_meta = heatmap_extra.get("heatmap_meta") or {}
            hm_meta = {**hm_meta, **heatmap_point_meta}
            heatmap_extra["heatmap_meta"] = hm_meta
        total_cells = 0
        if idw_meta:
            try:
                g_n = int(idw_meta.get("grid_n", 0))
                total_cells = max(0, g_n * g_n)
            except (TypeError, ValueError):
                total_cells = 0

        # Optional smoothing (DB-driven)
        kernel = calib.get('heatmap_smoothing_kernel_size', 3.0)
        try:
            kernel = int(kernel)
        except (TypeError, ValueError):
            kernel = 3
        if kernel > 1 and idw_grid_raw:
            idw_grid = self._smooth_idw_grid(idw_grid_raw, idw_meta, kernel_size=kernel)
        else:
            idw_grid = idw_grid_raw

        if idw_grid:
            _vals = sorted(row[2] for row in idw_grid)
            _idx = min(int(len(_vals) * idw_scale_percentile / 100), len(_vals) - 1)
            idw_max = _vals[_idx]      # colour scale anchor at idw_scale_percentile
            idw_true_max = _vals[-1]   # actual grid maximum — UI clamp indicator only
        else:
            _vals = []
            idw_max = 1.0
            idw_true_max = 1.0

        coverage_smooth = 0.0
        if total_cells > 0:
            coverage_raw = len(idw_grid_raw) / total_cells if idw_grid_raw else 0.0
            coverage_smooth = len(idw_grid) / total_cells if idw_grid else 0.0
            # Edge-band (yttersta 3 rader/kolumner) coverage efter smoothing
            edge_band = 3
            edge_count = 0
            if idw_grid and idw_meta:
                lat_min = float(idw_meta["lat_min"])
                lon_min = float(idw_meta["lon_min"])
                lat_step = float(idw_meta["lat_step"])
                lon_step = float(idw_meta["lon_step"])
                g_n = int(idw_meta["grid_n"])
                for lat, lon, _v in idw_grid:
                    col = int(round((lon - lon_min) / lon_step))
                    row = int(round((lat - lat_min) / lat_step))
                    if (
                        row < edge_band
                        or row >= g_n - edge_band
                        or col < edge_band
                        or col >= g_n - edge_band
                    ):
                        edge_count += 1
            logger.info(
                "[Heatmap] Coverage: raw=%d/%.0f (%.1f%%), smooth=%d/%.0f (%.1f%%), edge_cells_with_values=%d",
                len(idw_grid_raw) if idw_grid_raw else 0,
                float(total_cells),
                coverage_raw * 100.0,
                len(idw_grid) if idw_grid else 0,
                float(total_cells),
                coverage_smooth * 100.0,
                edge_count,
            )

        heatmap_confidence = heatmap_extra.get("heatmap_confidence") or {}
        if not heatmap_confidence:
            raise RuntimeError("compute_pm25_heatmap returned empty heatmap_confidence")

        hc_vis = self.db.get_heatmap_confidence_visual_mapping()
        for lvl in ("ok", "low", "unreliable"):
            if lvl not in hc_vis:
                raise RuntimeError(
                    f"heatmap_confidence_visual_mapping missing row for confidence_level={lvl!r}"
                )

        wms = calib.get("normalization_winsor_min_samples")
        norm_report = self.db.get_normalization_readiness_report(
            winsor_min_samples=max(1, int(wms)) if wms is not None else 20
        )
        unusable_names = [
            p["parameter_name"]
            for p in norm_report.get("parameters", [])
            if p.get("status") == "unusable"
        ]
        normalization_readiness = {
            "unusable_parameters": unusable_names,
            "unstable_count": int(norm_report.get("unstable_count", 0)),
            "unusable_count": int(norm_report.get("unusable_count", 0)),
            "registry_revision": norm_report.get("registry_revision"),
        }

        logger.info(
            f"[Heatmap] IDW scale: p{idw_scale_percentile}={idw_max:.2f} µg/m³  "
            f"true_max={idw_true_max:.2f} µg/m³"
        )

        # ---- Section F: Solar, Storm, and Lightning layers ----
        solar_layer = self._build_solar_layer(cities_out)
        storm_layer = self._build_storm_layer(cities_out)
        lightning_layer = self._build_lightning_layer()
        
        # ---- Compute IDW grids for solar and storm layers ----
        # Prepare cities with solar_index for IDW computation
        cities_with_solar = []
        for city in cities_out:
            city_id = city.get("city_id")
            if city_id:
                indices = self.db.get_latest_analytical_indices(city_id)
                if indices and indices.get('solar_index') is not None:
                    city_copy = city.copy()
                    city_copy['solar_index'] = indices['solar_index']
                    cities_with_solar.append(city_copy)
        
        # Prepare cities with storm_risk for IDW computation
        cities_with_storm = []
        for city in cities_out:
            city_id = city.get("city_id")
            if city_id:
                indices = self.db.get_latest_analytical_indices(city_id)
                if indices and indices.get('storm_risk') is not None:
                    city_copy = city.copy()
                    city_copy['storm_risk'] = indices['storm_risk']
                    cities_with_storm.append(city_copy)
        
        # Compute IDW grids (same geographic extent as PM2.5 heatmap)
        solar_idw_grid, solar_idw_meta = self._compute_layer_idw_grid(
            cities_with_solar, 'solar_index', 'solar', extent=map_extent
        )
        storm_idw_grid, storm_idw_meta = self._compute_layer_idw_grid(
            cities_with_storm, 'storm_risk', 'storm', extent=map_extent
        )
        
        # ---- Compute percentile-based scaling for all layers ----
        def _compute_percentile_scale(values: List[float], p_low: float = 5.0, p_high: float = 95.0):
            """Compute percentile-based scale bounds."""
            if not values:
                return None, None
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            idx_low = max(0, int(n * p_low / 100))
            idx_high = min(n - 1, int(n * p_high / 100))
            return sorted_vals[idx_low], sorted_vals[idx_high]
        
        # PM2.5 scaling (existing - using idw_scale_percentile)
        pm25_p5, pm25_p95 = None, None
        if idw_grid:
            pm25_values = [row[2] for row in idw_grid]
            pm25_p5, pm25_p95 = _compute_percentile_scale(pm25_values, 5.0, idw_scale_percentile)

        # Heatmap value domain / clipping (fully DB-driven)
        clip_min = calib.get('heatmap_clip_min')
        clip_max = calib.get('heatmap_clip_max')
        try:
            clip_min_f = float(clip_min) if clip_min is not None else None
        except (TypeError, ValueError):
            clip_min_f = None
        try:
            clip_max_f = float(clip_max) if clip_max is not None else None
        except (TypeError, ValueError):
            clip_max_f = None

        # Fallbacks: derive from current grid if DB values are unusable
        if idw_grid and (clip_min_f is None or clip_max_f is None or clip_min_f >= clip_max_f):
            vals = _vals or sorted(row[2] for row in idw_grid)
            if vals:
                clip_min_f = vals[0]
                clip_max_f = vals[-1]
        if clip_min_f is None:
            clip_min_f = 0.0
        if clip_max_f is None or clip_max_f <= clip_min_f:
            clip_max_f = clip_min_f + 1.0

        heatmap_config = {
            "value_min": pm25_p5,
            "value_max": pm25_p95,
            "clip_min": clip_min_f,
            "clip_max": clip_max_f,
        }
        
        # Solar scaling (p5-p95)
        solar_p5, solar_p95 = None, None
        if solar_idw_grid:
            solar_values = [row[2] for row in solar_idw_grid]
            solar_p5, solar_p95 = _compute_percentile_scale(solar_values, 5.0, 95.0)
        
        # Storm scaling (p5-p95)
        storm_p5, storm_p95 = None, None
        if storm_idw_grid:
            storm_values = [row[2] for row in storm_idw_grid]
            storm_p5, storm_p95 = _compute_percentile_scale(storm_values, 5.0, 95.0)
        
        # Build timestamp for cache-busting
        build_timestamp = datetime.now(ZoneInfo("Europe/Stockholm"))

        payload_out = {
            "cities":         cities_out,
            "sensors":        sensors_out,
            "cluster_alerts": cluster_alerts,
            "score_metadata": score_metadata,
            "map_extent":     {"lat_min": map_extent[0], "lat_max": map_extent[1], "lon_min": map_extent[2], "lon_max": map_extent[3]},
            "idw_grid":       idw_grid,
            "idw_meta":       idw_meta,
            "idw_max":        idw_max,
            "idw_true_max":   idw_true_max,
            "idw_scale_percentile": idw_scale_percentile,  # For JS template
            "pm25_p5":        pm25_p5,
            "pm25_p95":       pm25_p95,
            "heatmap_confidence": heatmap_confidence,
            "heatmap_engine": heatmap_extra.get("engine_config") or {},
            "heatmap_meta": heatmap_extra.get("heatmap_meta") or {},
            "heatmap_warnings": heatmap_extra.get("warning_codes") or [],
            "heatmap_confidence_visual": hc_vis,
            "map_init_timeout_ms": int(calib["map_init_size_ready_timeout_ms"]),
            "normalization_readiness": normalization_readiness,
            "heatmap_config": heatmap_config,
            "solar_layer":    solar_layer,
            "solar_idw_grid": solar_idw_grid,
            "solar_idw_meta": solar_idw_meta,
            "solar_p5":       solar_p5,
            "solar_p95":      solar_p95,
            "storm_layer":    storm_layer,
            "storm_idw_grid": storm_idw_grid,
            "storm_idw_meta": storm_idw_meta,
            "storm_p5":       storm_p5,
            "storm_p95":      storm_p95,
            "storm_layer_active": len(storm_layer) > 0,  # Flag for JS conditional rendering
            "lightning_layer": lightning_layer,
            "build_timestamp": build_timestamp.isoformat(),
            "data_freshness_seconds": 0,  # Always fresh
        }
        if self.debug_mode:
            payload_out["map_debug"] = {
                "heatmap_confidence": dict(heatmap_confidence),
                "heatmap_engine": heatmap_extra.get("engine_config") or {},
                "heatmap_extra": {k: v for k, v in heatmap_extra.items() if k != "heatmap_confidence"},
                "pm25_idw_cell_count": len(idw_grid or []),
                "normalization_readiness_full": norm_report,
                "calibration_keys_heatmap_confidence": [
                    "heatmap_confidence_low_min_stations",
                    "heatmap_confidence_unreliable_min_stations",
                    "heatmap_confidence_low_max_coverage_fraction",
                    "heatmap_confidence_unreliable_max_coverage_fraction",
                    "heatmap_confidence_w_station",
                    "heatmap_confidence_w_coverage",
                    "heatmap_confidence_w_distance",
                    "heatmap_confidence_score_unreliable_below",
                    "heatmap_confidence_score_low_below",
                    "heatmap_confidence_formula_version",
                    "map_init_size_ready_timeout_ms",
                    "normalization_winsor_min_samples",
                ],
            }
        return payload_out

    # ------------------------------------------------------------------
    # Section C — winsorized inversion score
    # ------------------------------------------------------------------

    def _compute_inversion_score(
        self,
        wind_speed: Optional[float],
        humidity:   Optional[float],
        wind_lo: Optional[float], wind_hi: Optional[float],
        hum_lo:  Optional[float], hum_hi:  Optional[float],
        wind_range: Optional[float], hum_range: Optional[float],
        bounds_available: bool,
        city_id: int,
    ) -> Optional[float]:
        """
        Compute inversion risk score in [0, 100].

        Returns None if bounds are unavailable, ranges are zero,
        or input values are None.
        """
        if not bounds_available:
            return None

        if wind_speed is None or humidity is None:
            return None

        if wind_range == 0:
            logger.info(
                f"inversion_score: wind_range=0 for city {city_id}, "
                f"score set to null (data quality signal)"
            )
            return None

        if hum_range == 0:
            logger.info(
                f"inversion_score: hum_range=0 for city {city_id}, "
                f"score set to null (data quality signal)"
            )
            return None

        # Get calibration weights from DB
        calib = self._get_calibration_params()
        wind_weight = calib['inversion_wind_weight']
        humidity_weight = calib['inversion_humidity_weight']

        wind_norm = _clamp((wind_speed - wind_lo) / wind_range, 0.0, 1.0)
        hum_norm  = _clamp((humidity   - hum_lo)  / hum_range,  0.0, 1.0)

        score = (
            (1.0 - wind_norm) * wind_weight
            + hum_norm        * humidity_weight
        ) * 100.0

        return round(score, 1)

    # ------------------------------------------------------------------
    # Section B — relative cluster analysis
    # ------------------------------------------------------------------

    def _compute_cluster_alerts(
        self,
        valid_cities: List[Dict],
        national_7d:  Optional[float],
    ) -> List[Dict]:
        """
        Emit cluster alerts only when a region deviates from the
        7-day national baseline by more than the deviation_factor.

        The north/south boundary is the median latitude of all valid cities.
        deviation_factor is derived from existing WarningDetector thresholds.
        """
        if not valid_cities or national_7d is None or national_7d == 0:
            return []

        # Deviation factor: ratio of two existing threshold values — not a new constant
        deviation_factor = (
            self.detector.THRESHOLDS["moderate"] / self.detector.THRESHOLDS["good"]
        )

        # Dynamic north/south boundary = median latitude of valid cities
        lats = sorted(c["latitude"] for c in valid_cities)
        n = len(lats)
        if n == 0:
            return []
        mid = n // 2
        if n % 2 == 1:
            median_lat = lats[mid]
        else:
            median_lat = (lats[mid - 1] + lats[mid]) / 2.0

        # Split into regions
        regions = {
            "norr":  [c for c in valid_cities if c["latitude"] >= median_lat],
            "söder": [c for c in valid_cities if c["latitude"] <  median_lat],
        }

        alerts = []
        for region_label, members in regions.items():
            if not members:
                continue
            region_mean = sum(c["pm25_24h"] for c in members) / len(members)
            threshold   = national_7d * deviation_factor

            if region_mean > threshold:
                deviation_pct = round((region_mean / national_7d - 1.0) * 100.0, 1)
                alerts.append({
                    "region":           region_label,
                    "region_mean":      round(region_mean, 2),
                    "national_baseline": round(national_7d, 2),
                    "deviation_pct":    deviation_pct,
                    "city_count":       len(members),
                })

        return alerts

    # ------------------------------------------------------------------
    # Section D — station density
    # ------------------------------------------------------------------

    def _compute_density(self, cities: List[Dict]) -> None:
        """
        Mutates each city record in-place with:
          density_radius  — count of neighbours within 2° lat/lon box
          low_density     — True if fewer than 2 neighbours
        """
        for city in cities:
            lat = city["latitude"]
            lon = city["longitude"]
            count = sum(
                1 for other in cities
                if other is not city
                and abs(other["latitude"]  - lat) <= 2.0
                and abs(other["longitude"] - lon) <= 2.0
            )
            city["density_radius"] = count
            city["low_density"]    = count < 2

    # ------------------------------------------------------------------
    # Section E — IDW grid interpolation (PM2.5: analytics/heatmap_interpolation.compute_pm25_heatmap)
    # ------------------------------------------------------------------

    def _compute_layer_idw_grid(
        self,
        cities: List[Dict],
        value_key: str,
        layer_name: str,
        extent: Optional[Tuple[float, float, float, float]] = None,
    ) -> Tuple[List[List[float]], Dict]:
        """
        Compute IDW grid for a specific layer (solar, storm, etc.).
        Bounding box: from optional extent, or from cities + 5%% padding.
        """
        # Filter cities with valid values
        valid_cities = [c for c in cities if c.get(value_key) is not None]
        if not valid_cities:
            return [], {}
        
        lats = [c["latitude"] for c in valid_cities]
        lons = [c["longitude"] for c in valid_cities]
        vals = [c[value_key] for c in valid_cities]
        n = len(valid_cities)
        
        if extent is not None:
            lat_min, lat_max, lon_min, lon_max = extent
            lat_pad = (lat_max - lat_min) * 0.05
            lon_pad = (lon_max - lon_min) * 0.05
            lat_min -= lat_pad
            lat_max += lat_pad
            lon_min -= lon_pad
            lon_max += lon_pad
        else:
            # Bounding box: actual station extents + 5% proportional padding
            lat_min, lat_max = min(lats), max(lats)
            lon_min, lon_max = min(lons), max(lons)
            lat_pad = (lat_max - lat_min) * 0.05
            lon_pad = (lon_max - lon_min) * 0.05
            lat_min -= lat_pad
            lat_max += lat_pad
            lon_min -= lon_pad
            lon_max += lon_pad
        
        # Grid resolution: scales with station density, bounded [80, 150]
        grid_n = max(80, min(150, int(math.sqrt(n) * 10)))
        
        # Get layer-specific IDW parameters (or use defaults)
        calib = self._get_calibration_params()
        idw_power_key = f'{layer_name}_idw_power'
        idw_max_r_factor_key = f'{layer_name}_idw_max_r_factor'
        
        base_power = calib.get('idw_power', 2.3)
        layer_power = calib.get(idw_power_key, base_power)
        idw_power = float(layer_power if layer_power is not None else base_power)
        
        base_r_factor = calib.get('idw_max_r_factor', 1.3)
        layer_r_factor = calib.get(idw_max_r_factor_key, base_r_factor)
        idw_max_r_factor = float(layer_r_factor if layer_r_factor is not None else base_r_factor)
        
        # Max IDW influence radius in km, derived from diagonal extent
        diag_deg = math.sqrt((lat_max - lat_min) ** 2 + (lon_max - lon_min) ** 2)
        approx_km = diag_deg * 111.0
        max_radius_km = approx_km / (math.sqrt(n) * max(idw_max_r_factor, 0.1))
        max_radius_km = max(1.0, max_radius_km)
        
        def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
            lat1_rad = math.radians(lat1)
            lat2_rad = math.radians(lat2)
            dlat = lat2_rad - lat1_rad
            dlon = math.radians(lon2 - lon1)
            x = dlon * math.cos((lat1_rad + lat2_rad) * 0.5)
            y = dlat
            return 6371.0 * math.sqrt(x * x + y * y)
        
        lat_step = (lat_max - lat_min) / grid_n
        lon_step = (lon_max - lon_min) / grid_n
        
        grid = []
        for i in range(grid_n):
            glat = lat_min + i * lat_step
            for j in range(grid_n):
                glon = lon_min + j * lon_step
                num = den = 0.0
                for slat, slon, sval in zip(lats, lons, vals):
                    d_km = _distance_km(glat, glon, slat, slon)
                    if d_km < 1e-3:  # coincident with station
                        num, den = sval, 1.0
                        break
                    if d_km <= max_radius_km:
                        w = 1.0 / max(d_km ** idw_power, 1e-9)
                        num += w * sval
                        den += w
                if den > 0:
                    grid.append([
                        round(glat, 5),
                        round(glon, 5),
                        round(num / den, 3),
                    ])
        
        meta = {
            "lat_min": lat_min,
            "lat_max": lat_max,
            "lon_min": lon_min,
            "lon_max": lon_max,
            "grid_n": grid_n,
            "lat_step": lat_step,
            "lon_step": lon_step,
        }
        return grid, meta

    # ------------------------------------------------------------------
    # Section E2 — smoothing helpers for IDW grids (NaN-aware)
    # ------------------------------------------------------------------

    @staticmethod
    def _smooth_idw_grid(
        grid: List[List[float]],
        meta: Dict,
        kernel_size: int,
    ) -> List[List[float]]:
        """
        Apply a simple NaN-aware box smoothing over an IDW grid.

        The input grid is a sparse list of [lat, lon, value] triples; cells that
        are missing in this list are treated as NaN. The output has the same
        sparse structure, with each cell averaged over its neighbourhood.
        """
        if not grid or not meta:
            return grid

        try:
            n = int(meta.get("grid_n", 0))
        except (TypeError, ValueError):
            return grid
        if n <= 0:
            return grid

        # Ensure odd kernel and at least 3x3
        if kernel_size < 1:
            return grid
        if kernel_size % 2 == 0:
            kernel_size += 1
        if kernel_size < 3:
            kernel_size = 3

        lat_min = float(meta["lat_min"])
        lon_min = float(meta["lon_min"])
        lat_step = float(meta["lat_step"])
        lon_step = float(meta["lon_step"])

        # Build dense matrix initialised with NaN
        dense = [[math.nan for _ in range(n)] for _ in range(n)]
        for lat, lon, val in grid:
            col = int(round((lon - lon_min) / lon_step))
            row = int(round((lat - lat_min) / lat_step))
            # y index inverted (north at top) is handled only when rendering,
            # not in this smoothing space.
            if 0 <= row < n and 0 <= col < n:
                dense[row][col] = float(val)

        radius = kernel_size // 2
        smoothed: List[List[float]] = []
        for row in range(n):
            for col in range(n):
                centre_val = dense[row][col]
                if math.isnan(centre_val):
                    # Keep NaN cells NaN to avoid inventing values far from stations
                    continue
                acc = 0.0
                cnt = 0
                for dr in range(-radius, radius + 1):
                    rr = row + dr
                    if rr < 0 or rr >= n:
                        continue
                    for dc in range(-radius, radius + 1):
                        cc = col + dc
                        if cc < 0 or cc >= n:
                            continue
                        v = dense[rr][cc]
                        if not math.isnan(v):
                            acc += v
                            cnt += 1
                if cnt == 0:
                    continue
                avg = acc / cnt
                lat = lat_min + row * lat_step
                lon = lon_min + col * lon_step
                smoothed.append([
                    round(lat, 5),
                    round(lon, 5),
                    round(avg, 3),
                ])

        return smoothed

    # ------------------------------------------------------------------
    # Sensor formatter
    # ------------------------------------------------------------------

    def _format_sensors(self, sensors: List[Dict]) -> List[Dict]:
        """Format raw sensor records for the JS sensor marker layer."""
        out = []
        for s in sensors:
            fs = s.copy()
            fs["formatted_parameter"] = (
                format_parameter_name(s["parameter"])
                if s.get("parameter")
                else "Okänd"
            )
            fs["formatted_timestamp"] = _format_timestamp(s.get("last_updated"))
            out.append(fs)
        return out
    
    # ------------------------------------------------------------------
    # Solar, Storm, and Lightning layers
    # ------------------------------------------------------------------
    
    def _build_solar_layer(self, cities: List[Dict]) -> List[Dict]:
        """
        Build solar layer from analytical indices.
        
        Returns:
            List of {lat, lon, solar_index} points
        """
        layer = []
        for city in cities:
            city_id = city.get("city_id")
            if not city_id:
                continue
            
            # Get latest analytical indices
            indices = self.db.get_latest_analytical_indices(city_id)
            if indices and indices.get('solar_index') is not None:
                layer.append({
                    "lat": city.get("latitude"),
                    "lon": city.get("longitude"),
                    "solar_index": indices['solar_index']
                })
        return layer
    
    def _should_render_storm_layer(self, cities: List[Dict]) -> bool:
        """
        Determine if storm layer should be rendered based on dynamic percentile thresholds.
        
        Returns True only if:
        - lightning_count > p75 of current dataset OR
        - CAPE > p75 of current dataset OR  
        - storm_risk > p75 of current dataset
        
        All thresholds computed dynamically from current data.
        """
        try:
            # Get lightning events count
            lightning_events = self.db.get_lightning_events(hours=24)
            lightning_count = len(lightning_events) if lightning_events else 0
            
            # Get CAPE values from latest weather_data
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cape FROM weather_data 
                WHERE cape IS NOT NULL 
                ORDER BY timestamp DESC 
                LIMIT 100
            """)
            cape_values = [row[0] for row in cursor.fetchall() if row[0] is not None]
            
            # Get storm_risk values
            storm_risks = []
            for city in cities:
                city_id = city.get('city_id')
                if city_id:
                    indices = self.db.get_latest_analytical_indices(city_id)
                    if indices and indices.get('storm_risk') is not None:
                        storm_risks.append(indices['storm_risk'])
            
            # Use fixed thresholds as specified by user
            # lightning_count > 0 (any lightning event)
            # CAPE > 100 J/kg
            # Note: radar reflectivity not yet available in current data model
            
            lightning_threshold = 0  # Any lightning event
            cape_threshold = 100.0  # J/kg
            
            # Check if any threshold is exceeded
            should_render = (
                lightning_count > lightning_threshold or
                (cape_values and max(cape_values) > cape_threshold)
            )
            
            logger.debug(
                f"[Storm Layer] Threshold check: lightning={lightning_count} (thresh={lightning_threshold}), "
                f"CAPE max={max(cape_values) if cape_values else 0} (thresh={cape_threshold}), "
                f"should_render={should_render}"
            )
            
            return should_render
            
        except Exception as e:
            logger.warning(f"Error checking storm layer thresholds: {e}")
            return False  # Default to not rendering on error
    
    def _build_storm_layer(self, cities: List[Dict]) -> List[Dict]:
        """
        Build storm layer from analytical indices.
        
        Only includes cities if storm layer should be rendered (thresholds met).
        
        Returns:
            List of {lat, lon, storm_risk} points, or empty list if thresholds not met
        """
        # Check if we should render storm layer
        if not self._should_render_storm_layer(cities):
            logger.debug("[Storm Layer] Thresholds not met, returning empty layer")
            return []  # Empty layer = no rendering in JS
        
        layer = []
        for city in cities:
            city_id = city.get("city_id")
            if not city_id:
                continue
            
            # Get latest analytical indices
            indices = self.db.get_latest_analytical_indices(city_id)
            if indices and indices.get('storm_risk') is not None:
                layer.append({
                    "lat": city.get("latitude"),
                    "lon": city.get("longitude"),
                    "storm_risk": indices['storm_risk']
                })
        return layer
    
    def _build_lightning_layer(self) -> List[Dict]:
        """
        Build lightning layer from lightning_events table.
        
        Returns:
            List of {lat, lon, timestamp, intensity} strike markers
        """
        try:
            # Get lightning display hours from calibration
            display_hours = self.db.get_calibration_parameter('lightning_display_hours')
            if display_hours is None:
                display_hours = 24.0
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.row_factory = lambda cursor, row: {
                'latitude': row[0],
                'longitude': row[1],
                'timestamp': row[2],
                'intensity': row[3]
            }
            
            cursor.execute("""
                SELECT latitude, longitude, timestamp, intensity
                FROM lightning_events
                WHERE timestamp >= datetime('now', '-' || ? || ' hours')
                ORDER BY timestamp DESC
            """, (display_hours,))
            
            rows = cursor.fetchall()
            layer = []
            for row in rows:
                layer.append({
                    "lat": row['latitude'],
                    "lon": row['longitude'],
                    "timestamp": str(row['timestamp']),
                    "intensity": row['intensity']
                })
            
            return layer
            
        except Exception as e:
            logger.warning(f"Error building lightning layer: {e}")
            return []


# ---------------------------------------------------------------------------
# Timestamp helper (module-level, used by both MapDataBuilder and StationsTab)
# ---------------------------------------------------------------------------

def _format_timestamp(timestamp) -> str:
    if timestamp is None:
        return "Okänd"
    try:
        if isinstance(timestamp, str):
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    dt = datetime.strptime(timestamp, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=ZoneInfo("Europe/Stockholm"))
                    return dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    continue
            return timestamp
        elif isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=ZoneInfo("Europe/Stockholm"))
            else:
                timestamp = timestamp.astimezone(ZoneInfo("Europe/Stockholm"))
            return timestamp.strftime("%Y-%m-%d %H:%M")
        else:
            return str(timestamp)
    except Exception:
        return "Okänd"



# ---------------------------------------------------------------------------
# CustomMarkerDialog (unchanged)
# ---------------------------------------------------------------------------

class CustomMarkerDialog(QDialog):
    """Dialog for adding custom markers."""

    def __init__(self, parent=None, lat: Optional[float] = None, lon: Optional[float] = None):
        super().__init__(parent)
        self.setWindowTitle("Lägg till Custom Marker")
        self.setModal(True)
        self._init_ui(lat, lon)

    def _init_ui(self, lat: Optional[float], lon: Optional[float]):
        layout = QFormLayout(self)

        self.lat_input = QLineEdit()
        if lat is not None:
            self.lat_input.setText(str(lat))
        self.lat_input.setPlaceholderText("t.ex. 59.3293")
        layout.addRow("Latitud:", self.lat_input)

        self.lon_input = QLineEdit()
        if lon is not None:
            self.lon_input.setText(str(lon))
        self.lon_input.setPlaceholderText("t.ex. 18.0686")
        layout.addRow("Longitud:", self.lon_input)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("t.ex. Min sensor")
        layout.addRow("Namn:", self.name_input)

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("t.ex. Luftkvalitetssensor hemma")
        layout.addRow("Beskrivning:", self.desc_input)

        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("Valfritt värde (t.ex. 15.5)")
        layout.addRow("Värde (µg/m³):", self.value_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _validate_and_accept(self):
        try:
            lat = float(self.lat_input.text().strip())
            lon = float(self.lon_input.text().strip())
            if not (-90 <= lat <= 90):
                QMessageBox.warning(self, "Fel", "Latitud måste vara mellan -90 och 90")
                return
            if not (-180 <= lon <= 180):
                QMessageBox.warning(self, "Fel", "Longitud måste vara mellan -180 och 180")
                return
            self.latitude    = lat
            self.longitude   = lon
            self.name        = self.name_input.text().strip()
            self.description = self.desc_input.text().strip()
            value_str        = self.value_input.text().strip()
            self.value       = float(value_str) if value_str else None
            self.accept()
        except ValueError:
            QMessageBox.warning(self, "Fel", "Ogiltiga koordinater eller värde")

    def get_marker_data(self) -> Dict:
        return {
            "latitude":    self.latitude,
            "longitude":   self.longitude,
            "name":        self.name,
            "description": self.description,
            "value":       self.value,
        }


# ---------------------------------------------------------------------------
# StationsTab
# ---------------------------------------------------------------------------

class StationsTab(QWidget):
    """Tab showing stations and sensors on an analytical interactive map."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._sensors_loaded = False
        # Set to True just before load() is called so that the handler
        # can ignore the spurious loadFinished(False) that QWebEngine emits
        # when the implicit about:blank navigation is aborted by the new load.
        self._expecting_html_load = False
        self._map_html_tmp: Optional[str] = None  # legacy: no longer used (localhost map document server)
        self.last_refresh_time = None
        self.refresh_timer = None
        self._init_ui()
        self._setup_auto_refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if not WEBENGINE_AVAILABLE:
            error_label = QLabel("WebEngine krävs för karta. Installera PyQtWebEngine.")
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: red; font-size: 14px; padding: 20px;")
            layout.addWidget(error_label)
            return

        toolbar = QHBoxLayout()
        refresh_button = QPushButton("Uppdatera Stationer")
        refresh_button.clicked.connect(self._refresh_map)
        toolbar.addWidget(refresh_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.map_view = QWebEngineView()
        self.map_view.loadFinished.connect(self._on_map_load_finished)
        layout.addWidget(self.map_view)
        self._ensure_map_web_profile()

        self._load_map()

    # ------------------------------------------------------------------
    # Map loading
    # ------------------------------------------------------------------

    def _ensure_map_web_profile(self) -> None:
        """Dedicated profile with DB user_agent (OSM tile policy)."""
        if not WEBENGINE_AVAILABLE or QWebEngineProfile is None or QWebEnginePage is None:
            return
        try:
            row = self.controller.db.get_map_tile_provider_row()
            ua = str(row["user_agent"])
        except Exception as e:
            logger.error("[Map] map_tile_provider unreadable: %s", e)
            return
        prof = QWebEngineProfile("WeatherAppMapProfile", self.map_view)
        prof.setHttpUserAgent(ua)
        page = QWebEnginePage(prof, self.map_view)
        self.map_view.setPage(page)

    def _load_map(self):
        if not WEBENGINE_AVAILABLE:
            return

        warning_detector = WarningDetector(self.controller.db)
        debug_mode = bool(self.controller.config.get_setting("debug_mode", False))
        builder = MapDataBuilder(self.controller.db, warning_detector, debug_mode=debug_mode)

        try:
            payload = builder.build()
        except Exception as e:
            logger.error(f"MapDataBuilder.build() failed: {e}")
            to = self.controller.db.get_calibration_parameter("map_init_size_ready_timeout_ms")
            try:
                mt = self.controller.db.get_map_tile_provider_for_payload()
            except Exception:
                mt = {}
            payload = {
                "cities": [], "sensors": [],
                "cluster_alerts": [], "score_metadata": {},
                "idw_grid": [], "idw_max": 1.0, "idw_true_max": 1.0,
                "map_init_timeout_ms": int(to) if to is not None else 0,
                "heatmap_confidence": {"level": "ok", "reasons": ["payload_build_failed"]},
                "heatmap_confidence_visual": {},
                "normalization_readiness": {"unusable_parameters": [], "unstable_count": 0, "unusable_count": 0},
                "map_tile": mt,
            }

        try:
            payload["map_tile"] = self.controller.db.get_map_tile_provider_for_payload()
        except Exception as e:
            logger.error(f"[Map] map_tile payload failed: {e}")
            return

        cities = payload.get("cities", [])
        n_heat = sum(1 for c in cities if c.get("pm25_24h") is not None)
        logger.info(f"[Heatmap] cities with pm25_24h: {n_heat}/{len(cities)}")

        # Map centre and bounds (bounds from payload map_extent for fitBounds)
        lats = [c["latitude"]  for c in cities if c.get("latitude")  is not None]
        lons = [c["longitude"] for c in cities if c.get("longitude") is not None]
        if lats and lons:
            center_lat = sum(lats) / len(lats)
            center_lon = sum(lons) / len(lons)
        else:
            center_lat, center_lon = 62.0, 15.0
        map_extent = payload.get("map_extent")  # { lat_min, lat_max, lon_min, lon_max } or None

        # Serialise the full payload here so we can measure its size before
        # generating the HTML.  The same string is embedded verbatim in the
        # HTML — no double serialisation.
        payload_json = json.dumps(payload, default=str)

        opacity_int = int(self.controller.config.get_setting("heatmap_opacity", 70))
        try:
            html = self._generate_map_html(
                payload_json, opacity_int, center_lat, center_lon, map_extent=map_extent
            )
        except Exception as exc:
            logger.error(f"[Heatmap] _generate_map_html failed: {exc}", exc_info=True)
            return

        logger.info(
            f"[Heatmap] payload: {len(payload_json):,} B JSON  "
            f"/ {len(html):,} B HTML  "
            f"/ {len(html) / 1024 / 1024:.2f} MB total"
        )
        # Large HTML: use singleton localhost document server so tile requests
        # get http Referer (OSM policy); setHtml/file:// are insufficient.
        try:
            set_map_document_html(html)
            map_url = map_document_server_url()
        except Exception as exc:
            logger.error(f"[Heatmap] local map document server failed: {exc}", exc_info=True)
            return

        logger.info(f"[Heatmap] loading map from {map_url}")

        # Arm the flag BEFORE load() so that the handler is ready for the
        # loadFinished(True) that follows the about:blank abort.
        self._expecting_html_load = True
        self.map_view.load(QUrl(map_url))
        self.map_view.page().titleChanged.connect(self._on_title_changed)
        self._sensors_loaded = True

    def _setup_auto_refresh(self):
        """Setup automatic map refresh on data updates and periodic timer."""
        # Connect to data_updated signal
        self.controller.data_updated.connect(self._on_data_updated)
        
        # Setup periodic timer
        refresh_interval = self.controller.db.get_calibration_parameter('map_refresh_interval_seconds')
        if refresh_interval is None:
            refresh_interval = 90.0  # Default: 90 seconds
        
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_map)
        self.refresh_timer.start(int(refresh_interval * 1000))
        
        logger.info(f"[Heatmap] Auto-refresh enabled: signal-driven + periodic ({refresh_interval}s)")
    
    def _on_data_updated(self, city_id: int, data_id: int):
        """Handle data_updated signal with debouncing."""
        # Debounce: only refresh if last refresh was > 5 seconds ago
        now = datetime.now(ZoneInfo("Europe/Stockholm"))
        if self.last_refresh_time is None or (now - self.last_refresh_time).total_seconds() > 5:
            logger.debug(f"[Heatmap] Data updated signal received (city_id={city_id}), refreshing map")
            self._refresh_map()
            self.last_refresh_time = now
    
    def _refresh_map(self):
        """Refresh map display from database only."""
        logger.info("Uppdaterar analytisk karta från databas")
        self._load_map()

    def _on_map_load_finished(self, ok: bool) -> None:
        """
        Called by QWebEngineView.loadFinished for every navigation, including
        the implicit about:blank that QWebEngine starts on creation.

        When setHtml() is called it aborts that about:blank navigation which
        emits loadFinished(False).  We MUST NOT treat that as a real failure:
        the genuine loadFinished(True) for our HTML fires immediately after.

        The _expecting_html_load flag is armed by _load_map() just before
        setHtml() so that any event received while the flag is False is
        unconditionally discarded (stale initial-blank events before our first
        setHtml call).

        ok=False with flag armed = about:blank abort → warn, keep flag set,
                                    wait for the True that follows.
        ok=True  with flag armed = our HTML loaded  → consume flag, inject.
        """
        if not self._expecting_html_load:
            # Stale event from before we ever called setHtml — discard.
            return
        if not ok:
            # Very likely the about:blank abort.  Log a warning but leave the
            # flag set so the real ok=True still triggers injection.
            logger.warning("[Heatmap] loadFinished(False) received — "
                           "likely about:blank abort; waiting for ok=True")
            return
        # Genuine successful load of our HTML.
        self._expecting_html_load = False
        logger.info("[Heatmap] loadFinished(True) — scheduling initHeatOverlay via Qt event loop")
        QTimer.singleShot(0, self._inject_heat_layer)

    def _inject_heat_layer(self) -> None:
        """
        Phase 1: read-only snapshot of the full JS state via runJavaScript
        callback.  console.log is silently discarded by QWebEngine — only
        uncaught exceptions reach Python as 'js: ...' lines.  The callback
        is the only reliable channel for getting values back to Python.

        The snapshot is pure read — no map.invalidateSize() side-effect.
        Every variable access is guarded with typeof so a missing variable
        returns a descriptive string instead of throwing.
        QWebEngine returns the plain JS object directly as a Python dict.
        """
        self.map_view.page().runJavaScript(
            """
            (function() {
                return {
                    L_exists:        typeof L !== "undefined",
                    idw_grid_len:    (typeof PAYLOAD !== "undefined" && PAYLOAD.idw_grid)
                                         ? PAYLOAD.idw_grid.length : "no PAYLOAD.idw_grid",
                    idw_meta_ok:     (typeof PAYLOAD !== "undefined" && PAYLOAD.idw_meta)
                                         ? JSON.stringify(PAYLOAD.idw_meta) : "no PAYLOAD.idw_meta",
                    heatMax_val:     typeof heatMax !== "undefined" ? heatMax : "undefined",
                    map_exists:      typeof map !== "undefined",
                    map_size:        typeof map !== "undefined" ? map.getSize() : "no map",
                    map_container_w: typeof map !== "undefined" ? map.getContainer().clientWidth : "no map"
                };
            })()
            """,
            self._on_heat_diagnostics
        )

    def _on_heat_diagnostics(self, result) -> None:
        """
        Phase 2: log each field of the snapshot individually so the output is
        readable at a glance, then schedule initHeatOverlay() via a second
        QTimer.singleShot(0) hop.

        Two Qt event-loop cycles are required:
          - Cycle 1 (in _on_map_load_finished): lets the page script finish
          - Cycle 2 (here): lets Qt's layout engine assign pixel dimensions
            to the QWebEngineView container before the canvas renders
        """
        logger.info("[Heatmap] pre-creation diagnostics:")
        if isinstance(result, dict):
            for k, v in result.items():
                logger.info(f"  {k}: {v}")
        else:
            logger.info(f"  raw: {result}")

        QTimer.singleShot(
            0,
            lambda: self.map_view.page().runJavaScript("beginHeatmapAttachWhenSized();"),
        )
        logger.info("[Heatmap] beginHeatmapAttachWhenSized() scheduled (second QTimer hop)")

    # ------------------------------------------------------------------
    # HTML / Leaflet generation
    # ------------------------------------------------------------------

    def _generate_map_html(
        self,
        payload_json: str,
        opacity_int: int,
        center_lat: float,
        center_lon: float,
        map_extent: Optional[Dict] = None,
    ) -> str:
        """
        Generate the full Leaflet HTML.
        If map_extent is provided (lat_min, lat_max, lon_min, lon_max), the map
        uses fitBounds so the full extent is visible; otherwise setView(center, 6).
        """
        # Normalize opacity for JS canvas alpha (expects 0.0–1.0)
        opacity_float = round(opacity_int / 100.0, 2)
        # Bounds for fitBounds (when map_extent from payload)
        has_bounds = (
            map_extent is not None
            and all(map_extent.get(k) is not None for k in ("lat_min", "lat_max", "lon_min", "lon_max"))
        )
        if has_bounds:
            b_lat_min = float(map_extent["lat_min"])
            b_lat_max = float(map_extent["lat_max"])
            b_lon_min = float(map_extent["lon_min"])
            b_lon_max = float(map_extent["lon_max"])
            map_init_js = f"map.fitBounds([[{b_lat_min}, {b_lon_min}], [{b_lat_max}, {b_lon_max}]], {{ padding: [20, 20] }});"
        else:
            b_lat_min = b_lat_max = b_lon_min = b_lon_max = 0.0  # unused
            map_init_js = f"map.setView([{center_lat}, {center_lon}], 6);"

        # No icon loading - use circleMarker for lightning markers
        lightning_icon_data_url = ""

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body  {{ margin:0; padding:0; font-family: sans-serif; }}
  #map  {{ height:100vh; width:100%; }}

  /* Layer toggle toolbar */
  #layer-toolbar {{
    position: absolute; top: 10px; left: 50px; z-index: 1000;
    background: rgba(255,255,255,0.92); border-radius: 6px;
    padding: 6px 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    display: flex; gap: 8px; align-items: center;
  }}
  .layer-btn {{
    padding: 4px 10px; border: 1px solid #999; border-radius: 4px;
    cursor: pointer; font-size: 12px; background: #f0f0f0;
    user-select: none;
  }}
  .layer-btn.active {{ background: #3a7bd5; color: #fff; border-color: #3a7bd5; }}

  /* Cluster alert banner */
  #cluster-banner {{
    position: absolute; bottom: 30px; left: 50%; transform: translateX(-50%);
    z-index: 1000; display: flex; flex-direction: column; gap: 6px;
    max-width: 480px; width: 90%;
  }}
  .cluster-alert {{
    background: rgba(220,53,69,0.88); color: #fff;
    padding: 7px 14px; border-radius: 6px; font-size: 13px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.35);
  }}

  /* Popup styles */
  .popup-title     {{ font-weight: bold; font-size: 14px; margin-bottom: 4px; }}
  .aqi-badge       {{ display:inline-block; padding:2px 8px; border-radius:10px;
                      color:#fff; font-size:11px; font-weight:bold; margin-bottom:6px; }}
  .sparkline-wrap  {{ margin: 6px 0; }}
  .inv-bar-wrap    {{ margin: 6px 0; }}
  .inv-bar-bg      {{ background:#e0e0e0; border-radius:4px; height:10px; width:180px; }}
  .inv-bar-fill    {{ height:10px; border-radius:4px; }}
  .meta-note       {{ font-size:10px; color:#888; margin-top:4px; }}
  .low-density-note {{ font-size:11px; color:#e67e22; margin-top:4px; }}
  #heatmap-confidence-badge {{
    position: absolute; top: 52px; right: 12px; z-index: 1000;
    font-size: 11px; padding: 4px 10px; border-radius: 14px;
    background: rgba(255,255,255,0.92); border: 1px solid #bbb;
    box-shadow: 0 1px 4px rgba(0,0,0,0.2); max-width: 220px;
  }}
  #heatmap-confidence-badge.unreliable {{ border-color: #c0392b; color: #922b21; }}
  #heatmap-confidence-badge.low {{ border-color: #e67e22; color: #a04000; }}
  #heatmap-confidence-badge.ok {{ border-color: #27ae60; color: #1e8449; }}
</style>
</head>
<body>

<div id="layer-toolbar">
  <span style="font-size:12px;font-weight:bold;color:#555;">Lager:</span>
  <span class="layer-btn active" id="btn-markers"  onclick="toggleLayer('markers')">Stationer</span>
  <span class="layer-btn active" id="btn-heatmap"  onclick="toggleLayer('heatmap')">Heatmap</span>
  <span class="layer-btn" id="btn-solar"  onclick="toggleLayer('solar')">Sol</span>
  <span class="layer-btn" id="btn-storm"  onclick="toggleLayer('storm')">Åska</span>
  <span class="layer-btn" id="btn-lightning"  onclick="toggleLayer('lightning')">Blixtar</span>
  <span class="layer-btn active" id="btn-sensors"  onclick="toggleLayer('sensors')">Sensorer</span>
  <div id="scale-clamp-note" style="display:none; font-size:11px; color:#b03030; margin-left:8px;"></div>
</div>

<div id="cluster-banner"></div>
<div id="heatmap-confidence-banner"></div>
<div id="heatmap-confidence-badge" style="display:none;"></div>
<div id="map"></div>

<script>
// ── Payload injected by Python ────────────────────────────────────────────
var PAYLOAD = {payload_json};

var cities        = PAYLOAD.cities        || [];
var sensors       = PAYLOAD.sensors       || [];
var clusterAlerts = PAYLOAD.cluster_alerts || [];
var scoreMeta     = PAYLOAD.score_metadata || {{}};
var solarLayer    = PAYLOAD.solar_layer   || [];
var stormLayer    = PAYLOAD.storm_layer   || [];
var lightningLayer = PAYLOAD.lightning_layer || [];

(function() {{
  var hc = PAYLOAD.heatmap_confidence || {{}};
  var vis = PAYLOAD.heatmap_confidence_visual || {{}};
  var el = document.getElementById('heatmap-confidence-banner');
  if (!el) return;
  var lvl = hc.level || 'ok';
  var row = vis[lvl] || {{}};
  var label = row.badge_label_sv || '';
  if (hc.level === 'unreliable' || hc.level === 'low') {{
    var reasons = (hc.reasons || []).join(', ');
    var bg = hc.level === 'unreliable' ? 'rgba(192,57,43,0.92)' : 'rgba(230,126,34,0.92)';
    el.innerHTML = '<div style="background:' + bg + ';color:#fff;padding:8px 14px;border-radius:6px;font-size:12px;max-width:520px;margin:0 auto 6px auto;box-shadow:0 2px 6px rgba(0,0,0,0.35);">'
      + '<strong>' + (label || hc.level) + '</strong>'
      + (reasons ? (' — ' + reasons) : '')
      + '</div>';
    el.style.cssText = 'position:absolute;bottom:78px;left:50%;transform:translateX(-50%);z-index:1000;width:92%;max-width:520px;';
  }} else {{
    el.innerHTML = '';
  }}
  var bd = document.getElementById('heatmap-confidence-badge');
  if (bd) {{
    bd.style.display = 'block';
    bd.className = '';
    bd.classList.add(lvl);
    bd.textContent = label || ('Heatmap: ' + lvl);
  }}
}})();

(function() {{
  var nr = PAYLOAD.normalization_readiness || {{}};
  var bad = nr.unusable_parameters || [];
  if (bad.length) {{
    console.warn('[Heatmap] normalization unusable parameters:', bad.join(', '));
  }}
}})();

// ── Map init ─────────────────────────────────────────────────────────────
var map = L.map('map');
{map_init_js}
(function() {{
  var mt = PAYLOAD.map_tile || {{}};
  if (!mt.url_template) {{
    console.error('[Map] PAYLOAD.map_tile.url_template missing — check map_tile_provider in DB');
  }} else {{
    var opts = {{ attribution: mt.attribution_html || '' }};
    if (mt.subdomains) {{ opts.subdomains = mt.subdomains; }}
    if (typeof mt.min_zoom === 'number') {{ opts.minZoom = mt.min_zoom; }}
    if (typeof mt.max_zoom === 'number') {{ opts.maxZoom = mt.max_zoom; }}
    L.tileLayer(mt.url_template, opts).addTo(map);
  }}
}})();
L.control.zoom({{ position: 'topright' }}).addTo(map);
map.scrollWheelZoom.enable();

// ── Layer groups ─────────────────────────────────────────────────────────
var markerGroup    = L.layerGroup().addTo(map);
var sensorGroup    = L.layerGroup().addTo(map);
var solarGroup     = L.layerGroup();
var stormGroup     = L.layerGroup();
var lightningGroup = L.layerGroup();
var heatLayer      = null;
var solarHeatLayer = null;
var stormHeatLayer = null;
var layerState     = {{ markers: true, heatmap: true, sensors: true, solar: false, storm: false, lightning: false }};

// ── Sparkline SVG helper ─────────────────────────────────────────────────
function buildSparkline(trend) {{
  if (!trend || trend.length < 2) return '<em style="font-size:11px;color:#aaa;">Trend ej tillgänglig</em>';
  var vals = trend.map(function(p) {{ return p.pm25; }}).filter(function(v) {{ return v != null; }});
  if (vals.length < 2) return '<em style="font-size:11px;color:#aaa;">Otillräcklig data</em>';
  var W = 180, H = 40, pad = 4;
  var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
  var rng = mx - mn || 1;
  var pts = vals.map(function(v, i) {{
    var x = pad + (i / (vals.length - 1)) * (W - 2 * pad);
    var y = H - pad - ((v - mn) / rng) * (H - 2 * pad);
    return x.toFixed(1) + ',' + y.toFixed(1);
  }}).join(' ');
  return '<svg width="' + W + '" height="' + H + '" style="display:block">' +
    '<polyline points="' + pts + '" fill="none" stroke="#3a7bd5" stroke-width="1.5"/>' +
    '<text x="2" y="' + (H - 2) + '" font-size="9" fill="#999">' + mn.toFixed(1) + '</text>' +
    '<text x="2" y="10" font-size="9" fill="#999">' + mx.toFixed(1) + '</text>' +
    '</svg>';
}}

// ── Inversion gauge helper ────────────────────────────────────────────────
function buildInvGauge(score, meta) {{
  if (score === null || score === undefined) {{
    var reason = meta.bounds_available
      ? 'Otillräcklig variationsbredd i historiken'
      : 'Historik &lt; 20 rader — kalibrering pågår';
    return '<div class="meta-note">Inversionspoäng: ' + reason + '</div>';
  }}
  var pct   = Math.round(score);
  var color = pct >= 70 ? '#c0392b' : pct >= 40 ? '#e67e22' : '#27ae60';
  var wb    = meta.wind_bounds     && meta.wind_bounds[0]     !== null;
  var hb    = meta.humidity_bounds && meta.humidity_bounds[0] !== null;
  var wStr  = wb ? meta.wind_bounds[0].toFixed(1) + '–' + meta.wind_bounds[1].toFixed(1) + ' m/s' : '?';
  var hStr  = hb ? meta.humidity_bounds[0].toFixed(0) + '–' + meta.humidity_bounds[1].toFixed(0) + '%' : '?';
  var rows  = meta.data_rows_used || 0;
  var pRange= (meta.percentile_range || [5,95]).join('–');
  return '<div class="inv-bar-wrap">' +
    '<div style="font-size:11px;margin-bottom:3px;">Inversionsrisk: <strong>' + pct + '/100</strong></div>' +
    '<div class="inv-bar-bg"><div class="inv-bar-fill" style="width:' + pct + '%;background:' + color + '"></div></div>' +
    '<div class="meta-note">Kalibrerad mot ' + rows + ' mätningar (p' + pRange + ')<br>' +
    'Vind: ' + wStr + ' · Fuktighet: ' + hStr + '</div>' +
    '</div>';
}}

// ── City markers layer ────────────────────────────────────────────────────
cities.forEach(function(city) {{
  var lat = city.latitude, lon = city.longitude;
  if (lat == null || lon == null) return;

  var color   = city.aqi_color   || '#cccccc';
  var pm25    = city.pm25_24h;
  var ws      = city.wind_speed;

  // Wind-speed ring radius: scale between 6 and 22px from wind_speed
  var ringR = 8;
  if (ws != null && scoreMeta.wind_bounds && scoreMeta.wind_bounds[1] != null) {{
    var wsMax = scoreMeta.wind_bounds[1];
    ringR = wsMax > 0 ? 6 + Math.round((ws / wsMax) * 16) : 8;
    ringR = Math.max(6, Math.min(22, ringR));
  }}

  // Outer wind-speed ring (grey, proportional)
  L.circleMarker([lat, lon], {{
    radius:      ringR,
    color:       '#888',
    weight:      1,
    fillColor:   '#888',
    fillOpacity: 0.08,
    interactive: false,
  }}).addTo(markerGroup);

  // Inner AQI-colour station dot
  var dot = L.circleMarker([lat, lon], {{
    radius:      7,
    color:       '#fff',
    weight:      1.5,
    fillColor:   color,
    fillOpacity: 0.9,
  }}).addTo(markerGroup);

  // ── Analytical popup ────────────────────────────────────────────────
  var sparkline = buildSparkline(city.trend_24h);
  var invGauge  = buildInvGauge(city.inversion_score, scoreMeta);

  var pm25Str  = pm25 != null
    ? pm25.toFixed(1) + ' µg/m³' + (city.pm25_source_label ? ' (källa: ' + city.pm25_source_label + ')' : '')
    : 'Ingen data';
  var tempStr  = city.temperature  != null ? city.temperature.toFixed(1)  + ' °C'    : '–';
  var humStr   = city.humidity     != null ? city.humidity.toFixed(0)     + '%'       : '–';
  var wsStr    = city.wind_speed   != null ? city.wind_speed.toFixed(1)   + ' m/s'   : '–';
  var no2Str   = city.no2          != null ? city.no2.toFixed(1)          + ' µg/m³' : '–';
  var o3Str    = city.o3           != null ? city.o3.toFixed(1)           + ' µg/m³' : '–';

  var densityNote = city.low_density
    ? '<div class="low-density-note">⚠ Gles stationstäckning — heatmap-interpolation osäker</div>'
    : '';

  var popupHtml =
    '<div class="popup-title">' + city.city_name + '</div>' +
    '<span class="aqi-badge" style="background:' + color + '">' + city.aqi_level_name + '</span><br>' +
    '<b>PM2.5 (24h):</b> ' + pm25Str + '<br>' +
    '<b>Temp:</b> ' + tempStr + ' &nbsp; <b>Fukt:</b> ' + humStr + ' &nbsp; <b>Vind (medel):</b> ' + wsStr + '<br>' +
    '<b>NO₂:</b> ' + no2Str + ' &nbsp; <b>O₃:</b> ' + o3Str + '<br>' +
    '<div class="sparkline-wrap">' + sparkline + '</div>' +
    invGauge +
    densityNote +
    '<div style="margin-top:4px"><a href="https://www.google.com/maps?q=' + lat + ',' + lon +
    '" target="_blank" style="font-size:11px">Öppna i Google Maps</a></div>';

  dot.bindPopup(popupHtml, {{ maxWidth: 240 }});
}});

// ── Heatmap raster overlay ────────────────────────────────────────────────
// The IDW grid (computed in Python) is rendered pixel-by-pixel on an
// offscreen canvas, bilinearly upscaled for smoothness, then attached to
// the map as L.imageOverlay.  This avoids the LED-dot artefact that
// L.heatLayer produces when fed a pre-interpolated grid.
//
// heatMax:     Python p95 anchor — outlier-robust colour scale.
// heatTrueMax: actual grid maximum — used only by the scale-clamp indicator.
var heatMax     = PAYLOAD.idw_max      || 1.0;
var heatTrueMax = PAYLOAD.idw_true_max || heatMax;
var idwScalePct = PAYLOAD.idw_scale_percentile || 95;
console.log("[Heatmap] idw_grid:", (PAYLOAD.idw_grid || []).length, "cells  heatMax:", heatMax, "heatTrueMax:", heatTrueMax);

// ── Scale-clamp indicator ─────────────────────────────────────────────────
// Shown only when the colour scale is clamped below the true grid maximum.
// Informs the user that red is not the absolute max during extreme events.
(function() {{
  if (heatTrueMax <= heatMax) return;
  var el = document.getElementById('scale-clamp-note');
  if (!el) return;
  el.style.display = 'block';
  el.innerHTML =
    '&#9888; Skalan visar upp till <strong>' + heatMax.toFixed(1) + '\u00a0\u00b5g/m\u00b3</strong>' +
    ' (p' + idwScalePct + ') &mdash; faktiskt\u00a0max: <strong>' +
    heatTrueMax.toFixed(1) + '\u00a0\u00b5g/m\u00b3</strong>';
}})();

window.addEventListener("resize", function() {{
  map.invalidateSize();
}});

var __heatAttachState = {{ done: false, timer: null, ro: null }};

function attachHeatOverlayOnce() {{
  if (__heatAttachState.done) return;
  map.invalidateSize();
  var size = map.getSize();

  var grid = PAYLOAD.idw_grid;
  var meta = PAYLOAD.idw_meta;
  if (!grid || !grid.length || !meta) {{
    console.error("[Heatmap] idw_grid or idw_meta missing — overlay skipped");
    __heatAttachState.done = true;
    return;
  }}

  var baseHeatOpacity = {opacity_float};
  var hcLvl = (PAYLOAD.heatmap_confidence || {{}}).level || 'ok';
  var visRow = (PAYLOAD.heatmap_confidence_visual || {{}})[hcLvl] || {{}};
  var opacityMult = (typeof visRow.opacity_multiplier === 'number') ? visRow.opacity_multiplier : null;
  if (opacityMult === null) {{
    console.error("[Heatmap] heatmap_confidence_visual missing opacity_multiplier for level", hcLvl);
    opacityMult = 1.0;
  }}
  var heatOpacityEffective = Math.max(0, Math.min(1, baseHeatOpacity * opacityMult));

  // ── AQI colour gradient stops (same palette as before) ──────────────────
  var stops = [
    {{ t:0.0,  r:0,   g:228, b:0   }},
    {{ t:0.25, r:255, g:255, b:0   }},
    {{ t:0.5,  r:255, g:126, b:0   }},
    {{ t:0.75, r:255, g:0,   b:0   }},
    {{ t:1.0,  r:126, g:0,   b:35  }}
  ];

  // DB-driven value domain / clipping for colour mapping
  var hcfg = PAYLOAD.heatmap_config || {{}};
  var clipMin = (typeof hcfg.clip_min === 'number') ? hcfg.clip_min : 0.0;
  var clipMax = (typeof hcfg.clip_max === 'number') ? hcfg.clip_max : heatMax;
  if (clipMax <= clipMin) clipMax = clipMin + 1.0;
  
  function valToRGB(val) {{
    // Normalize using DB-driven clip bounds
    var t = Math.max(0, Math.min(1, (val - clipMin) / (clipMax - clipMin)));
    for (var i = 1; i < stops.length; i++) {{
      if (t <= stops[i].t) {{
        var s0 = stops[i-1], s1 = stops[i];
        var f = (t - s0.t) / (s1.t - s0.t);
        return [
          Math.round(s0.r + f*(s1.r-s0.r)),
          Math.round(s0.g + f*(s1.g-s0.g)),
          Math.round(s0.b + f*(s1.b-s0.b))
        ];
      }}
    }}
    var l = stops[stops.length-1]; return [l.r, l.g, l.b];
  }}

  // ── Offscreen canvas: one pixel per IDW grid cell ────────────────────────
  var n   = meta.grid_n;
  var raw = document.createElement('canvas');
  raw.width  = n;
  raw.height = n;
  var ctx = raw.getContext('2d');
  var img = ctx.createImageData(n, n);
  var alpha = Math.round(heatOpacityEffective * 255);

  for (var k = 0; k < grid.length; k++) {{
    var pt  = grid[k];
    var col = Math.round((pt[1] - meta.lon_min) / meta.lon_step);
    var row = Math.round((pt[0] - meta.lat_min) / meta.lat_step);
    // Canvas Y=0 is at the top (north), so invert the row
    var py  = (n - 1) - row;
    var px  = col;
    if (px < 0 || px >= n || py < 0 || py >= n) continue;
    var idx = (py * n + px) * 4;
    var rgb = valToRGB(pt[2]);
    img.data[idx]     = rgb[0];
    img.data[idx + 1] = rgb[1];
    img.data[idx + 2] = rgb[2];
    img.data[idx + 3] = alpha;
  }}
  ctx.putImageData(img, 0, 0);

  // ── Upscale with bilinear smoothing to reduce pixelation ────────────────
  // Target ~480px on the shorter side; derived from grid_n so it adapts
  // automatically as grid density scales with station count.
  var overlayScale = Math.max(1, Math.ceil(480 / n));
  var big    = document.createElement('canvas');
  big.width  = n * overlayScale;
  big.height = n * overlayScale;
  var bigCtx = big.getContext('2d');
  bigCtx.imageSmoothingEnabled = true;
  bigCtx.imageSmoothingQuality = 'high';
  bigCtx.drawImage(raw, 0, 0, big.width, big.height);

  var dataURL = big.toDataURL('image/png');
  var bounds  = [[meta.lat_min, meta.lon_min], [meta.lat_max, meta.lon_max]];
  heatLayer   = L.imageOverlay(dataURL, bounds, {{ opacity: heatOpacityEffective, interactive: false }});
  heatLayer.addTo(map);
  __heatAttachState.done = true;
  console.log("[Heatmap] imageOverlay created. size:", size.x, "x", size.y,
              "canvas:", big.width, "x", big.height, "heatMax:", heatMax,
              "opacityEffective:", heatOpacityEffective);
}}

function beginHeatmapAttachWhenSized() {{
  var timeoutMs = PAYLOAD.map_init_timeout_ms;
  if (typeof timeoutMs !== 'number' || timeoutMs <= 0 || !isFinite(timeoutMs)) {{
    console.error("[Heatmap] map_init_timeout_ms missing or invalid — check calibration_parameters (map_init_size_ready_timeout_ms)");
    return;
  }}
  var mapDiv = map.getContainer();

  function tryAttach() {{
    map.invalidateSize();
    var s = map.getSize();
    if (s.x > 0 && s.y > 0) {{
      if (__heatAttachState.timer) clearTimeout(__heatAttachState.timer);
      if (__heatAttachState.ro) {{
        __heatAttachState.ro.disconnect();
        __heatAttachState.ro = null;
      }}
      attachHeatOverlayOnce();
      return true;
    }}
    return false;
  }}

  if (tryAttach()) return;

  if (typeof ResizeObserver !== "undefined") {{
    __heatAttachState.ro = new ResizeObserver(function() {{ tryAttach(); }});
    __heatAttachState.ro.observe(mapDiv);
  }} else {{
    console.error("[Heatmap] ResizeObserver unavailable — cannot satisfy size-ready contract");
  }}

  __heatAttachState.timer = setTimeout(function() {{
    if (__heatAttachState.done) return;
    var s = map.getSize();
    console.error("[Heatmap] MAP_INIT_TIMEOUT: map container size remained " + s.x + "x" + s.y +
      " after " + timeoutMs + "ms (DB map_init_size_ready_timeout_ms) — heat overlay not attached");
    if (__heatAttachState.ro) {{
      __heatAttachState.ro.disconnect();
      __heatAttachState.ro = null;
    }}
  }}, timeoutMs);
}}

function initHeatOverlay() {{ beginHeatmapAttachWhenSized(); }}
// beginHeatmapAttachWhenSized() is invoked from Python via runJavaScript after loadFinished(True).

// ── Sensor marker layer ───────────────────────────────────────────────────
sensors.forEach(function(s) {{
  var lat = s.latitude, lon = s.longitude;
  if (lat == null || lon == null) return;

  var marker = L.marker([lat, lon]).addTo(sensorGroup);
  var content = '';

  if (s.is_custom == 1) {{
    var ci = s.custom_info ? JSON.parse(s.custom_info) : {{}};
    content += '<b>' + (ci.name || 'Custom Marker') + '</b><br>';
    if (ci.description) content += ci.description + '<br>';
    if (ci.value != null) content += 'Värde: ' + ci.value + ' µg/m³<br>';
  }} else {{
    content += '<b>Sensor ID:</b> '  + (s.sensor_id           || 'Okänd') + '<br>';
    content += '<b>Parameter:</b> '  + (s.formatted_parameter || 'Okänd') + '<br>';
    if (s.last_value   != null) content += '<b>Värde:</b> '     + s.last_value             + ' µg/m³<br>';
    if (s.formatted_timestamp && s.formatted_timestamp !== 'Okänd')
      content += '<b>Uppdaterad:</b> ' + s.formatted_timestamp + '<br>';
    if (s.city_name) content += '<b>Stad:</b> ' + s.city_name + '<br>';
  }}
  content += '<a href="https://www.google.com/maps?q=' + lat + ',' + lon +
             '" target="_blank">Öppna i Google Maps</a>';
  marker.bindPopup(content);
}});

// ── Cluster alert banner ──────────────────────────────────────────────────
(function() {{
  var banner = document.getElementById('cluster-banner');
  clusterAlerts.forEach(function(a) {{
    var div = document.createElement('div');
    div.className = 'cluster-alert';
    div.innerHTML =
      '⚠ Regional påverkan: <strong>' + a.region.charAt(0).toUpperCase() + a.region.slice(1) +
      'ra Sverige</strong> — PM2.5 snitt ' + a.region_mean.toFixed(1) +
      ' µg/m³ (+' + a.deviation_pct + '% mot nationellt 7d-snitt ' +
      a.national_baseline.toFixed(1) + ' µg/m³, ' + a.city_count + ' stationer)';
    banner.appendChild(div);
  }});
}})();

// ── Solar layer rendering ─────────────────────────────────────────────────
function initSolarLayer() {{
  // Use Python-computed IDW grid instead of point-based interpolation
  var grid = PAYLOAD.solar_idw_grid;
  var meta = PAYLOAD.solar_idw_meta;
  if (!grid || !grid.length || !meta) return;
  
  // Use percentile-based scaling (p5-p95)
  var solar_p5 = PAYLOAD.solar_p5;
  var solar_p95 = PAYLOAD.solar_p95;
  if (solar_p5 === null || solar_p95 === null || solar_p5 === solar_p95) return;
  
  var scale_range = solar_p95 - solar_p5;
  
  // Yellow to orange gradient stops
  var stops = [
    {{ t:0.0,  r:255, g:255, b:0   }},
    {{ t:0.5,  r:255, g:200, b:0   }},
    {{ t:1.0,  r:255, g:100, b:0   }}
  ];
  
  function valToRGB(val) {{
    // Normalize using percentile bounds
    var t = Math.max(0, Math.min(1, (val - solar_p5) / scale_range));
    for (var i = 1; i < stops.length; i++) {{
      if (t <= stops[i].t) {{
        var s0 = stops[i-1], s1 = stops[i];
        var f = (t - s0.t) / (s1.t - s0.t);
        return [
          Math.round(s0.r + f*(s1.r-s0.r)),
          Math.round(s0.g + f*(s1.g-s0.g)),
          Math.round(s0.b + f*(s1.b-s0.b))
        ];
      }}
    }}
    var l = stops[stops.length-1]; return [l.r, l.g, l.b];
  }}
  
  // Render grid directly (same approach as PM2.5 heatmap)
  var n = meta.grid_n;
  var raw = document.createElement('canvas');
  raw.width = n;
  raw.height = n;
  var ctx = raw.getContext('2d');
  var img = ctx.createImageData(n, n);
  var alpha = Math.round(0.7 * 255);
  
  for (var k = 0; k < grid.length; k++) {{
    var pt = grid[k];
    var col = Math.round((pt[1] - meta.lon_min) / meta.lon_step);
    var row = Math.round((pt[0] - meta.lat_min) / meta.lat_step);
    var py = (n - 1) - row;  // Canvas Y = 0 at north
    var px = col;
    if (px < 0 || px >= n || py < 0 || py >= n) continue;
    var idx = (py * n + px) * 4;
    var rgb = valToRGB(pt[2]);
    img.data[idx] = rgb[0];
    img.data[idx + 1] = rgb[1];
    img.data[idx + 2] = rgb[2];
    img.data[idx + 3] = alpha;
  }}
  ctx.putImageData(img, 0, 0);
  
  // Upscale with high-quality smoothing
  var overlayScale = Math.max(1, Math.ceil(480 / n));
  var big = document.createElement('canvas');
  big.width = n * overlayScale;
  big.height = n * overlayScale;
  var bigCtx = big.getContext('2d');
  bigCtx.imageSmoothingEnabled = true;
  bigCtx.imageSmoothingQuality = 'high';
  bigCtx.drawImage(raw, 0, 0, big.width, big.height);
  
  var dataURL = big.toDataURL('image/png');
  var bounds = [[meta.lat_min, meta.lon_min], [meta.lat_max, meta.lon_max]];
  solarHeatLayer = L.imageOverlay(dataURL, bounds, {{ opacity: 0.7, interactive: false }});
  if (layerState.solar) solarHeatLayer.addTo(map);
}}

// ── Storm layer rendering ─────────────────────────────────────────────────
function initStormLayer() {{
  // Only render if storm layer is active (thresholds met)
  if (!PAYLOAD.storm_layer_active) {{
    console.log("[Storm Layer] Thresholds not met, skipping storm layer rendering");
    return;  // Don't render storm colors
  }}
  
  // Use Python-computed IDW grid instead of JS interpolation
  var grid = PAYLOAD.storm_idw_grid;
  var meta = PAYLOAD.storm_idw_meta;
  if (!grid || !grid.length || !meta) return;
  
  // Use percentile-based scaling (p5-p95)
  var storm_p5 = PAYLOAD.storm_p5;
  var storm_p95 = PAYLOAD.storm_p95;
  if (storm_p5 === null || storm_p95 === null || storm_p5 === storm_p95) return;
  
  var scale_range = storm_p95 - storm_p5;
  
  // Purple to red gradient stops
  var stops = [
    {{ t:0.0,  r:150, g:0,   b:255 }},
    {{ t:0.5,  r:200, g:0,   b:150 }},
    {{ t:1.0,  r:255, g:0,   b:0   }}
  ];
  
  function valToRGB(val) {{
    // Normalize using percentile bounds
    var t = Math.max(0, Math.min(1, (val - storm_p5) / scale_range));
    for (var i = 1; i < stops.length; i++) {{
      if (t <= stops[i].t) {{
        var s0 = stops[i-1], s1 = stops[i];
        var f = (t - s0.t) / (s1.t - s0.t);
        return [
          Math.round(s0.r + f*(s1.r-s0.r)),
          Math.round(s0.g + f*(s1.g-s0.g)),
          Math.round(s0.b + f*(s1.b-s0.b))
        ];
      }}
    }}
    var l = stops[stops.length-1]; return [l.r, l.g, l.b];
  }}
  
  // Render grid directly (same approach as PM2.5 heatmap)
  var n = meta.grid_n;
  var raw = document.createElement('canvas');
  raw.width = n;
  raw.height = n;
  var ctx = raw.getContext('2d');
  var img = ctx.createImageData(n, n);
  var alpha = Math.round(0.7 * 255);
  
  for (var k = 0; k < grid.length; k++) {{
    var pt = grid[k];
    var col = Math.round((pt[1] - meta.lon_min) / meta.lon_step);
    var row = Math.round((pt[0] - meta.lat_min) / meta.lat_step);
    var py = (n - 1) - row;  // Canvas Y = 0 at north
    var px = col;
    if (px < 0 || px >= n || py < 0 || py >= n) continue;
    var idx = (py * n + px) * 4;
    var rgb = valToRGB(pt[2]);
    img.data[idx] = rgb[0];
    img.data[idx + 1] = rgb[1];
    img.data[idx + 2] = rgb[2];
    img.data[idx + 3] = alpha;
  }}
  ctx.putImageData(img, 0, 0);
  
  // Upscale with high-quality smoothing
  var overlayScale = Math.max(1, Math.ceil(480 / n));
  var big = document.createElement('canvas');
  big.width = n * overlayScale;
  big.height = n * overlayScale;
  var bigCtx = big.getContext('2d');
  bigCtx.imageSmoothingEnabled = true;
  bigCtx.imageSmoothingQuality = 'high';
  bigCtx.drawImage(raw, 0, 0, big.width, big.height);
  
  var dataURL = big.toDataURL('image/png');
  var bounds = [[meta.lat_min, meta.lon_min], [meta.lat_max, meta.lon_max]];
  stormHeatLayer = L.imageOverlay(dataURL, bounds, {{ opacity: 0.7, interactive: false }});
  if (layerState.storm) stormHeatLayer.addTo(map);
}}

// ── Lightning markers (using canvas for performance) ──────────────────────
lightningLayer.forEach(function(strike) {{
  var lat = strike.lat, lon = strike.lon;
  if (lat == null || lon == null) return;
  
  // Use canvas marker (L.circleMarker) for better performance
  // If PNG data URL is available, use it; otherwise use simple circle
  var marker;
  if (`{lightning_icon_data_url}` && `{lightning_icon_data_url}`.length > 0) {{
    // Use PNG icon if available
    var icon = L.icon({{
      iconUrl: `{lightning_icon_data_url}`,
      iconSize: [24, 24],
      iconAnchor: [12, 12]
    }});
    marker = L.marker([lat, lon], {{ icon: icon }}).addTo(lightningGroup);
  }} else {{
    // Fallback to canvas circle marker (faster than SVG)
    marker = L.circleMarker([lat, lon], {{
      radius: 8,
      fillColor: '#FFD700',
      color: '#000',
      weight: 1,
      opacity: 1,
      fillOpacity: 0.8
    }}).addTo(lightningGroup);
  }}
  
  var popup = 'Blixtnedslag<br>';
  if (strike.timestamp) popup += 'Tid: ' + strike.timestamp + '<br>';
  if (strike.intensity != null) popup += 'Intensitet: ' + strike.intensity.toFixed(1) + '<br>';
  marker.bindPopup(popup);
}});

// Initialize solar and storm layers after map is ready
setTimeout(function() {{
  initSolarLayer();
  initStormLayer();
}}, 1000);

// Placeholder for future DB-driven PM2.5 contour overlay (no-op for now).
// The enable flag and levels are already DB-driven via PAYLOAD.heatmap_config.
function initPm25Contours() {{
  var hcfg = PAYLOAD.heatmap_config || {{}};
  if (!hcfg.contours_enabled) return;
  var levels = hcfg.contours_levels || [];
  if (!levels.length) return;
  // Contour computation and rendering will be added in a future iteration.
}}

// ── Layer toggle logic ────────────────────────────────────────────────────
function toggleLayer(name) {{
  layerState[name] = !layerState[name];
  var btn = document.getElementById('btn-' + name);
  if (layerState[name]) {{
    btn.classList.add('active');
    if (name === 'markers') map.addLayer(markerGroup);
    if (name === 'sensors') map.addLayer(sensorGroup);
    if (name === 'heatmap' && heatLayer) map.addLayer(heatLayer);
    if (name === 'solar' && solarHeatLayer) map.addLayer(solarHeatLayer);
    if (name === 'storm' && stormHeatLayer) map.addLayer(stormHeatLayer);
    if (name === 'lightning') map.addLayer(lightningGroup);
  }} else {{
    btn.classList.remove('active');
    if (name === 'markers') map.removeLayer(markerGroup);
    if (name === 'sensors') map.removeLayer(sensorGroup);
    if (name === 'heatmap' && heatLayer) map.removeLayer(heatLayer);
    if (name === 'solar' && solarHeatLayer) map.removeLayer(solarHeatLayer);
    if (name === 'storm' && stormHeatLayer) map.removeLayer(stormHeatLayer);
    if (name === 'lightning') map.removeLayer(lightningGroup);
  }}
}}

// ── Right-click context menu (custom marker placement) ───────────────────
map.on('contextmenu', function(e) {{
  window.mapRightClickLat = e.latlng.lat;
  window.mapRightClickLon = e.latlng.lng;
  document.title = 'MAP_RIGHT_CLICK:' + e.latlng.lat + ',' + e.latlng.lng;
}});
</script>
</body>
</html>"""
        return html

    # ------------------------------------------------------------------
    # Right-click → custom marker
    # ------------------------------------------------------------------

    def _on_title_changed(self, title: str):
        if title.startswith("MAP_RIGHT_CLICK:"):
            try:
                coords_str = title.replace("MAP_RIGHT_CLICK:", "")
                lat_str, lon_str = coords_str.split(",")
                lat = float(lat_str)
                lon = float(lon_str)
                self._on_map_right_click(lat, lon)
                self.map_view.page().runJavaScript("document.title = 'Stations Map';")
            except (ValueError, IndexError) as e:
                logger.warning(f"Fel vid parsing av right-click koordinater: {e}")

    def _on_map_right_click(self, lat: float, lon: float):
        dialog = CustomMarkerDialog(self, lat, lon)
        if dialog.exec_() == QDialog.Accepted:
            marker_data = dialog.get_marker_data()

            cities    = self.controller.get_all_cities()
            nearest   = None
            min_dist  = float("inf")

            for city in cities:
                dist = ((lat - city["latitude"]) ** 2 + (lon - city["longitude"]) ** 2) ** 0.5
                if dist < min_dist:
                    min_dist = dist
                    nearest  = city

            if nearest and min_dist < 0.5:
                city_id = nearest["id"]
            else:
                if cities:
                    city_id = cities[0]["id"]
                else:
                    QMessageBox.warning(self, "Fel", "Inga städer hittades. Lägg till en stad först.")
                    return

            custom_info = json.dumps({
                "name":        marker_data["name"],
                "description": marker_data["description"],
                "value":       marker_data["value"],
            })

            try:
                self.controller.db.add_custom_marker(
                    city_id=city_id,
                    latitude=lat,
                    longitude=lon,
                    custom_info=custom_info,
                )
                logger.info(f"Custom marker tillagd för stad {city_id}")
                QMessageBox.information(self, "Klart", "Custom marker tillagd!")
                self._refresh_map()
            except Exception as e:
                logger.error(f"Fel vid tillägg av custom marker: {e}")
                QMessageBox.warning(self, "Fel", f"Kunde inte lägga till marker: {e}")
