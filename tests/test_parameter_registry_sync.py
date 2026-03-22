"""Automated registry/schema sync and backfill_support validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager  # noqa: E402
from utils.backfill_support_validation import (  # noqa: E402
    default_backfill_support_dict,
    validate_backfill_support,
)


def test_backfill_support_schema_accepts_default():
    d = default_backfill_support_dict()
    out = validate_backfill_support(d)
    assert out["archive"] is True
    assert out["endpoint_profile"] in ("forecast-api", "archive-api", "any")


def test_backfill_support_rejects_extra_keys():
    with pytest.raises(ValueError):
        validate_backfill_support(
            json.dumps(
                {
                    "archive": True,
                    "forecast": True,
                    "realtime": True,
                    "endpoint_profile": "any",
                    "extra": 1,
                }
            )
        )


def test_validate_registry_schema_sync_on_temp_db(tmp_path):
    db_path = tmp_path / "t.db"
    db = DatabaseManager(str(db_path))
    sync = db.validate_registry_schema_sync()
    assert sync.get("ok") is True, sync
    assert not sync.get("missing_registry_rows")
