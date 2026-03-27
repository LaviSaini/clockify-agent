"""
Fetch Clockify time entries, run LLM analysis, write Markdown + Word under reports/.

Usage (from repo root, after .env and venv):
  python -m src.run_pipeline --start 2025-03-01 --end 2025-03-31 --user-email someone@company.com
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.clockify_client import ClockifyClient, format_entries_for_prompt
from src.llm_client import complete_analysis
from src.reports import project_root, write_docx, write_markdown

load_dotenv(project_root() / ".env")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _load_system_prompt() -> str:
    path = project_root() / "prompts" / "analysis_system.md"
    if not path.is_file():
        raise FileNotFoundError(f"Missing prompt file: {path}")
    return path.read_text(encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Clockify to LLM report pipeline")
    p.add_argument("--start", required=True, help="Start date (YYYY-MM-DD), UTC window")
    p.add_argument("--end", required=True, help="End date (YYYY-MM-DD), inclusive UTC window")
    p.add_argument(
        "--user-email",
        default="",
        help="Workspace user email to analyze (required unless CLOCKIFY_USER_ID is set)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch Clockify data and print prompt size; do not call the LLM",
    )
    args = p.parse_args()

    import os

    api_key = os.environ.get("CLOCKIFY_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Set CLOCKIFY_API_KEY in .env (see .env.example).")

    start_d = _parse_date(args.start)
    end_d = _parse_date(args.end)
    start_dt = datetime.combine(start_d, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_d, time.max, tzinfo=timezone.utc)

    client = ClockifyClient(api_key)
    ws_id = os.environ.get("CLOCKIFY_WORKSPACE_ID", "").strip()
    if not ws_id:
        workspaces = client.list_workspaces()
        if not workspaces:
            raise SystemExit("No Clockify workspaces found for this API key.")
        ws_id = workspaces[0].id

    user_id = os.environ.get("CLOCKIFY_USER_ID", "").strip()
    user_email = (args.user_email or os.environ.get("CLOCKIFY_USER_EMAIL", "")).strip()
    if not user_id:
        if not user_email:
            raise SystemExit("Provide --user-email or set CLOCKIFY_USER_EMAIL / CLOCKIFY_USER_ID.")
        u = client.find_user_by_email(ws_id, user_email)
        if not u:
            raise SystemExit(f"No user matched email {user_email!r} in workspace.")
        user_id = u.id
        display_name = u.name or u.email
    else:
        display_name = user_email or user_id

    entries = client.get_time_entries(ws_id, user_id, start_dt, end_dt)
    entries_text = format_entries_for_prompt(entries)

    user_block = (
        f"Workspace ID: {ws_id}\n"
        f"User: {display_name}\n"
        f"Range (UTC): {start_d.isoformat()} .. {end_d.isoformat()}\n"
        f"Entry count: {len(entries)}\n\n"
        f"## Raw time entries\n\n{entries_text}"
    )

    if args.dry_run:
        print(user_block[:8000])
        if len(user_block) > 8000:
            print("\n... truncated for dry-run ...")
        return

    system_prompt = _load_system_prompt()
    report_body = complete_analysis(system_prompt, user_block)
    title = f"Time tracking review — {display_name} ({start_d} to {end_d})"
    md_path = write_markdown(title, report_body)
    docx_path = write_docx(title, report_body)
    print(f"Wrote {md_path}")
    print(f"Wrote {docx_path}")


if __name__ == "__main__":
    main()
