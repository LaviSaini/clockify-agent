"""
Simple HTTP API: fetch Clockify data, run OpenAI analysis (prompts in agent/prompts.py), return JSON.

Run: uvicorn server:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv()

from agent.runner import run_analysis
from report.excel_builder import build_excel_report
from report.text_builder import build_markdown_report

app = FastAPI(title="LogLens API", version="0.1.0")


class AnalyzeBody(BaseModel):
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    write_excel: bool = Field(False, description="If true, also write output/loglens_report_*.xlsx")
    write_markdown: bool = Field(
        True,
        description="If true, also write output/loglens_summary_*.md",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze")
def analyze(body: AnalyzeBody) -> JSONResponse:
    try:
        data: dict[str, Any] = run_analysis(body.start_date, body.end_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    excel_path: str | None = None
    markdown_path: str | None = None
    if body.write_excel:
        excel_path = build_excel_report(data, body.start_date, body.end_date)
    if body.write_markdown:
        markdown_path = build_markdown_report(data, body.start_date, body.end_date)

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
    if excel_path:
        out["excel_path"] = excel_path
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
