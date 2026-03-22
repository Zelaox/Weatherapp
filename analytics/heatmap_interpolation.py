"""
DB-driven PM2.5 heatmap IDW grid, spatial index selection, interpolation registry,
and per-cell confidence aggregation (see docs/ANALYTICAL_MAP.md).
"""

from __future__ import annotations

import json
import logging
import math
import random
import statistics
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from analytics.normalization_engine import NormalizationEngine
from utils.heatmap_json_validation import (
    validate_global_score_clip,
    validate_method_selection_rules,
    validate_spatial_index_rules,
)

logger = logging.getLogger("WeatherApp.analytics.heatmap_interpolation")

R_EARTH_KM = 6371.0


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = lat2_rad - lat1_rad
    dlon = math.radians(lon2 - lon1)
    x = dlon * math.cos((lat1_rad + lat2_rad) * 0.5)
    y = dlat
    return R_EARTH_KM * math.sqrt(x * x + y * y)


def _cell_area_km2(lat: float, lat_step_deg: float, lon_step_deg: float, method: str) -> float:
    if method == "planar_approx":
        dy = abs(lat_step_deg) * 111.0
        dx = abs(lon_step_deg) * 111.0 * max(math.cos(math.radians(lat)), 1e-6)
        return max(dy * dx, 1e-9)
    # haversine: approximate rectangle area at latitude
    dy = abs(lat_step_deg) * (math.pi / 180.0) * R_EARTH_KM
    dx = abs(lon_step_deg) * (math.pi / 180.0) * R_EARTH_KM * max(math.cos(math.radians(lat)), 1e-6)
    return max(dy * dx, 1e-9)


def apply_float_precision(x: float, mode: str) -> float:
    if mode == "rounded_6dp":
        return round(float(x), 6)
    return float(x)


