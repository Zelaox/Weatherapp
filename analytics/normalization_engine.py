"""Single entry point for parameter normalization (DB-driven normalization_profile)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from database.db_manager import DatabaseManager

logger = logging.getLogger("WeatherApp.analytics.normalization_engine")


class NormalizationEngine:
    """Normalize values using normalization_profile from parameter_registry (fail loud if missing)."""

    def __init__(self, db: DatabaseManager):
        self._db = db

    def normalize_by_profile_key(
        self,
        profile_key: str,
        value: Optional[float],
        *,
        debug_trace: bool = False,
    ) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
        """
        Normalize using normalization_profile.profile_key directly (no parameter_registry row).
        Used for heatmap confidence components and other DB-anchored metrics.
        """
        if value is None:
            return None, None
        profile = self._db.get_normalization_profile_by_key(profile_key)
        if profile is None:
            raise ValueError(
                f"Missing normalization_profile row for profile_key={profile_key!r}"
            )
        label = f"@{profile_key}"
        return self._normalize_with_profile(profile, label, float(value), debug_trace=debug_trace)

    def normalize(
        self,
        parameter: str,
        value: Optional[float],
        *,
        debug_trace: bool = False,
    ) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
        """
        Normalize value to [0, 1] per DB profile.

        Returns:
            (normalized_value, trace_dict_or_none). trace is only populated when debug_trace=True.
        """
        if value is None:
            return None, None

        profile = self._db.get_normalization_profile_for_parameter(parameter)
        if profile is None:
            raise ValueError(
                f"Missing normalization_profile_id for parameter '{parameter}' in parameter_registry"
            )

        return self._normalize_with_profile(profile, parameter, float(value), debug_trace=debug_trace)

    def _normalize_with_profile(
        self,
        profile: Dict[str, Any],
        parameter: str,
        value: float,
        *,
        debug_trace: bool,
    ) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
        mode = profile["mode"]
        pid = int(profile["id"])
        pkey = str(profile["profile_key"])

        if mode == "identity":
            # Pass-through: treat as already comparable scale (clamp only)
            nv = float(value)
            out = max(0.0, min(1.0, nv))
            tr = None
            if debug_trace:
                tr = {
                    "parameter": parameter,
                    "mode": mode,
                    "normalization_profile_id": pid,
                    "profile_key": pkey,
                    "method": "identity",
                }
            return out, tr

        if mode == "fixed_domain":
            lo = profile.get("fixed_min")
            hi = profile.get("fixed_max")
            if lo is None or hi is None:
                raise ValueError(
                    f"fixed_domain profile '{pkey}' missing fixed_min/fixed_max for '{parameter}'"
                )
            lo_f, hi_f = float(lo), float(hi)
            if hi_f <= lo_f:
                logger.warning("NormalizationEngine: invalid fixed_domain bounds for %s", parameter)
                return None, None
            norm = (float(value) - lo_f) / (hi_f - lo_f)
            out = max(0.0, min(1.0, norm))
            tr = None
            if debug_trace:
                tr = {
                    "parameter": parameter,
                    "mode": mode,
                    "normalization_profile_id": pid,
                    "profile_key": pkey,
                    "resolved_lo": lo_f,
                    "resolved_hi": hi_f,
                    "method": "fixed_domain",
                }
            return out, tr

        if mode == "winsorized_percentile":
            p_low = profile.get("p_low")
            p_high = profile.get("p_high")
            if p_low is None or p_high is None:
                raise ValueError(
                    f"winsorized_percentile profile '{pkey}' missing p_low/p_high for '{parameter}'"
                )
            hist = profile.get("history_days")
            hist_f = float(hist) if hist is not None else None

            bounds_result = self._db.get_parameter_winsorized_bounds(
                parameter,
                float(p_low),
                float(p_high),
                history_days_override=hist_f,
                include_meta=debug_trace,
            )
            if not debug_trace:
                lo_b, hi_b = bounds_result  # type: ignore[misc]
                meta = None
            else:
                lo_b, hi_b, meta = bounds_result  # type: ignore[misc]

            if lo_b is None or hi_b is None:
                logger.debug(
                    "NormalizationEngine: no winsor bounds for %s (insufficient history?)", parameter
                )
                return None, (meta if debug_trace else None)

            lo_f, hi_f = float(lo_b), float(hi_b)
            if hi_f <= lo_f:
                logger.warning("NormalizationEngine: invalid winsor bounds for %s", parameter)
                return None, None

            norm = (float(value) - lo_f) / (hi_f - lo_f)
            out = max(0.0, min(1.0, norm))

            tr = None
            if debug_trace:
                tr = {
                    "parameter": parameter,
                    "mode": mode,
                    "normalization_profile_id": pid,
                    "profile_key": pkey,
                    "p_low": float(p_low),
                    "p_high": float(p_high),
                    "history_days": hist_f,
                    "resolved_lo": lo_f,
                    "resolved_hi": hi_f,
                    "method": "winsorized_percentile",
                }
                if meta:
                    tr["n_samples"] = meta.get("n_samples")
                    tr["history_window_days"] = meta.get("history_window_days")
            return out, tr

        raise ValueError(f"Unknown normalization mode '{mode}' for parameter '{parameter}'")
