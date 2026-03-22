"""Solar index from composite_index_definition (DB) + NormalizationEngine."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from database.db_manager import DatabaseManager
from analytics.normalization_engine import NormalizationEngine
from utils.composite_index_validation import validate_composite_index_definition

logger = logging.getLogger("WeatherApp.analytics.solar_composite")


def calculate_solar_index_from_composite(
    db: DatabaseManager,
    weather: Dict[str, Any],
    engine: NormalizationEngine,
    *,
    debug_trace: bool = False,
) -> Tuple[Optional[float], Optional[List[Dict[str, Any]]]]:
    """
    Compute solar_index using composite_index_definition for 'solar_index'.

    Returns:
        (solar_index or None, optional list of per-input trace dicts when debug_trace=True)
    """
    raw = db.get_composite_index_definition_json("solar_index")
    doc = validate_composite_index_definition(raw)
    combine = doc["combine"]
    if combine == "split_instant_vs_accumulated":
        raise NotImplementedError(
            "composite combine mode split_instant_vs_accumulated is not implemented"
        )
    if combine != "weighted_linear":
        raise ValueError(f"Unsupported combine mode for solar_index: {combine}")

    transforms: Dict[str, str] = dict(doc.get("transforms") or {})
    inputs: List[Dict[str, Any]] = list(doc["inputs"])
    traces: List[Dict[str, Any]] = []

    terms: List[float] = []
    weights: List[float] = []

    for inp in inputs:
        pname = str(inp["parameter_name"])
        weight = float(inp["weight"])
        tclass = str(inp["temporal_class"])
        tform = transforms.get(pname, "none")

        raw_val = weather.get(pname)
        if tform == "divide_by_interval_seconds":
            iv = db.get_calibration_parameter("composite_sunshine_interval_seconds")
            if iv is None:
                raise ValueError(
                    "divide_by_interval_seconds requires calibration key composite_sunshine_interval_seconds"
                )
            if raw_val is None:
                val_use = None
            else:
                val_use = float(raw_val) / max(float(iv), 1e-9)
        elif tform == "none":
            val_use = raw_val if raw_val is None else float(raw_val)
        else:
            raise ValueError(f"Unsupported transform for {pname}: {tform}")

        if val_use is None:
            continue

        nv, tr = engine.normalize(pname, val_use, debug_trace=debug_trace)
        if debug_trace and tr is not None:
            tr = dict(tr)
            tr["temporal_class"] = tclass
            tr["transform"] = tform
            traces.append(tr)
        if nv is not None:
            terms.append(nv)
            weights.append(weight)

    if not terms:
        logger.debug("solar_composite: no valid normalized terms")
        return None, (traces if debug_trace else None)

    tw = sum(weights)
    if tw <= 0:
        return None, (traces if debug_trace else None)
    weights = [w / tw for w in weights]

    solar_index = sum(t * w for t, w in zip(terms, weights))
    solar_index = max(0.0, min(1.0, float(solar_index)))
    return solar_index, (traces if debug_trace else None)
