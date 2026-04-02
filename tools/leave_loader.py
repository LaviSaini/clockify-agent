"""
Load approved leave ranges from HR CSV (e.g. Zoho export) and map to Clockify user ids
via normalized employee display names.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta


def _normalize_person_name(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def _name_match_key(name: str) -> str:
    """Stable key so CSV vs Clockify order differs (e.g. 'Pyla Abhilash' vs 'Abhilash Pyla')."""
    toks = sorted(_normalize_person_name(name).split())
    return " ".join(toks)


def _parse_leave_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_leave_csv_rows(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)

    header_idx = None
    for i, row in enumerate(rows):
        if row and len(row) > 1 and row[0].strip() == "Employee Number":
            header_idx = i
            break
    if header_idx is None:
        return []

    headers = [h.strip() for h in rows[header_idx]]
    out: list[dict[str, str]] = []
    for row in rows[header_idx + 1 :]:
        if not row or not any((c or "").strip() for c in row):
            continue
        while len(row) < len(headers):
            row.append("")
        out.append({headers[j]: row[j].strip() for j in range(len(headers))})
    return out


def load_leave_dates_by_normalized_name(
    path: str,
    range_start_s: str,
    range_end_s: str,
) -> dict[str, set[str]]:
    """
    Returns map: normalized employee name -> set of YYYY-MM-DD strings that are
    on approved leave, intersected with [range_start_s, range_end_s].

    Only rows with Status containing 'approved' (case-insensitive) are used.
    """
    if not path or not os.path.isfile(path):
        return {}

    try:
        audit_start = datetime.strptime(range_start_s, "%Y-%m-%d")
        audit_end = datetime.strptime(range_end_s, "%Y-%m-%d")
    except ValueError:
        return {}

    rows = _parse_leave_csv_rows(path)
    by_name: dict[str, set[str]] = {}

    for row in rows:
        status = (row.get("Status") or "").strip().lower()
        if "approved" not in status:
            continue

        emp_name = (row.get("Employee Name") or "").strip()
        if not emp_name:
            continue

        from_dt = _parse_leave_date(row.get("From Date") or "")
        to_dt = _parse_leave_date(row.get("To Date") or "")
        if from_dt is None or to_dt is None:
            continue
        if to_dt < from_dt:
            from_dt, to_dt = to_dt, from_dt

        key = _name_match_key(emp_name)
        bucket = by_name.setdefault(key, set())

        cur = from_dt.date()
        end_d = to_dt.date()
        while cur <= end_d:
            if audit_start.date() <= cur <= audit_end.date():
                bucket.add(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)

    return by_name


def build_leave_frozen_by_user_id(
    csv_path: str,
    name_by_id: dict[str, str],
    start_date: str,
    end_date: str,
) -> dict[str, frozenset[str]]:
    """Maps each Clockify user id to frozenset of YYYY-MM-DD on approved leave in range."""
    name_to_dates = load_leave_dates_by_normalized_name(csv_path, start_date, end_date)
    if not name_to_dates:
        return {}

    out: dict[str, frozenset[str]] = {}
    for uid, raw_name in name_by_id.items():
        nk = _name_match_key(raw_name)
        dates = name_to_dates.get(nk) or set()
        out[uid] = frozenset(dates)
    return out
