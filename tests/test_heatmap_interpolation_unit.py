"""Unit tests for heatmap rule evaluation and helpers (no full DB migration required)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics.heatmap_interpolation import (  # noqa: E402
    apply_float_precision,
    evaluate_rules_json,
)


def test_apply_float_precision_raw():
    assert apply_float_precision(0.123456789, "raw") == 0.123456789


def test_apply_float_precision_rounded():
    assert apply_float_precision(0.123456789, "rounded_6dp") == pytest.approx(0.123457)


def test_evaluate_rules_first_match():
    doc = {
        "schema_version": 1,
        "priority_order": "asc",
        "evaluation_order": "top_down",
        "first_match_wins": True,
        "rules": [
            {"rule_priority": 0, "when": {}, "then": {"method": "idw"}},
            {"rule_priority": 1, "when": {"x": 1}, "then": {"method": "nearest"}},
        ],
    }
    assert evaluate_rules_json(doc, {}) == {"method": "idw"}


def test_evaluate_rules_ambiguous_same_priority_raises():
    doc = {
        "schema_version": 1,
        "priority_order": "asc",
        "evaluation_order": "top_down",
        "first_match_wins": True,
        "rules": [
            {"rule_priority": 0, "when": {}, "then": {"method": "idw"}},
            {"rule_priority": 0, "when": {}, "then": {"method": "nearest"}},
        ],
    }
    with pytest.raises(RuntimeError, match="ambiguous"):
        evaluate_rules_json(doc, {})
