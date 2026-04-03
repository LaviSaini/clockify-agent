"""
Simple HTTP API: fetch Clockify data, run OpenAI analysis (prompts in agent/prompts.py), return JSON.

Run: uvicorn server:app --reload --host 127.0.0.1 --port 8000

POST /analyze uses multipart form: optional leave CSV file upload (field name: leave_file).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

load_dotenv()

from agent.runner import run_analysis
from report.excel_builder import build_excel_report
from report.text_builder import build_markdown_report

app = FastAPI(title="LogLens API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_EXCEL_NAME = re.compile(r"^loglens_report_\d{4}-\d{2}-\d{2}\.xlsx$")


def _parse_write_markdown(raw: str | None, write_excel: bool) -> bool:
    if raw is None or str(raw).strip() == "":
        return not write_excel
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/download/excel/{filename}")
def download_excel(filename: str):
    """Serve a generated report from output/ (browser download)."""
    if not _EXCEL_NAME.match(filename):
        raise HTTPException(status_code=400, detail="Invalid report filename.")
    base = Path("output").resolve()
    path = (base / filename).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path.") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(
        path,
        filename=filename,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


@app.post("/analyze")
async def analyze(
    start_date: str = Form(..., description="YYYY-MM-DD"),
    end_date: str = Form(..., description="YYYY-MM-DD"),
    leave_file: UploadFile | None = File(
        None,
        description=(
            "Optional leave requests CSV (approved rows). "
            "If omitted, uses LOGLLENS_LEAVE_CSV_PATH from .env if set."
        ),
    ),
    write_excel: bool = Form(False),
    write_markdown: str | None = Form(
        None,
        description='Omit for auto: false when write_excel is true, else true. Or "true"/"false".',
    ),
) -> JSONResponse:
    leave_csv_text: str | None = None
    if leave_file is not None:
        raw = await leave_file.read()
        if raw:
            leave_csv_text = raw.decode("utf-8-sig", errors="replace")

    write_md = _parse_write_markdown(write_markdown, write_excel)

    try:
        data: dict[str, Any] = run_analysis(
            start_date,
            end_date,
            leave_csv_text=leave_csv_text,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    excel_path: str | None = None
    markdown_path: str | None = None
    if write_excel:
        excel_path = build_excel_report(data, start_date, end_date)
    if write_md:
        markdown_path = build_markdown_report(data, start_date, end_date)

    out: dict[str, Any] = {
        "missing_logs": data.get("missing_logs", []),
        "poor_descriptions": data.get("poor_descriptions", []),
        "counts": {
            "missing_logs": len(data.get("missing_logs", [])),
            "poor_descriptions": len(data.get("poor_descriptions", [])),
        },
    }
    wu = data.get("workspace_users")
    if wu is not None:
        out["workspace_users"] = wu
        out["counts"]["workspace_users"] = len(wu)
    uem = data.get("user_email_by_name")
    if uem is not None:
        out["user_email_by_name"] = uem
    uname = data.get("user_name_by_id")
    if uname is not None:
        out["user_name_by_id"] = uname
    uemail = data.get("user_email_by_id")
    if uemail is not None:
        out["user_email_by_id"] = uemail
    wids = data.get("workspace_user_ids")
    if wids is not None:
        out["workspace_user_ids"] = wids
    th = data.get("total_hours_by_user_id")
    if th is not None:
        out["total_hours_by_user_id"] = th
    ld = data.get("leave_days_by_user_id")
    if ld is not None:
        out["leave_days_by_user_id"] = ld
    ldates = data.get("leave_dates_by_user_id")
    if ldates is not None:
        out["leave_dates_by_user_id"] = ldates
    mhpd = data.get("min_hours_per_day")
    if mhpd is not None:
        out["min_hours_per_day"] = mhpd
    if excel_path:
        out["excel_path"] = excel_path
        out["excel_filename"] = os.path.basename(excel_path)
    if markdown_path:
        out["markdown_path"] = markdown_path
    return JSONResponse(content=out)


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
