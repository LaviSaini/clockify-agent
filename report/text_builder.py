from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime


def _fmt_pct(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.0%"
    return f"{(numerator / denominator) * 100:.1f}%"


def _group_id(row: dict) -> str:
    return ((row.get("user_id") or row.get("user") or "") or "").strip() or "__unknown__"


def _markdown_label(uid: str, data: dict) -> str:
    name = ((data.get("user_name_by_id") or {}).get(uid, "") or "").strip()
    if name:
        return name
    email = ((data.get("user_email_by_id") or {}).get(uid, "") or "").strip()
    if email:
        return email
    if uid and uid != "__unknown__":
        return uid
    return "Unknown"


def build_markdown_report(data: dict, start_date: str, end_date: str) -> str:
    missing_logs = data.get("missing_logs", [])
    poor_descriptions = data.get("poor_descriptions", [])

    by_user = defaultdict(
        lambda: {
            "missing_days": 0,
            "incomplete_days": 0,
            "poor_descriptions": 0,
            "score1": 0,
            "score2": 0,
        }
    )

    for row in missing_logs:
        uid = _group_id(row)
        sev = row.get("severity", "")
        if sev == "Missing":
            by_user[uid]["missing_days"] += 1
        elif sev == "Incomplete":
            by_user[uid]["incomplete_days"] += 1

    for row in poor_descriptions:
        uid = _group_id(row)
        by_user[uid]["poor_descriptions"] += 1
        score = int(row.get("score", 0) or 0)
        if score == 1:
            by_user[uid]["score1"] += 1
        elif score == 2:
            by_user[uid]["score2"] += 1

    total_missing_days = sum(v["missing_days"] for v in by_user.values())
    total_incomplete_days = sum(v["incomplete_days"] for v in by_user.values())
    total_quality_issues = sum(v["poor_descriptions"] for v in by_user.values())
    total_critical_quality = sum(v["score1"] for v in by_user.values())
    total_users = len(by_user)

    ranked_users = sorted(
        by_user.items(),
        key=lambda item: (
            item[1]["missing_days"] + item[1]["incomplete_days"],
            item[1]["poor_descriptions"],
        ),
        reverse=True,
    )

    lines: list[str] = []
    lines.append("# LogLens Clockify Audit Report")
    lines.append("")
    lines.append(f"**Date range:** {start_date} to {end_date}")
    lines.append(f"**Generated at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(
        f"- Team members with findings: **{total_users}**"
    )
    lines.append(f"- Missing log days: **{total_missing_days}**")
    lines.append(f"- Incomplete log days: **{total_incomplete_days}**")
    lines.append(f"- Poor description entries: **{total_quality_issues}**")
    lines.append(
        f"- Critical description issues (score=1): **{total_critical_quality}** "
        f"({_fmt_pct(total_critical_quality, total_quality_issues)})"
    )
    lines.append("")

    lines.append("## User-wise Breakdown")
    if not ranked_users:
        lines.append("- No issues found in the selected date range.")
    else:
        for uid, stats in ranked_users:
            label = _markdown_label(uid, data)
            lines.append(
                "- "
                f"**{label}**: {stats['missing_days']} missing, "
                f"{stats['incomplete_days']} incomplete, "
                f"{stats['poor_descriptions']} poor descriptions "
                f"(score1={stats['score1']}, score2={stats['score2']})"
            )
    lines.append("")

    os.makedirs("output", exist_ok=True)
    filename = f"output/loglens_summary_{datetime.today().strftime('%Y-%m-%d')}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Markdown report saved -> {filename}")
    return filename
