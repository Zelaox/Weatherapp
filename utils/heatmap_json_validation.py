"""
Validate JSON columns for heatmap_interpolation_config (fail loud; no silent defaults).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Union

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "database" / "schemas"


def _load_schema(name: str) -> Dict[str, Any]:
    p = _SCHEMA_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"heatmap schema missing: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _validate_with_jsonschema(instance: Dict[str, Any], schema_name: str) -> None:
    schema = _load_schema(schema_name)
    try:
        import jsonschema

        jsonschema.validate(instance=instance, schema=schema)
    except Exception as e:
        if type(e).__name__ == "ValidationError":
            raise ValueError(f"{schema_name} validation failed: {e}") from e
        raise


def validate_global_score_clip(value: Union[str, Mapping[str, Any], None]) -> Dict[str, Any]:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return {"min": None, "max": 1.0}
    if isinstance(value, str):
        data = json.loads(value)
    else:
        data = dict(value)
    _validate_with_jsonschema(data, "heatmap_global_score_clip.schema.json")
    return data


def validate_method_selection_rules(value: Union[str, Mapping[str, Any], None]) -> Dict[str, Any]:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise ValueError("method_selection_rules is required")
    if isinstance(value, str):
        data = json.loads(value)
    else:
        data = dict(value)
    _validate_with_jsonschema(data, "heatmap_method_selection_rules.schema.json")
    return data


def validate_spatial_index_rules(value: Union[str, Mapping[str, Any], None]) -> Dict[str, Any]:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise ValueError("spatial_index_rules is required")
    if isinstance(value, str):
        data = json.loads(value)
    else:
        data = dict(value)
    _validate_with_jsonschema(data, "heatmap_spatial_index_rules.schema.json")
    return data


def validate_radius_shrink_spec(value: Union[str, Mapping[str, Any], None]) -> Dict[str, Any]:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise ValueError("radius_shrink_spec is null")
    if isinstance(value, str):
        data = json.loads(value)
    else:
        data = dict(value)
    _validate_with_jsonschema(data, "heatmap_radius_shrink_spec.schema.json")
    return data
