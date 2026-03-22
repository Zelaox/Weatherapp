"""Validate composite_index_definition JSON against database/schemas/composite_index_v1.schema.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Union

_SCHEMA_CACHE: Dict[str, Any] | None = None


def _schema_path() -> Path:
    return Path(__file__).resolve().parent.parent / "database" / "schemas" / "composite_index_v1.schema.json"


def load_composite_index_schema() -> Dict[str, Any]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        p = _schema_path()
        if not p.exists():
            raise FileNotFoundError(f"composite_index_v1 JSON Schema missing: {p}")
        _SCHEMA_CACHE = json.loads(p.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE


def validate_composite_index_definition(
    value: Union[str, Mapping[str, Any], None],
) -> Dict[str, Any]:
    """
    Validate composite index JSON. Raises ValueError on invalid input.
    Returns normalized dict.
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise ValueError("composite_index_definition config_json is required")

    if isinstance(value, str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"composite_index_definition is not valid JSON: {e}") from e
    elif isinstance(value, Mapping):
        data = dict(value)
    else:
        raise ValueError(f"composite_index_definition must be str or mapping, got {type(value)}")

    schema = load_composite_index_schema()
    try:
        import jsonschema

        jsonschema.validate(instance=data, schema=schema)
    except ImportError as e:
        raise RuntimeError("jsonschema is required for composite_index validation") from e
    except Exception as e:
        if type(e).__name__ == "ValidationError":
            raise ValueError(f"composite_index_definition failed JSON Schema validation: {e}") from e
        raise

    return data
