from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime

import openpyxl
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill

RED = PatternFill("solid", fgColor="FFCCCC")
AMBER = PatternFill("solid", fgColor="FFF2CC")
BOLD = Font(bold=True)


def _append_header_row(ws, values: list) -> None:
    row = []
    for v in values:
        c = WriteOnlyCell(ws, v)
        c.font = BOLD
        row.append(c)
    ws.append(row)


def _append_filled_row(ws, values: list, fill: PatternFill) -> None:
    row = []
    for v in values:
        c = WriteOnlyCell(ws, v)
        c.fill = fill
        row.append(c)
    ws.append(row)


def _email_for_user(data: dict, user: str | None) -> str:
    if not user:
        return ""
    return (data.get("user_email_by_name") or {}).get(user, "") or ""


def build_excel_report(data: dict, start_date: str, end_date: str) -> str:
    wb = openpyxl.Workbook(write_only=True)

    # ── Sheet 1: Summary ──────────────────────────────────────────────────────
    ws1 = wb.create_sheet("Summary")
    _append_header_row(
        ws1, ["User", "Email", "Missing Days", "Incomplete Days", "Flagged Entries"]
    )

    missing_count = defaultdict(lambda: {"Missing": 0, "Incomplete": 0})
    for row in data.get("missing_logs", []):
        missing_count[row["user"]][row["severity"]] += 1

    desc_count = defaultdict(int)
    for row in data.get("poor_descriptions", []):
        desc_count[row["user"]] += 1

    # One Summary row per workspace member (same order as Clockify user list). Users with no issues show zeros.
    users_for_summary = data.get("workspace_users")
    if not users_for_summary:
        issue_users = set(missing_count.keys()) | set(desc_count.keys())
        users_for_summary = sorted(issue_users, key=lambda x: x or "")

    for user in users_for_summary:
        ws1.append(
            [
                user,
                _email_for_user(data, user),
                missing_count[user]["Missing"],
                missing_count[user]["Incomplete"],
                desc_count[user],
            ]
        )

    # ── Sheet 2: Missing Logs ─────────────────────────────────────────────────
    ws2 = wb.create_sheet("Missing Logs")
    _append_header_row(
        ws2, ["User", "Email", "Date", "Day", "Hours Logged", "Severity"]
    )

    for row in data.get("missing_logs", []):
        fill = RED if row["severity"] == "Missing" else AMBER
        u = row.get("user")
        _append_filled_row(
            ws2,
            [
                u,
                _email_for_user(data, u),
                row["date"],
                row["day"],
                row["hours_logged"],
                row["severity"],
            ],
            fill,
        )

    # ── Sheet 3: Poor Descriptions ────────────────────────────────────────────
    ws3 = wb.create_sheet("Poor Descriptions")
    _append_header_row(
        ws3, ["User", "Email", "Date", "Project", "Description", "Score", "Reason"]
    )

    for row in data.get("poor_descriptions", []):
        fill = RED if row["score"] == 1 else AMBER
        u = row.get("user")
        _append_filled_row(
            ws3,
            [
                u,
                _email_for_user(data, u),
                row["date"],
                row.get("project", ""),
                row["description"],
                row["score"],
                row["reason"],
            ],
            fill,
        )

    # ── Save ──────────────────────────────────────────────────────────────────
    os.makedirs("output", exist_ok=True)
    filename = f"output/loglens_report_{datetime.today().strftime('%Y-%m-%d')}.xlsx"
    wb.save(filename)
    print(f"Report saved -> {filename}")
    return filename
