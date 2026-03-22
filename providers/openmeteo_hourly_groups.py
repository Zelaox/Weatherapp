"""
Open-Meteo hourly request grouping: endpoint_profile + variable_family (DB only).

No hardcoded hourly bundles — families and members live in variable_family / variable_family_member.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class HourlyRequestGroup:
    """One HTTP hourly= string worth of Open-Meteo API field names."""

    family_key: Optional[str]
    endpoint_profile: str
    hourly_api_names: Tuple[str, ...]
    parameter_names: Tuple[str, ...]


def _get_conn(db: Any):
    return db.get_connection()


def resolve_family_id(
    conn: sqlite3.Connection, endpoint_profile: str, family_key: str
) -> Optional[int]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM variable_family
        WHERE endpoint_profile = ? AND family_key = ?
        """,
        (endpoint_profile, family_key),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def get_hourly_api_names_for_family(conn: sqlite3.Connection, family_id: int) -> List[str]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT hourly_api_name FROM variable_family_member
        WHERE family_id = ?
        ORDER BY sort_order ASC, hourly_api_name ASC
        """,
        (family_id,),
    )
    return [r[0] for r in cur.fetchall()]


def build_hourly_groups_for_parameters(
    db: Any,
    *,
    endpoint_profile: str,
    parameter_names: Sequence[str],
    openmeteo_mappings: Dict[str, str],
) -> List[HourlyRequestGroup]:
    """
    Group parameters by variable_family_key for one endpoint_profile.

    Parameters without variable_family_key get one group each (single hourly field) when mapping exists.
    """
    if not parameter_names:
        return []

    conn = _get_conn(db)
    cur = conn.cursor()
    placeholders = ",".join("?" * len(parameter_names))
    cur.execute(
        f"""
        SELECT parameter_name, variable_family_key, provider_mappings
        FROM parameter_registry
        WHERE parameter_name IN ({placeholders})
        """,
        tuple(parameter_names),
    )
    meta = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    groups: Dict[Tuple[str, str], List[str]] = {}
    singles: List[str] = []

    for pname in parameter_names:
        if pname not in openmeteo_mappings:
            continue
        row = meta.get(pname)
        fkey = row[0] if row else None
        if fkey:
            k = (endpoint_profile, fkey)
            groups.setdefault(k, []).append(pname)
        else:
            singles.append(pname)

    out: List[HourlyRequestGroup] = []

    for (ep, fkey), pnames in sorted(groups.items(), key=lambda x: (x[0][0], x[0][1])):
        fid = resolve_family_id(conn, ep, fkey)
        if fid is None:
            continue
        hourly_names = get_hourly_api_names_for_family(conn, fid)
        if not hourly_names:
            continue
        out.append(
            HourlyRequestGroup(
                family_key=fkey,
                endpoint_profile=ep,
                hourly_api_names=tuple(hourly_names),
                parameter_names=tuple(sorted(pnames)),
            )
        )

    for pname in singles:
        api = openmeteo_mappings.get(pname)
        if not api:
            continue
        out.append(
            HourlyRequestGroup(
                family_key=None,
                endpoint_profile=endpoint_profile,
                hourly_api_names=(api,),
                parameter_names=(pname,),
            )
        )

    return out


def hourly_groups_to_comma_string(group: HourlyRequestGroup) -> str:
    return ",".join(group.hourly_api_names)
