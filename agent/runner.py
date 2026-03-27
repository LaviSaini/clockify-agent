"""Fetch Clockify data in Python, analyze with Gemini using prompts from agent.prompts."""

from __future__ import annotations

import json
import os
import re

import google.generativeai as genai

from agent.prompts import GEMINI_SYSTEM_PROMPT
from tools.analysis_tools import detect_missing_logs
from tools.clockify_tools import get_all_users, get_projects, get_time_entries


def _configure_gemini() -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")
    genai.configure(api_key=api_key)
    return os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("Gemini did not return a JSON object.")
    return json.loads(m.group(0))


def gather_payload(start_date: str, end_date: str) -> dict:
    users = get_all_users()
    projects = get_projects()
    project_by_id = {p["id"]: p["name"] for p in projects}

    time_entries_by_user: dict[str, list] = {}
    missing_logs: list = []

    for u in users:
        uid, name = u["id"], u["name"]
        entries = get_time_entries(uid, start_date, end_date)
        for e in entries:
            e["project"] = project_by_id.get(e.get("project_id") or "", "") or ""
        time_entries_by_user[name] = entries
        missing_logs.extend(
            detect_missing_logs(name, entries, start_date, end_date)
        )

    return {
        "users": users,
        "projects": projects,
        "time_entries_by_user": time_entries_by_user,
        "missing_logs": missing_logs,
    }


def run_analysis(start_date: str, end_date: str) -> dict:
    model_name = _configure_gemini()
    payload = gather_payload(start_date, end_date)

    user_message = (
        f"Date range: {start_date} to {end_date}.\n\n"
        f"Data (JSON):\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )

    model = genai.GenerativeModel(
        model_name,
        system_instruction=GEMINI_SYSTEM_PROMPT,
    )
    response = model.generate_content(
        user_message,
        generation_config={"temperature": 0.2},
    )
    raw = (response.text or "").strip()
    if not raw:
        raise RuntimeError("Gemini returned empty content.")

    result = _extract_json_object(raw)

    # Ensure missing_logs stay aligned with Python audit if model drifted
    result["missing_logs"] = payload["missing_logs"]

    if "poor_descriptions" not in result or not isinstance(result["poor_descriptions"], list):
        result["poor_descriptions"] = []

    return result
