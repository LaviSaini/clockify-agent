"""Fetch Clockify data in Python, analyze with OpenAI using prompts from agent.prompts."""

from __future__ import annotations

import json
import os
import re

from openai import OpenAI


from agent.prompts import OPEN_AI_SYSTEM_PROMPT
from tools.analysis_tools import detect_missing_logs
from tools.clockify_tools import get_all_users, get_projects, get_time_entries


def _configure_openai() -> str:
    api_key = os.getenv("OPEN_AI_API_KEY", "").strip()
    if not api_key:
        return ""
    return os.getenv("OPEN_AI_MODEL", "gpt-4o-mini").strip()


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("OpenAI did not return a JSON object.")
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


def _score_description(description: str) -> tuple[int, str]:
    text = (description or "").strip()
    if not text:
        return 1, "Blank or empty description."

    words = [w for w in re.split(r"\s+", text) if w]
    lower = text.lower()
    vague_terms = {
        "work",
        "task",
        "meeting",
        "misc",
        "update",
        "support",
        "call",
        "dev",
    }

    if len(words) == 1:
        return 2, "Single-word description."
    if len(words) < 4 or (len(words) < 10 and any(t in lower for t in vague_terms)):
        return 2, "Too short/vague; lacks specific task context."
    if len(words) < 10:
        return 3, "Basic activity noted but lacks clear outcome context."
    return 4, "Reasonably clear description."


# def _analyze_poor_descriptions_locally(payload: dict) -> list[dict]:
#     poor_descriptions, _ = _score_entries_locally(payload)
#     return poor_descriptions


def _score_entries_locally(payload: dict) -> tuple[list[dict], dict[str, list]]:
    """
    Scores each time entry's description locally using the same rubric logic.

    Returns:
      - poor_descriptions: entries with local score in {1,2}
      - time_entries_to_llm_by_user: entries with local score NOT in {1,2}
    """
    poor_descriptions: list[dict] = []
    time_entries_to_llm_by_user: dict[str, list] = {}

    for user, entries in payload.get("time_entries_by_user", {}).items():
        # Detect copy-pasted descriptions for that user across multiple days.
        by_desc: dict[str, set[str]] = {}
        for entry in entries:
            desc = (entry.get("description") or "").strip()
            if desc:
                by_desc.setdefault(desc.lower(), set()).add(entry.get("date", ""))
        repeated = {d for d, dates in by_desc.items() if len(dates) >= 2}

        for entry in entries:
            desc = (entry.get("description") or "").strip()
            score, reason = _score_description(desc)

            repeated_note = ""
            if desc and desc.lower() in repeated:
                # If repeated across days, downgrade to poor quality.
                repeated_note = " Repeated across multiple days."
                score = min(score, 2)

            if score <= 2:
                poor_descriptions.append(
                    {
                        "user": user,
                        "date": entry.get("date", ""),
                        "project": entry.get("project", ""),
                        "description": desc,
                        "score": score,
                        "reason": f"{reason}{repeated_note}".strip(),
                    }
                )
            else:
                time_entries_to_llm_by_user.setdefault(user, []).append(entry)

    return poor_descriptions, time_entries_to_llm_by_user


def _merge_poor_descriptions(
    local_poor: list[dict], llm_poor: list[dict]
) -> list[dict]:
    """
    Merge lists without losing entries. If the same entry appears in both,
    keep the LLM version (it should be at least as informative).
    """
    def _key(d: dict) -> tuple:
        return (
            (d.get("user") or ""),
            (d.get("date") or ""),
            (d.get("project") or ""),
            (d.get("description") or ""),
        )

    merged: list[dict] = []
    index_by_key: dict[tuple, int] = {}

    for item in local_poor:
        k = _key(item)
        if k in index_by_key:
            continue
        index_by_key[k] = len(merged)
        merged.append(item)

    for item in llm_poor:
        k = _key(item)
        if k in index_by_key:
            merged[index_by_key[k]] = item
        else:
            index_by_key[k] = len(merged)
            merged.append(item)

    return merged


def run_analysis(start_date: str, end_date: str) -> dict:
    model_name = _configure_openai()
    payload = gather_payload(start_date, end_date)

    # 1) Local pre-scan first.
    #    - local_poor_descriptions: score in {1,2}
    #    - entries_to_llm_by_user: score not in {1,2}
    local_poor_descriptions, entries_to_llm_by_user = _score_entries_locally(payload)

    # 2) Only call OpenAI if:
    #    - OpenAI is configured (API key present)
    #    - there is at least one entry to analyze with the model
    has_entries_to_llm = any(entries for entries in entries_to_llm_by_user.values())
    if not model_name or not has_entries_to_llm:
        return {
            "missing_logs": payload["missing_logs"],
            "poor_descriptions": local_poor_descriptions,
        }

    # 3) Build a filtered payload for the LLM (so we don't waste tokens).
    filtered_payload = dict(payload)
    filtered_payload["time_entries_by_user"] = entries_to_llm_by_user

    user_message = (
        f"Date range: {start_date} to {end_date}.\n\n"
        f"Data (JSON):\n{json.dumps(filtered_payload, ensure_ascii=False, indent=2)}"
    )

    # model = OpenAI.GenerativeModel(
    #     model_name,
    #     system_instruction=OPEN_AI_SYSTEM_PROMPT,
    # )
    print(f"Sending data to OpenAI model {model_name} for analysis...")
    try:
        client = OpenAI(api_key=os.getenv("OPEN_AI_API_KEY"))
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": OPEN_AI_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
        )
        choice = response.choices[0] if response.choices else None
        raw = (choice.message.content if choice and choice.message else "") or ""
        raw = raw.strip()
        if not raw:
            raise RuntimeError("OpenAI returned empty content.")

        llm_result = _extract_json_object(raw)

        llm_result["missing_logs"] = payload["missing_logs"]

        llm_poor = llm_result.get("poor_descriptions", [])
        if not isinstance(llm_poor, list):
            llm_poor = []

        merged_poor = _merge_poor_descriptions(local_poor_descriptions, llm_poor)

        return {
            "missing_logs": payload["missing_logs"],
            "poor_descriptions": merged_poor,
        }
    except Exception as exc:
        print(f"[runner] OpenAI analysis failed, using local scores only: {exc}")
        return {
            "missing_logs": payload["missing_logs"],
            "poor_descriptions": local_poor_descriptions,
        }
