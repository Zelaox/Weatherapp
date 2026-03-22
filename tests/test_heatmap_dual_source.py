"""Dual PM2.5 heatmap source: JSON validation (no full DB required)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.heatmap_json_validation import (  # noqa: E402
    validate_data_quality_weights,
    validate_data_source_priority,
)


def test_validate_data_source_priority_ok():
    assert validate_data_source_priority('["raw_latest","aggregated_24h"]') == [
        "raw_latest",
        "aggregated_24h",
    ]


def test_validate_data_source_priority_rejects_unknown_token():
    with pytest.raises(ValueError, match="validation failed"):
        validate_data_source_priority('["raw_latest","unknown"]')


def test_validate_data_quality_weights_ok():
    w = validate_data_quality_weights('{"raw_latest":0.85,"aggregated_24h":1.0}')
    assert w["raw_latest"] == pytest.approx(0.85)
    assert w["aggregated_24h"] == pytest.approx(1.0)


def test_validate_data_quality_weights_requires_both_keys():
    with pytest.raises(ValueError, match="validation failed"):
        validate_data_quality_weights('{"raw_latest":0.85}')
