"""map_tile_provider contract and payload shape."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager  # noqa: E402


def test_map_tile_provider_seed_passes_validation(tmp_path):
    db_path = tmp_path / "t.db"
    db = DatabaseManager(str(db_path))
    db.validate_map_tile_contract()
    row = db.get_map_tile_provider_row()
    assert "openstreetmap" in row["url_template"].lower()
    pl = db.get_map_tile_provider_for_payload()
    assert pl["url_template"]
    assert pl["attribution_html"]
    assert "subdomains" in pl


def test_validate_rejects_osm_without_attribution_reference(tmp_path):
    db_path = tmp_path / "u.db"
    db = DatabaseManager(str(db_path))
    conn = db.get_connection()
    conn.execute(
        "UPDATE map_tile_provider SET attribution_html = ? WHERE id = 1",
        ("Wrong attribution only",),
    )
    conn.commit()
    with pytest.raises(RuntimeError, match="OpenStreetMap"):
        db.validate_map_tile_contract()