def _when_matches(when: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    if not when:
        return True
    for k, v in when.items():
        if ctx.get(k) != v:
            return False
    return True


def evaluate_rules_json(
    doc: Dict[str, Any],
    context: Dict[str, Any],
    *,
    tie_key: str = "rule_priority",
) -> Dict[str, Any]:
    """
    first_match_wins top_down: sort by rule_priority using priority_order asc|desc.
    Same-priority multiple match -> RuntimeError.
    """
    first_match = doc.get("first_match_wins", True)
    if not first_match:
        raise RuntimeError("first_match_wins=false requires merge semantics (not implemented)")
    order = doc.get("priority_order", "asc")
    rules = list(doc.get("rules") or [])
    reverse = order == "desc"
    rules.sort(key=lambda r: int(r.get(tie_key, 0)), reverse=reverse)
    matched_rule: Optional[Dict[str, Any]] = None
    for r in rules:
        if _when_matches(dict(r.get("when") or {}), context):
            matched_rule = r
            break
    if matched_rule is None:
        raise RuntimeError("no matching rule in rules document")
    pri = int(matched_rule.get(tie_key, 0))
    conflicts = [
        r
        for r in rules
        if int(r.get(tie_key, 0)) == pri and _when_matches(dict(r.get("when") or {}), context)
    ]
    if len(conflicts) > 1:
        raise RuntimeError(f"ambiguous rule match at priority {pri}: {len(conflicts)} rules")
    return dict(matched_rule["then"])


def _kd_tree_available() -> bool:
    try:
        from scipy.spatial import cKDTree  # noqa: F401

        return True
    except Exception:
        return False


def resolve_spatial_index_mode(
    cfg_row: Dict[str, Any],
    *,
    n_stations: int,
    grid_cells: int,
) -> str:
    raw = cfg_row.get("spatial_index_mode") or "brute_force"
    rules_txt = cfg_row.get("spatial_index_rules")
    if not rules_txt:
        return str(raw)
    doc = validate_spatial_index_rules(rules_txt)
    ctx = {
        "n_stations": int(n_stations),
        "grid_cells": int(grid_cells),
        "kd_tree_available": _kd_tree_available(),
        "spatial_index_mode": str(raw),
    }
    then = evaluate_rules_json(doc, ctx)
    mode = str(then.get("mode", "brute_force"))
    if mode == "kd_tree" and not _kd_tree_available():
        raise RuntimeError("spatial_index_rules selected kd_tree but scipy.spatial.cKDTree is not available")
    if mode == "grid_bucket":
        raise RuntimeError("grid_bucket spatial index is not implemented (fail loud)")
    return mode


def resolve_interpolation_method(cfg_row: Dict[str, Any]) -> str:
    rules_txt = cfg_row.get("method_selection_rules")
    if not rules_txt:
        return str(cfg_row.get("interpolation_method") or "idw")
    doc = validate_method_selection_rules(rules_txt)
    ctx: Dict[str, Any] = {}
    then = evaluate_rules_json(doc, ctx)
    return str(then.get("method", "idw"))


class InterpolationMethodRegistry:
    """method_name -> callable (IDW implemented; kriging fails loud)."""

    def __init__(self) -> None:
        self._methods: Dict[str, Callable[..., float]] = {}

    def register(self, name: str, fn: Callable[..., float]) -> None:
        self._methods[name] = fn

    def get(self, name: str) -> Callable[..., float]:
        if name == "kriging":
            raise RuntimeError("interpolation method 'kriging' is not implemented")
        if name not in self._methods:
            raise RuntimeError(f"unknown interpolation method: {name!r}")
        return self._methods[name]


# Registry instance for future IDW/nearest callables (PM2.5 path uses explicit IDW in compute_pm25_heatmap).
interpolation_registry = InterpolationMethodRegistry()


def _idw_station_value(
    glat: float,
    glon: float,
    lats: Sequence[float],
    lons: Sequence[float],
    vals: Sequence[float],
    max_radius_km: float,
    idw_power: float,
    decay_type: int,
) -> Tuple[float, float, int, float, float]:
    """
    Returns (value, weight_den, used_points, wdist_num, wdist_den) for IDW cell.
    """
    num = den = 0.0
    used = 0
    wdist_num = wdist_den = 0.0
    for slat, slon, sval in zip(lats, lons, vals):
        d_km = _distance_km(glat, glon, slat, slon)
        if d_km < 1e-3:
            return float(sval), 1.0, 1, 0.0, 1.0
        if d_km <= max_radius_km:
            w = 1.0 / max(d_km ** idw_power, 1e-9)
            r_norm = d_km / max(max_radius_km, 1e-9)
            if decay_type == 1:
                decay = max(0.0, 1.0 - r_norm)
                w *= decay
            elif decay_type == 2:
                w *= math.exp(-(r_norm**2))
            num += w * sval
            den += w
            used += 1
            wdist_num += d_km * w
            wdist_den += w
    if den <= 0:
        return float("nan"), 0.0, 0, 0.0, 0.0
    return num / den, den, used, wdist_num, wdist_den


def _stations_within_radius(
    glat: float,
    glon: float,
    lats: Sequence[float],
    lons: Sequence[float],
    vals: Sequence[float],
    radius_km: float,
) -> List[Tuple[float, float, float, float]]:
    out: List[Tuple[float, float, float, float]] = []
    for slat, slon, sval in zip(lats, lons, vals):
        d = _distance_km(glat, glon, slat, slon)
        if d <= radius_km + 1e-9:
            out.append((slat, slon, float(sval), d))
    return out


def _adaptive_radius(
    glat: float,
    glon: float,
    lats: Sequence[float],
    lons: Sequence[float],
    vals: Sequence[float],
    *,
    r_min: float,
    r_max: float,
    r_step: float,
    min_points: int,
) -> float:
    r = r_min
    while r <= r_max + 1e-9:
        inside = _stations_within_radius(glat, glon, lats, lons, vals, r)
        if len(inside) >= min_points:
            return min(r, r_max)
        r += r_step
    return r_max


def _shrink_factor_from_spec(spec: Dict[str, Any], density: float) -> float:
    t = spec.get("type")
    if t == "lookup":
        pts = spec.get("points") or []
        if len(pts) < 2:
            raise RuntimeError("radius_shrink_spec lookup requires at least 2 points")
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x = float(density)
        if x <= xs[0]:
            return float(ys[0])
        if x >= xs[-1]:
            return float(ys[-1])
        for i in range(len(xs) - 1):
            if xs[i] <= x <= xs[i + 1]:
                tfrac = (x - xs[i]) / max(xs[i + 1] - xs[i], 1e-12)
                return float(ys[i] + tfrac * (ys[i + 1] - ys[i]))
        return float(ys[-1])
    if t == "formula":
        expr = str(spec.get("expr", "1.0"))
        params = dict(spec.get("params") or {})
        params["density"] = float(density)
        # Safe mini-eval: only allow log1p, + - * / ** ( ) numbers
        allowed = {"log1p": math.log1p, "abs": abs, "min": min, "max": max, "density": params["density"]}
        for k, v in params.items():
            allowed[k] = v
        try:
            return float(eval(expr, {"__builtins__": {}}, allowed))
        except Exception as e:
            raise RuntimeError(f"radius_shrink_spec formula eval failed: {e}") from e
    raise RuntimeError(f"unknown radius_shrink_spec type: {t!r}")


def _parse_ts_hours(ts: Any, now: datetime) -> Optional[float]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        s = str(ts)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(s[:19], fmt.replace(".%f", ""))
                break
            except ValueError:
                continue
        else:
            return None
    delta = now - dt.replace(tzinfo=None) if dt.tzinfo is None else now - dt.astimezone().replace(tzinfo=None)
    return max(0.0, delta.total_seconds() / 3600.0)


def _aggregate_scores(values: List[float], method: str) -> float:
    if not values:
        return 0.0
    if method == "mean":
        return float(sum(values) / len(values))
    if method in ("median", "p50"):
        return float(statistics.median(values))
    if method == "p75":
        s = sorted(values)
        n = len(s)
        idx = int(round(0.75 * (n - 1)))
        return float(s[idx])
    raise RuntimeError(f"unknown cell_score_aggregation_method: {method!r}")


def compute_pm25_heatmap(
    db: Any,
    heatmap_input_points: List[Dict[str, Any]],
    extent: Optional[Tuple[float, float, float, float]],
    calib: Dict[str, float],
    *,
    context_key: str = "pm25_heatmap",
    debug_mode: bool = False,
    now: Optional[datetime] = None,
) -> Tuple[List[List[float]], Dict[str, Any], Dict[str, Any]]:
    """
    heatmap_input_points: list of selected_pm25 dicts with lat, lon, value, source
    (raw_latest | aggregated_24h), optional city_id, measurement_ts, collector_ts.

    Returns:
      grid: sparse [lat, lon, value] rows
      meta: idw_meta (lat bounds, steps, grid_n, mean_interpolation_distance_km, ...)
      extra: heatmap_confidence, engine_config, heatmap_meta, cell_histogram, warning_codes
    """
    if not heatmap_input_points:
        return [], {}, {"heatmap_confidence": {}, "engine_config": {}, "heatmap_meta": {}, "warning_codes": []}

    cfg_row = db.get_heatmap_interpolation_config_row(context_key)
    if cfg_row is None or not int(cfg_row.get("enabled", 1)):
        raise RuntimeError(f"heatmap interpolation config missing or disabled: {context_key!r}")

    _priority, min_points_render, data_quality_weights = db.get_heatmap_dual_source_config(context_key)

    float_mode = str(cfg_row.get("float_precision_mode") or "raw")
    feat_rows = db.get_heatmap_confidence_features(context_key)
    agg_row = db.get_heatmap_confidence_aggregate_row(context_key)
    thr_row = db.get_heatmap_confidence_threshold_row(context_key)

    for p in heatmap_input_points:
        if not all(k in p for k in ("lat", "lon", "value", "source")):
            raise RuntimeError(f"heatmap_input_points entry missing required keys (lat,lon,value,source): {p!r}")

    lats = [float(p["lat"]) for p in heatmap_input_points]
    lons = [float(p["lon"]) for p in heatmap_input_points]
    vals = [float(p["value"]) for p in heatmap_input_points]
    point_sources = [str(p["source"]) for p in heatmap_input_points]
    n = len(heatmap_input_points)

    # Optional timestamps for temporal freshness (hours)
    now_dt = now or datetime.now()
    ts_basis = str(cfg_row.get("temporal_freshness_time_basis") or "measurement_time")
    station_hours: List[Optional[float]] = []
    for p in heatmap_input_points:
        raw_ts = p.get("measurement_ts") or p.get("measurement_timestamp")
        if ts_basis == "collector_time":
            raw_ts = p.get("collector_ts") or p.get("timestamp")
        station_hours.append(_parse_ts_hours(raw_ts, now_dt))

    if extent is not None:
        lat_min, lat_max, lon_min, lon_max = extent
    else:
        lat_min, lat_max = min(lats), max(lats)
        lon_min, lon_max = min(lons), max(lons)

    pad_f = float(cfg_row.get("bbox_padding_fraction") or 0.05)
    lat_pad = (lat_max - lat_min) * pad_f
    lon_pad = (lon_max - lon_min) * pad_f
    lat_min -= lat_pad
    lat_max += lat_pad
    lon_min -= lon_pad
    lon_max += lon_pad

    g_min = int(cfg_row.get("grid_resolution_min") or 80)
    g_max = int(cfg_row.get("grid_resolution_max") or 150)
    grid_n = max(g_min, min(g_max, int(math.sqrt(n) * 10)))

    base_power = float(calib.get("idw_power") or 2.3)
    heatmap_power = cfg_row.get("idw_power")
    idw_power = float(heatmap_power if heatmap_power is not None else calib.get("heatmap_idw_power", base_power))

    r_max_cfg = cfg_row.get("radius_max_km")
    if r_max_cfg is None:
        max_radius_km = calib.get("heatmap_max_influence_radius_km")
        if max_radius_km is None:
            diag_deg = math.sqrt((lat_max - lat_min) ** 2 + (lon_max - lon_min) ** 2)
            approx_km = diag_deg * 111.0
            max_radius_km = approx_km / max(math.sqrt(n), 1.0)
    else:
        max_radius_km = float(r_max_cfg)
    max_radius_km = max(1.0, float(max_radius_km))

    min_points = int(cfg_row.get("min_points") or calib.get("heatmap_idw_min_points") or 3)
    min_points = max(1, min_points)

    decay_type_raw = calib.get("heatmap_radial_decay_type", 1.0)
    try:
        decay_type = int(decay_type_raw)
    except (TypeError, ValueError):
        decay_type = 1

    adaptive = bool(int(cfg_row.get("adaptive_radius_enabled") or 0))
    r_min = float(cfg_row.get("radius_min_km") or 20.0)
    r_step = float(cfg_row.get("radius_step_km") or 15.0)
    r_cap = float(cfg_row.get("radius_max_km") or max_radius_km)

    density_mode = str(cfg_row.get("density_mode") or "radius_based")
    cell_area_m = str(cfg_row.get("cell_area_method") or "haversine")

    shrink_txt = cfg_row.get("radius_shrink_spec")
    shrink_spec: Optional[Dict[str, Any]] = None
    if shrink_txt:
        from utils.heatmap_json_validation import validate_radius_shrink_spec

        shrink_spec = validate_radius_shrink_spec(shrink_txt)

    selected_method = resolve_interpolation_method(cfg_row)
    if selected_method != "idw":
        raise RuntimeError(f"interpolation method {selected_method!r} not implemented (only idw)")

    total_cells = grid_n * grid_n
    spatial_mode = resolve_spatial_index_mode(cfg_row, n_stations=n, grid_cells=total_cells)

    skip_idw = n < min_points_render
    if skip_idw:
        logger.info(
            "[Heatmap] Render guard: input_points=%s < min_points_render=%s (no IDW grid)",
            n,
            min_points_render,
        )

    lat_step = (lat_max - lat_min) / grid_n
    lon_step = (lon_max - lon_min) / grid_n

    norm_engine = NormalizationEngine(db)
    feature_defs = sorted(
        [dict(r) for r in feat_rows if int(r.get("enabled", 1))],
        key=lambda r: int(r.get("sort_order") or 0),
    )
    w_sum = sum(float(r["weight"]) for r in feature_defs)
    if feature_defs and abs(w_sum - 1.0) > 0.02:
        raise RuntimeError(f"heatmap_confidence_feature weights must sum to 1.0 (got {w_sum})")

    cell_scores: List[float] = []
    grid: List[List[float]] = []
    sum_mean_interp_km = 0.0
    count_mean_interp = 0

    def _station_idx(slat: float, slon: float) -> Optional[int]:
        for idx, (a, b) in enumerate(zip(lats, lons)):
            if abs(a - slat) < 1e-5 and abs(b - slon) < 1e-5:
                return idx
        return None

    if not skip_idw:
        for i in range(grid_n):
            # Match legacy IDW: sample at grid corner (same as previous MapDataBuilder)
            glat = lat_min + i * lat_step
            for j in range(grid_n):
                glon = lon_min + j * lon_step

                r_used = max_radius_km
                if adaptive:
                    r_used = _adaptive_radius(
                        glat, glon, lats, lons, vals, r_min=r_min, r_max=r_cap, r_step=r_step, min_points=min_points
                    )

                inside = _stations_within_radius(glat, glon, lats, lons, vals, r_used)
                n_pts = len(inside)

                if density_mode == "radius_based":
                    area_km2 = math.pi * max(r_used, 1e-6) ** 2
                    spatial_density = n_pts / max(area_km2, 1e-12)
                else:
                    ca = _cell_area_km2(glat, lat_step, lon_step, cell_area_m)
                    spatial_density = n_pts / max(ca, 1e-12)

                if shrink_spec and adaptive:
                    try:
                        fmul = _shrink_factor_from_spec(shrink_spec, spatial_density)
                        r_used = max(r_min, min(r_cap, r_used / max(fmul, 1e-9)))
                        inside = _stations_within_radius(glat, glon, lats, lons, vals, r_used)
                        n_pts = len(inside)
                    except Exception as e:
                        raise RuntimeError(f"radius_shrink_spec application failed: {e}") from e

                val, _den, used, wn, wd = _idw_station_value(
                    glat, glon, lats, lons, vals, r_used, idw_power, decay_type
                )
                if math.isnan(val) or used < min_points:
                    continue

                if wd > 0:
                    mean_d = wn / wd
                    sum_mean_interp_km += mean_d
                    count_mean_interp += 1
                else:
                    mean_d = 0.0

                # Per-cell score from normalized features
                cell_score = None
                if feature_defs:
                    acc = 0.0
                    for fr in feature_defs:
                        fk = str(fr["feature_key"])
                        wgt = float(fr["weight"])
                        pk = str(fr["profile_key"])
                        if fk == "cell_n_points":
                            nv, _ = norm_engine.normalize_by_profile_key(pk, float(n_pts))
                            if nv is None:
                                raise RuntimeError(f"normalization None for {pk}")
                            acc += wgt * float(nv)
                        elif fk == "cell_mean_distance_km":
                            nv, _ = norm_engine.normalize_by_profile_key(pk, float(mean_d))
                            if nv is None:
                                raise RuntimeError(f"normalization None for {pk}")
                            acc += wgt * (1.0 - float(nv))
                        elif fk == "cell_spatial_density":
                            nv, _ = norm_engine.normalize_by_profile_key(pk, float(spatial_density))
                            if nv is None:
                                raise RuntimeError(f"normalization None for {pk}")
                            acc += wgt * float(nv)
                        elif fk == "data_quality_type":
                            w_list: List[float] = []
                            for slat, slon, _sval, _d in inside:
                                idx = _station_idx(slat, slon)
                                if idx is not None:
                                    src = point_sources[idx]
                                    if src not in data_quality_weights:
                                        raise RuntimeError(
                                            f"data_quality_weights has no entry for source {src!r}"
                                        )
                                    w_list.append(float(data_quality_weights[src]))
                            mean_q = sum(w_list) / len(w_list) if w_list else 0.0
                            wmin = min(float(v) for v in data_quality_weights.values())
                            wmax = max(float(v) for v in data_quality_weights.values())
                            if wmax <= wmin:
                                raise RuntimeError("data_quality_weights: max must exceed min")
                            norm_q = (mean_q - wmin) / (wmax - wmin)
                            nv, _ = norm_engine.normalize_by_profile_key(pk, float(norm_q))
                            if nv is None:
                                raise RuntimeError(f"normalization None for {pk}")
                            acc += wgt * float(nv)
                        elif fk == "temporal_freshness_hours":
                            hrs_in_cell: List[float] = []
                            for slat, slon, _sval, _d in inside:
                                idx = _station_idx(slat, slon)
                                if idx is not None and station_hours[idx] is not None:
                                    hrs_in_cell.append(float(station_hours[idx]))
                            worst = max(hrs_in_cell) if hrs_in_cell else 0.0
                            nv, _ = norm_engine.normalize_by_profile_key(pk, float(worst))
                            if nv is None:
                                raise RuntimeError(f"normalization None for {pk}")
                            acc += wgt * (1.0 - float(nv))
                        else:
                            raise RuntimeError(f"unknown heatmap_confidence_feature.feature_key: {fk!r}")
                    cell_score = max(0.0, min(1.0, acc))
                    cell_score = apply_float_precision(cell_score, float_mode)
                    cell_scores.append(cell_score)

                grid.append(
                    [
                        apply_float_precision(glat, float_mode) if float_mode == "rounded_6dp" else round(glat, 5),
                        apply_float_precision(glon, float_mode) if float_mode == "rounded_6dp" else round(glon, 5),
                        apply_float_precision(val, float_mode) if float_mode == "rounded_6dp" else round(val, 3),
                    ]
                )

    mean_interp = (
        apply_float_precision(sum_mean_interp_km / count_mean_interp, float_mode)
        if count_mean_interp > 0
        else None
    )

    meta: Dict[str, Any] = {
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lon_min": lon_min,
        "lon_max": lon_max,
        "grid_n": grid_n,
        "lat_step": lat_step,
        "lon_step": lon_step,
        "mean_interpolation_distance_km": mean_interp,
    }

    # Coverage over full grid
    coverage_smooth = float(len(grid)) / float(total_cells) if total_cells > 0 else 0.0

    # Global score from cell distribution + coverage + low cell ratio
    agg_cell_stat = _aggregate_scores(cell_scores, str(agg_row.get("cell_score_aggregation_method") or "mean")) if agg_row else 0.0
    low_th = float(agg_row.get("low_cell_score_threshold") or 0.35) if agg_row else 0.35
    low_cells = sum(1 for s in cell_scores if s < low_th)
    denom_cells = len(cell_scores) if cell_scores else 1
    low_ratio = float(low_cells) / float(denom_cells)

    w_m = float(agg_row.get("global_combine_w_mean_cell") or 0.5) if agg_row else 0.5
    w_c = float(agg_row.get("global_combine_w_coverage") or 0.3) if agg_row else 0.3
    w_l = float(agg_row.get("global_combine_w_low_cell_ratio") or 0.2) if agg_row else 0.2
    if abs((w_m + w_c + w_l) - 1.0) > 0.02:
        raise RuntimeError("heatmap_confidence_aggregate global weights must sum to 1.0")

    s_cov = coverage_smooth
    s_low = max(0.0, min(1.0, 1.0 - low_ratio))
    global_score = w_m * agg_cell_stat + w_c * s_cov + w_l * s_low
    clip_doc = validate_global_score_clip(cfg_row.get("global_score_clipping"))
    cmin, cmax = clip_doc.get("min"), clip_doc.get("max")
    if cmin is not None:
        global_score = max(float(cmin), global_score)
    if cmax is not None:
        global_score = min(float(cmax), global_score)
    global_score = apply_float_precision(global_score, float_mode)

    # Histogram (10 bins)
    bins = [0] * 10
    for s in cell_scores:
        b = int(min(9, max(0, int(s * 10))))
        bins[b] += 1

    # Gates + levels from calibration + threshold row
    low_n = float(calib["heatmap_confidence_low_min_stations"])
    unr_n = float(calib["heatmap_confidence_unreliable_min_stations"])
    low_cov = float(calib["heatmap_confidence_low_max_coverage_fraction"])
    unr_cov = float(calib["heatmap_confidence_unreliable_max_coverage_fraction"])

    score_unreliable = float(thr_row.get("score_unreliable_below")) if thr_row else float(
        calib["heatmap_confidence_score_unreliable_below"]
    )
    score_low = float(thr_row.get("score_low_below")) if thr_row else float(calib["heatmap_confidence_score_low_below"])

    reasons: List[str] = []
    gate_level = "ok"
    if total_cells <= 0 or n < unr_n or coverage_smooth < unr_cov:
        gate_level = "unreliable"
        if n < unr_n:
            reasons.append("few_stations")
        if coverage_smooth < unr_cov:
            reasons.append("low_coverage_fraction")
    elif n < low_n or coverage_smooth < low_cov:
        gate_level = "low"
        if n < low_n:
            reasons.append("stations_below_low_threshold")
        if coverage_smooth < low_cov:
            reasons.append("coverage_below_low_threshold")

    score_level = "ok"
    if global_score < score_unreliable:
        score_level = "unreliable"
        reasons.append("score_below_unreliable_threshold")
    elif global_score < score_low:
        score_level = "low"
        reasons.append("score_below_low_threshold")

    order = {"ok": 0, "low": 1, "unreliable": 2}
    level = gate_level if order[gate_level] >= order[score_level] else score_level

    if skip_idw and "insufficient_data_density" not in reasons:
        reasons.append("insufficient_data_density")

    formula_version = float(calib.get("heatmap_confidence_formula_version") or 1.0)

    dist_component: Optional[float] = None
    if mean_interp is not None:
        nd, _ = norm_engine.normalize_by_profile_key("heatmap_conf_mean_distance_km", float(mean_interp))
        if nd is not None:
            dist_component = apply_float_precision(1.0 - float(nd), float_mode)

    heatmap_confidence: Dict[str, Any] = {
        "level": level,
        "score": apply_float_precision(global_score, float_mode),
        "global_score": apply_float_precision(global_score, float_mode),
        "reasons": reasons,
        "coverage_fraction": apply_float_precision(coverage_smooth, float_mode),
        "n_stations": n,
        "grid_cells_total": int(total_cells),
        "mean_interpolation_distance_km": mean_interp,
        "formula_version": formula_version,
        "components": {
            # Legacy keys (MapDataBuilder contract / tests)
            "station_score": apply_float_precision(agg_cell_stat, float_mode),
            "coverage_score": apply_float_precision(s_cov, float_mode),
            "distance_score": dist_component,
            # Extended per-cell model
            "aggregated_cell_score": apply_float_precision(agg_cell_stat, float_mode),
            "low_cell_component": apply_float_precision(s_low, float_mode),
            "mean_cell_score": apply_float_precision(agg_cell_stat, float_mode),
        },
        "cell_score_histogram": {"bins": bins, "bin_width": 0.1},
    }

    engine_config = {
        "context_key": context_key,
        "heatmap_engine_config_version": int(cfg_row.get("heatmap_engine_config_version") or 1),
        "config_schema_version": int(cfg_row.get("config_schema_version") or 1),
        "float_precision_mode": float_mode,
        "interpolation_method": selected_method,
        "spatial_index_mode": spatial_mode,
    }

    warn_codes: List[str] = []
    if skip_idw:
        warn_codes.append("insufficient_data_density")

    extra: Dict[str, Any] = {
        "heatmap_confidence": heatmap_confidence,
        "engine_config": engine_config,
        "heatmap_meta": {
            "spatial_index_mode": spatial_mode,
            "adaptive_radius_enabled": adaptive,
            "density_mode": density_mode,
            "min_points_render": int(min_points_render),
            "total_input_points": int(n),
            "skip_idw_grid": bool(skip_idw),
        },
        "warning_codes": warn_codes,
    }

    if debug_mode:
        sample_n = int(float(calib.get("heatmap_debug_sample_cells") or 0))
        if sample_n > 0 and grid:
            rid = str(uuid.uuid4())
            picks = random.sample(range(len(grid)), min(sample_n, len(grid)))
            for k in picks:
                row = grid[k]
                cs = cell_scores[k] if k < len(cell_scores) else None
                db.insert_heatmap_render_debug(
                    rid,
                    k // max(grid_n, 1),
                    k % max(grid_n, 1),
                    json.dumps({"lat": row[0], "lon": row[1], "value": row[2]}),
                    cs,
                    context_key=context_key,
                )
            extra["heatmap_debug"] = {"render_id": rid, "samples_written": len(picks)}

    return grid, meta, extra
