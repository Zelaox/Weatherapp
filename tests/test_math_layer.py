"""Math layer: composite schema, normalization profile join, CAPE piecewise."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager  # noqa: E402
from utils.composite_index_validation import validate_composite_index_definition  # noqa: E402
from analytics.normalization_engine import NormalizationEngine  # noqa: E402


def test_composite_index_v1_accepts_solar_seed(tmp_path):
    db_path = tmp_path / "c.db"
    db = DatabaseManager(str(db_path))
    raw = db.get_composite_index_definition_json("solar_index")
    doc = validate_composite_index_definition(raw)
    assert doc["schema_version"] == "composite_index_v1"
    assert doc["combine"] == "weighted_linear"


def test_composite_index_rejects_extra_top_level_key():
    with pytest.raises(ValueError):
        validate_composite_index_definition(
            {
                "schema_version": "composite_index_v1",
                "combine": "weighted_linear",
                "inputs": [
                    {
                        "parameter_name": "solar_radiation",
                        "temporal_class": "instantaneous",
                        "weight": 1.0,
                    }
                ],
                "transforms": {"solar_radiation": "none"},
                "extra": 1,
            }
        )


def test_cape_factors_from_db(tmp_path):
    db_path = tmp_path / "m.db"
    db = DatabaseManager(str(db_path))
    assert db.get_cape_storm_risk_factor(None) == 0.0
    assert db.get_cape_storm_risk_factor(0.0) == 0.0
    assert db.get_cape_storm_risk_factor(50.0) == pytest.approx(0.3)
    assert db.get_cape_storm_risk_factor(500.0) == pytest.approx(1.0)
    assert db.get_cape_storm_risk_factor(1500.0) == pytest.approx(1.5)
    assert db.get_cape_storm_risk_factor(3000.0) == pytest.approx(2.0)


def test_normalization_engine_winsor_path(tmp_path):
    db_path = tmp_path / "n.db"
    db = DatabaseManager(str(db_path))
    eng = NormalizationEngine(db)
    out, tr = eng.normalize("humidity", 50.0, debug_trace=False)
    assert out is None or isinstance(out, float)


def test_normalization_readiness_report_counts(tmp_path):
    db_path = tmp_path / "read.db"
    db = DatabaseManager(str(db_path))
    rep = db.get_normalization_readiness_report()
    assert rep["usable_count"] + rep["unstable_count"] + rep["unusable_count"] == len(rep["parameters"])
