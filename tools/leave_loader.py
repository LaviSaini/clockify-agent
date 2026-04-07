"""
Load approved leave ranges from HR CSV (e.g. Zoho export) and map to Clockify user ids
via normalized employee display names.
"""

from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime, timedelta


def _normalize_person_name(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def _name_match_key(name: str) -> str:
    """Stable key so CSV vs Clockify order differs (e.g. 'Pyla Abhilash' vs 'Abhilash Pyla')."""
    toks = sorted(_normalize_person_name(name).split())
    return " ".join(toks)


def _leave_status_is_approved(status: str) -> bool:
    """
    True for approved leave rows. Tolerates typos (e.g. 'Approvved') via repeated-letter collapse.
    Excludes rejected / not approved / cancelled.
    """
    s = (status or "").strip().lower()
    if not s:
        return False
    if "not approved" in s:
        return False
    if any(x in s for x in ("rejected", "denied", "withdraw", "cancelled", "canceled")):
        return False
    if "approved" in s:
        return True
    # Typo-tolerant: e.g. "approvved" -> collapse runs -> "approved"
    collapsed = re.sub(r"(.)\1+", r"\1", s)
    return "approved" in collapsed


def _row_employee_email(row: dict[str, str]) -> str:
    """Lowercase email from common HR export column names."""
    for col in (
        "Email",
        "Employee Email",
        "Email Id",
        "Email ID",
        "Work Email",
        "Company Email",
    ):
        v = (row.get(col) or "").strip().lower()
        if v and "@" in v:
            return v
    return ""


def _row_employee_name(row: dict[str, str]) -> str:
    for col in ("Employee Name", "Employee", "Name", "Staff Name"):
        v = (row.get(col) or "").strip()
        if v:
            return v
    return ""


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


def _dict_rows_from_csv_grid(grid: list[list[str]]) -> list[dict[str, str]]:
    header_idx = None
    for i, row in enumerate(grid):
        if row and len(row) > 1 and row[0].strip() == "Employee Number":
            header_idx = i
            break
    if header_idx is None:
        return []

    headers = [h.strip() for h in grid[header_idx]]
    out: list[dict[str, str]] = []
    for row in grid[header_idx + 1 :]:
        if not row or not any((c or "").strip() for c in row):
            continue
        while len(row) < len(headers):
            row.append("")
        out.append({headers[j]: row[j].strip() for j in range(len(headers))})
    return out


def _parse_leave_csv_rows(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        grid = list(csv.reader(f))
    return _dict_rows_from_csv_grid(grid)


def parse_leave_csv_string(content: str) -> list[dict[str, str]]:
    """Parse leave CSV from file text (UTF-8 with optional BOM)."""
    text = (content or "").lstrip("\ufeff")
    grid = list(csv.reader(io.StringIO(text)))
    return _dict_rows_from_csv_grid(grid)


def _dates_in_audit_window(
    from_dt: datetime,
    to_dt: datetime,
    range_start_s: str,
    range_end_s: str,
) -> set[str]:
    """Weekdays only from leave segment intersected with audit window."""
    try:
        audit_start = datetime.strptime(range_start_s, "%Y-%m-%d")
        audit_end = datetime.strptime(range_end_s, "%Y-%m-%d")
    except ValueError:
        return set()
    if to_dt < from_dt:
        from_dt, to_dt = to_dt, from_dt
    out: set[str] = set()
    cur = from_dt.date()
    end_d = to_dt.date()
    while cur <= end_d:
        # Count only Mon-Fri leave dates for missing-day adjustments.
        if audit_start.date() <= cur <= audit_end.date() and cur.weekday() < 5:
            out.add(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def leave_dict_rows_to_dates_by_name(
    rows: list[dict[str, str]],
    range_start_s: str,
    range_end_s: str,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """
    Returns (dates_by_sorted_name_key, dates_by_lowercase_email).
    Email map is used when Clockify display name does not match CSV Employee Name.
    """
    by_name: dict[str, set[str]] = {}
    by_email: dict[str, set[str]] = {}

    for row in rows:
        if not _leave_status_is_approved(row.get("Status") or ""):
            continue

        emp_name = _row_employee_name(row)
        from_dt = _parse_leave_date(row.get("From Date") or "")
        to_dt = _parse_leave_date(row.get("To Date") or "")
        if from_dt is None or to_dt is None:
            continue

        dates = _dates_in_audit_window(from_dt, to_dt, range_start_s, range_end_s)
        if not dates:
            continue

        if emp_name:
            key = _name_match_key(emp_name)
            by_name.setdefault(key, set()).update(dates)

        em = _row_employee_email(row)
        if em:
            by_email.setdefault(em, set()).update(dates)

    return by_name, by_email


def load_leave_dates_by_normalized_name(
    path: str,
    range_start_s: str,
    range_end_s: str,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    if not path or not os.path.isfile(path):
        return {}, {}
    rows = _parse_leave_csv_rows(path)
    return leave_dict_rows_to_dates_by_name(rows, range_start_s, range_end_s)


def load_leave_dates_from_csv_content(
    content: str,
    range_start_s: str,
    range_end_s: str,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    if not (content or "").strip():
        return {}, {}
    rows = parse_leave_csv_string(content)
    return leave_dict_rows_to_dates_by_name(rows, range_start_s, range_end_s)


def build_leave_frozen_by_user_id(
    csv_path: str,
    name_by_id: dict[str, str],
    start_date: str,
    end_date: str,
    email_by_id: dict[str, str] | None = None,
) -> dict[str, frozenset[str]]:
    """Maps each Clockify user id to frozenset of YYYY-MM-DD on approved leave in range."""
    name_to_dates, email_to_dates = load_leave_dates_by_normalized_name(
        csv_path, start_date, end_date
    )
    return _dates_map_to_uid_frozen(
        name_to_dates, name_by_id, email_by_id=email_by_id, email_to_dates=email_to_dates
    )


def build_leave_frozen_by_user_id_from_content(
    csv_text: str,
    name_by_id: dict[str, str],
    start_date: str,
    end_date: str,
    email_by_id: dict[str, str] | None = None,
) -> dict[str, frozenset[str]]:
    """Same as build_leave_frozen_by_user_id but CSV body as string (e.g. uploaded file)."""
    name_to_dates, email_to_dates = load_leave_dates_from_csv_content(
        csv_text, start_date, end_date
    )
    return _dates_map_to_uid_frozen(
        name_to_dates, name_by_id, email_by_id=email_by_id, email_to_dates=email_to_dates
    )


def build_leave_frozen_by_user_id_from_bytes(
    raw: bytes,
    name_by_id: dict[str, str],
    start_date: str,
    end_date: str,
    email_by_id: dict[str, str] | None = None,
) -> dict[str, frozenset[str]]:
    text = raw.decode("utf-8-sig", errors="replace")
    return build_leave_frozen_by_user_id_from_content(
        text, name_by_id, start_date, end_date, email_by_id=email_by_id
    )


def _dates_map_to_uid_frozen(
    name_to_dates: dict[str, set[str]],
    name_by_id: dict[str, str],
    *,
    email_by_id: dict[str, str] | None = None,
    email_to_dates: dict[str, set[str]] | None = None,
) -> dict[str, frozenset[str]]:
    """
    Map HR CSV rows to Clockify user ids using sorted-token name match, then merge
    any dates matched by work email (same email as Clockify user).
    """
    email_by_id = email_by_id or {}
    email_to_dates = email_to_dates or {}
    out: dict[str, frozenset[str]] = {}
    for uid, raw_name in name_by_id.items():
        nk = _name_match_key(raw_name)
        dates = set(name_to_dates.get(nk) or ())
        em = (email_by_id.get(uid) or "").strip().lower()
        if em and em in email_to_dates:
            dates |= email_to_dates[em]
        out[uid] = frozenset(dates)
    return out
