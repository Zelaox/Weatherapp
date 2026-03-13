"""Log analysis utilities for dynamic, log-driven debugging.

This module reads log files and builds a structured view of problems
per component, provider and error class – without hårdkodade feltyper.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional


LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - "
    r"(?P<logger>[^ ]+) - "
    r"(?P<level>[A-Z]+) - "
    r"(?P<msg>.*)$"
)


@dataclass
class ProblemEntry:
    first_seen: datetime
    last_seen: datetime
    count: int
    sample_message: str


def _classify_error(message: str) -> str:
    """Classify error message into a high-level, generic error class."""
    msg_lower = message.lower()

    # HTTP errors (any 3xx/4xx/5xx with 'error' text)
    if re.search(r"\b\d{3}\b", message) and "error" in msg_lower:
        return "http"

    # Schema / migration issues
    if "no such table" in msg_lower or "no such column" in msg_lower:
        return "schema"
    if "missing required calibration parameters" in msg_lower:
        return "calibration"

    # Provider / API availability
    if "timeout" in msg_lower or "connection error" in msg_lower:
        return "network"

    # Fallback class
    if "error" in msg_lower or "exception" in msg_lower or "traceback" in msg_lower:
        return "runtime"

    return "info"


def analyze_logs(log_dir: Path) -> Dict[str, Any]:
    """
    Analyze all log files in a directory and build a structured report.

    Args:
        log_dir: Directory containing *.log files

    Returns:
        Dict with aggregated problems per component and error_class.
    """
    report: Dict[str, Any] = {
        "log_dir": str(log_dir),
        "components": {},  # component -> error_class -> List[ProblemEntry]
    }

    components: Dict[str, Dict[str, Dict[str, ProblemEntry]]] = defaultdict(
        lambda: defaultdict(dict)
    )

    if not log_dir.exists() or not log_dir.is_dir():
        return report

    for path in sorted(log_dir.glob("*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m = LOG_LINE_RE.match(line.rstrip("\n"))
                    if not m:
                        continue

                    ts_str = m.group("ts")
                    logger_name = m.group("logger")
                    level = m.group("level")
                    msg = m.group("msg")

                    try:
                        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        ts = datetime.min

                    component = logger_name  # treat logger name as component
                    error_class = _classify_error(msg)

                    # Use message text as key for aggregation within (component, class)
                    key = f"{level}:{msg}"
                    bucket = components[component][error_class]
                    if key in bucket:
                        entry = bucket[key]
                        entry.count += 1
                        if ts > entry.last_seen:
                            entry.last_seen = ts
                    else:
                        bucket[key] = ProblemEntry(
                            first_seen=ts,
                            last_seen=ts,
                            count=1,
                            sample_message=msg,
                        )
        except Exception:
            # Log files should never break analysis completely – just skip problematic files
            continue

    # Normalize dataclasses to plain dicts for JSON-friendliness
    normalized_components: Dict[str, Any] = {}
    for component, classes in components.items():
        class_dict: Dict[str, List[Dict[str, Any]]] = {}
        for error_class, messages in classes.items():
            entries: List[Dict[str, Any]] = []
            for entry in messages.values():
                entries.append(
                    {
                        "first_seen": entry.first_seen.isoformat()
                        if entry.first_seen != datetime.min
                        else None,
                        "last_seen": entry.last_seen.isoformat()
                        if entry.last_seen != datetime.min
                        else None,
                        "count": entry.count,
                        "sample_message": entry.sample_message,
                    }
                )
            # sort most frequent first
            entries.sort(key=lambda e: e["count"], reverse=True)
            class_dict[error_class] = entries
        normalized_components[component] = class_dict

    report["components"] = normalized_components
    return report


def summarize_providers(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract provider-related issues from a full log report.

    Providers are identified generically by logger names containing 'providers'
    or known provider names (openmeteo, openaq, openweather).
    """
    provider_report: Dict[str, Any] = {}
    components = report.get("components", {})

    for component, classes in components.items():
        name_lower = component.lower()
        if "providers" in name_lower or any(
            p in name_lower for p in ("openmeteo", "openaq", "openweather")
        ):
            provider_report[component] = classes

    return provider_report


def summarize_schema_issues(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract schema/migration related issues from a full log report.
    """
    schema_report: Dict[str, Any] = {}
    components = report.get("components", {})

    for component, classes in components.items():
        schema_entries: List[Dict[str, Any]] = []
        for error_class, entries in classes.items():
            if error_class in ("schema", "calibration"):
                schema_entries.extend(entries)
        if schema_entries:
            # sort by count desc
            schema_entries.sort(key=lambda e: e["count"], reverse=True)
            schema_report[component] = schema_entries

    return schema_report

