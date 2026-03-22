"""Map init sequencing, heatmap confidence payload, normalization readiness."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager  # noqa: E402
from gui.stations_tab import MapDataBuilder, StationsTab, WEBENGINE_AVAILABLE  # noqa: E402
from analytics.warnings import WarningDetector  # noqa: E402


def test_map_html_uses_resize_observer_not_raf_polling(tmp_path):
    db_path = tmp_path / "m.db"
    db = DatabaseManager(str(db_path))
    ctrl = MagicMock()
    ctrl.db = db
    ctrl.config.get_setting = MagicMock(side_effect=lambda k, d=None: d)
    if not WEBENGINE_AVAILABLE:
        pytest.skip("PyQt WebEngine not available")
    from PyQt5.QtWidgets import QApplication
    import sys

    _app = QApplication.instance() or QApplication(sys.argv)
    tab = StationsTab(ctrl)
    html = tab._generate_map_html(
        json.dumps(
            {
                "cities": [],
                "heatmap_confidence": {"level": "ok"},
                "heatmap_confidence_visual": {
                    "ok": {"opacity_multiplier": 1.0, "badge_style_key": "ok", "badge_label_sv": "OK"},
                    "low": {"opacity_multiplier": 0.7, "badge_style_key": "low", "badge_label_sv": "Låg"},
                    "unreliable": {
                        "opacity_multiplier": 0.5,
                        "badge_style_key": "unreliable",
                        "badge_label_sv": "Dålig",
                    },
                },
                "map_init_timeout_ms": 5000,
                "map_tile": {
                    "url_template": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                    "attribution_html": "&copy; OpenStreetMap contributors",
                    "subdomains": "abc",
                    "max_zoom": 19,
                },
                "normalization_readiness": {
                    "unusable_parameters": [],
                    "unstable_count": 0,
                    "unusable_count": 0,
                },
            }
        ),
        70,
        62.0,
        15.0,
        map_extent=None,
    )
    assert "ResizeObserver" in html
    assert "beginHeatmapAttachWhenSized" in html
    assert "MAP_INIT_TIMEOUT" in html
    assert "requestAnimationFrame(initHeatOverlay" not in html
    assert "PAYLOAD.map_tile" in html or "mt.url_template" in html


def test_normalization_engine_normalize_by_profile_key(tmp_path):
    db_path = tmp_path / "p.db"
    db = DatabaseManager(str(db_path))
    from analytics.normalization_engine import NormalizationEngine

    eng = NormalizationEngine(db)
    out, _tr = eng.normalize_by_profile_key("heatmap_conf_station_count", 15.0)
    assert out == pytest.approx(0.5)


def test_map_payload_includes_confidence_components_and_readiness(tmp_path):
    db_path = tmp_path / "b.db"
    db = DatabaseManager(str(db_path))
    builder = MapDataBuilder(db, WarningDetector(db), debug_mode=False)
    payload = builder.build()
    assert "heatmap_confidence" in payload
    hc = payload["heatmap_confidence"]
    assert "level" in hc and "score" in hc
    assert "components" in hc
    assert set(hc["components"].keys()) >= {"station_score", "coverage_score", "distance_score"}
    assert payload.get("map_init_timeout_ms", 0) > 0
    assert "heatmap_confidence_visual" in payload
    for lvl in ("ok", "low", "unreliable"):
        assert lvl in payload["heatmap_confidence_visual"]
    nr = payload.get("normalization_readiness") or {}
    assert "unusable_parameters" in nr
    assert "idw_meta" in payload
    if payload["idw_meta"]:
        assert "mean_interpolation_distance_km" in payload["idw_meta"]


def test_normalization_readiness_report_shape(tmp_path):
    db_path = tmp_path / "r.db"
    db = DatabaseManager(str(db_path))
    rep = db.get_normalization_readiness_report()
    assert "parameters" in rep
    assert "usable_count" in rep
    for p in rep["parameters"]:
        assert p["status"] in ("usable", "unstable", "unusable")
