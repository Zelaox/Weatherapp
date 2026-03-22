"""
Strict validation for parameter_registry.backfill_support JSON (not freeform).

Loads JSON Schema from database/schemas/backfill_support.schema.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Union

_SCHEMA_CACHE: Dict[str, Any] | None = None


def _schema_path() -> Path:
    return Path(__file__).resolve().parent.parent / "database" / "schemas" / "backfill_support.schema.json"


def load_backfill_support_schema() -> Dict[str, Any]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        p = _schema_path()
        if not p.exists():
            raise FileNotFoundError(f"backfill_support JSON Schema missing: {p}")
        _SCHEMA_CACHE = json.loads(p.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE


def default_backfill_support_dict() -> Dict[str, Any]:
    """Default allowed document (matches schema)."""
    return {
        "archive": True,
        "forecast": True,
        "realtime": True,
        "endpoint_profile": "any",
    }


def default_backfill_support_json() -> str:
    return json.dumps(default_backfill_support_dict(), separators=(",", ":"), sort_keys=True)


def validate_backfill_support(
    value: Union[str, Mapping[str, Any], None],
    *,
    allow_none: bool = False,
) -> Dict[str, Any]:
    """
    Validate backfill_support payload. Raises ValueError on invalid input.

    Returns normalized dict (sorted keys for stable storage if needed).
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        if allow_none:
            return default_backfill_support_dict()
        raise ValueError("backfill_support is required (use default_backfill_support_json())")

    if isinstance(value, str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"backfill_support is not valid JSON: {e}") from e
    elif isinstance(value, Mapping):
        data = dict(value)
    else:
        raise ValueError(f"backfill_support must be str or mapping, got {type(value)}")

    schema = load_backfill_support_schema()
    try:
        import jsonschema

        jsonschema.validate(instance=data, schema=schema)
    except ImportError:
        _validate_backfill_support_manual(data)
    except Exception as e:
        if type(e).__name__ == "ValidationError":
            raise ValueError(f"backfill_support failed JSON Schema validation: {e}") from e
        raise

    return data


def _validate_backfill_support_manual(data: Dict[str, Any]) -> None:
    """Fallback when jsonschema is not installed (tests should install jsonschema)."""
    req = {"archive", "forecast", "realtime", "endpoint_profile"}
    if set(data.keys()) != req:
        raise ValueError(f"backfill_support must have exactly keys {req}, got {set(data.keys())}")
    for k in ("archive", "forecast", "realtime"):
        if not isinstance(data[k], bool):
            raise ValueError(f"backfill_support.{k} must be bool")
    ep = data["endpoint_profile"]
    if ep not in ("forecast-api", "archive-api", "any"):
        raise ValueError("backfill_support.endpoint_profile must be forecast-api|archive-api|any")


def normalize_backfill_support_json(value: Union[str, Mapping[str, Any], None]) -> str:
    """Validate and return compact JSON string for storage."""
    d = validate_backfill_support(value)
    return json.dumps(d, separators=(",", ":"), sort_keys=True)
