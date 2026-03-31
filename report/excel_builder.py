import os
from collections import defaultdict
from datetime import datetime
import openpyxl
from openpyxl.styles import PatternFill, Font

RED   = PatternFill("solid", fgColor="FFCCCC")
AMBER = PatternFill("solid", fgColor="FFF2CC")
BOLD  = Font(bold=True)


def build_excel_report(data: dict, start_date: str, end_date: str) -> str:
    wb = openpyxl.Workbook()

    # ── Sheet 1: Summary ──────────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Summary"
    ws1.append(["User", "Missing Days", "Incomplete Days", "Flagged Entries"])
    for cell in ws1[1]:
        cell.font = BOLD

    missing_count = defaultdict(lambda: {"Missing": 0, "Incomplete": 0})
    for row in data.get("missing_logs", []):
        missing_count[row["user"]][row["severity"]] += 1

    desc_count = defaultdict(int)
    for row in data.get("poor_descriptions", []):
        desc_count[row["user"]] += 1

    all_users = set(list(missing_count.keys()) + list(desc_count.keys()))
    for user in sorted(all_users, key=lambda x: x or ""):        
        ws1.append([
            user,
            missing_count[user]["Missing"],
            missing_count[user]["Incomplete"],
            desc_count[user],
        ])

    # ── Sheet 2: Missing Logs ─────────────────────────────────────────────────
    ws2 = wb.create_sheet("Missing Logs")
    ws2.append(["User", "Date", "Day", "Hours Logged", "Severity"])
    for cell in ws2[1]:
        cell.font = BOLD

    for row in data.get("missing_logs", []):
        ws2.append([
            row["user"], row["date"], row["day"],
            row["hours_logged"], row["severity"],
        ])
        fill = RED if row["severity"] == "Missing" else AMBER
        for cell in ws2[ws2.max_row]:
            cell.fill = fill

    # ── Sheet 3: Poor Descriptions ────────────────────────────────────────────
    ws3 = wb.create_sheet("Poor Descriptions")
    ws3.append(["User", "Date", "Project", "Description", "Score", "Reason"])
    for cell in ws3[1]:
        cell.font = BOLD

    for row in data.get("poor_descriptions", []):
        ws3.append([
            row["user"], row["date"], row.get("project", ""),
            row["description"], row["score"], row["reason"],
        ])
        fill = RED if row["score"] == 1 else AMBER
        for cell in ws3[ws3.max_row]:
            cell.fill = fill

    # ── Save ──────────────────────────────────────────────────────────────────
    os.makedirs("output", exist_ok=True)
    filename = f"output/loglens_report_{datetime.today().strftime('%Y-%m-%d')}.xlsx"
    wb.save(filename)
    print(f"Report saved → {filename}")
    return filename
