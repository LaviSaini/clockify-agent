"""Fetch Clockify data in Python, analyze with OpenAI using prompts from agent.prompts."""

from __future__ import annotations

import json
import os
import re
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI


from agent.prompts import OPEN_AI_SYSTEM_PROMPT
from tools.analysis_tools import MIN_HOURS, detect_missing_logs
from tools.clockify_tools import get_all_users, get_projects, get_time_entries
from tools.leave_loader import build_leave_frozen_by_user_id


def _allowed_activity_terms() -> frozenset[str]:
    """
    Whole-word tokens (case-insensitive) that count as acceptable activity labels.
    Entries containing any of these are not scored 1–2 locally for brevity/vagueness,
    and are not downgraded for repeating the same text across days.
    Override with env LOGLLENS_ALLOWED_ACTIVITY_TERMS (comma-separated).
    """
    raw = os.getenv(
        "LOGLLENS_ALLOWED_ACTIVITY_TERMS",
        "standup,assignment,meeting,stand-up,Scrum call",
    )
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def _words_include_allowed(words: list[str], allowed: frozenset[str]) -> bool:
    if not allowed or not words:
        return False
    for w in words:
        core = w.strip(".,;:!?\"'()[]`").lower()
        if core in allowed:
            return True
    return False


def _description_tokens_include_allowed(description: str, allowed: frozenset[str]) -> bool:
    text = (description or "").strip()
    if not text:
        return False
    words = [w for w in re.split(r"\s+", text) if w]
    return _words_include_allowed(words, allowed)


def _user_id_str(u: dict) -> str | None:
    uid = u.get("id")
    if uid is None:
        return None
    s = str(uid).strip()
    return s or None


def _total_hours_by_user(time_entries_by_user: dict[str, list]) -> dict[str, float]:
    """Sum logged hours per user for the fetched date range (from Clockify entries)."""
    out: dict[str, float] = {}
    for uid, entries in time_entries_by_user.items():
        total = 0.0
        for e in entries:
            try:
                total += float(e.get("hours") or 0)
            except (TypeError, ValueError):
                pass
        out[uid] = round(total, 2)
    return out


def _roster_maps(users: list) -> tuple[dict[str, str], dict[str, str], list[str]]:
    name_by_id: dict[str, str] = {}
    email_by_id: dict[str, str] = {}
    ordered_ids: list[str] = []
    for u in users:
        uid = _user_id_str(u)
        if not uid:
            continue
        ordered_ids.append(uid)
        name_by_id[uid] = (u.get("name") or "").strip()
        email_by_id[uid] = (u.get("email") or "").strip()
    return name_by_id, email_by_id, ordered_ids


def _openai_model_name() -> str:
    """Model id if LLM pass is enabled; empty string skips OpenAI (local scores only)."""
    skip = os.getenv("LOGLLENS_SKIP_OPENAI", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if skip:
        return ""
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


def _fetch_and_detect_for_user(
    index: int,
    u: dict,
    start_date: str,
    end_date: str,
    project_by_id: dict,
    leave_by_uid: dict[str, frozenset[str]],
) -> tuple[int, str | None, list, list]:
    uid_str = _user_id_str(u)
    raw_name = (u.get("name") or "").strip()
    if not uid_str:
        print("Skipping Clockify user with no id:", u.get("email"), u.get("name"))
        return index, None, [], []

    try:
        entries = get_time_entries(u.get("id"), start_date, end_date)
        for e in entries:
            e["project"] = project_by_id.get(
                e.get("project_id") or "", ""
            ) or ""
    except Exception as e:
        print(f"Error fetching time entries for user {uid_str}: {e}")
        traceback.print_exc()
        return index, uid_str, [], []

    try:
        leave_dates = leave_by_uid.get(uid_str) or frozenset()
        missing = detect_missing_logs(
            raw_name,
            uid_str,
            entries,
            start_date,
            end_date,
            leave_dates=leave_dates,
        )
    except Exception as e:
        print(f"Error detecting missing logs for user {uid_str}: {e}")
        traceback.print_exc()
        missing = []

    return index, uid_str, entries, missing


def gather_payload(
    start_date: str,
    end_date: str,
    leave_csv_path: str | None = None,
) -> dict:
    try:
        users = get_all_users()
    except Exception as e:
        print("Error fetching users:", e)
        return {}

    try:
        projects = get_projects()
        project_by_id = {p["id"]: p["name"] for p in projects}
    except Exception as e:
        print("Error fetching projects:", e)
        projects = []
        project_by_id = {}

    time_entries_by_user: dict[str, list] = {}
    missing_logs: list = []
    name_by_id, email_by_id, workspace_user_ids = _roster_maps(users)

    leave_csv = (leave_csv_path or "").strip() or os.getenv(
        "LOGLLENS_LEAVE_CSV_PATH", ""
    ).strip()
    leave_by_uid = (
        build_leave_frozen_by_user_id(leave_csv, name_by_id, start_date, end_date)
        if leave_csv
        else {}
    )

    # Default 1: Clockify rate-limits hard; raise CLOCKIFY_FETCH_CONCURRENCY only if your plan allows.
    conc = int(os.getenv("CLOCKIFY_FETCH_CONCURRENCY", "1"))
    conc = max(1, min(conc, 16))
    max_workers = min(conc, max(1, len(users)))
    indexed: dict[int, tuple[str | None, list, list]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                _fetch_and_detect_for_user,
                i,
                u,
                start_date,
                end_date,
                project_by_id,
                leave_by_uid,
            )
            for i, u in enumerate(users)
        ]
        for fut in as_completed(futures):
            i, uid_str, entries, missing = fut.result()
            indexed[i] = (uid_str, entries, missing)

    for i in range(len(users)):
        uid_str, entries, missing = indexed[i]
        if not uid_str:
            continue
        time_entries_by_user[uid_str] = entries
        missing_logs.extend(missing)

    total_hours_by_user_id = _total_hours_by_user(time_entries_by_user)

    return {
        "users": users,
        "projects": projects,
        "time_entries_by_user": time_entries_by_user,
        "missing_logs": missing_logs,
        "user_name_by_id": name_by_id,
        "user_email_by_id": email_by_id,
        "workspace_user_ids": workspace_user_ids,
        "total_hours_by_user_id": total_hours_by_user_id,
        "min_hours_per_day": MIN_HOURS,
    }


def _workspace_user_names(payload: dict) -> list[str]:
    """Stable user ids in Clockify member order (for summary / API)."""
    return list(payload.get("workspace_user_ids") or [])


def _user_email_by_name(payload: dict) -> dict[str, str]:
    """Maps user id -> email (kept for response key name compatibility)."""
    return dict(payload.get("user_email_by_id") or {})


def _slim_entries_for_llm(entries_by_user: dict[str, list]) -> dict[str, list]:
    """Minimal fields for the LLM to cut input tokens (ids/hours are irrelevant for text quality)."""
    out: dict[str, list] = {}
    for user, entries in entries_by_user.items():
        out[user] = [
            {
                "date": e.get("date", ""),
                "project": e.get("project", ""),
                "description": e.get("description", ""),
            }
            for e in entries
        ]
    return out


def _score_description(description: str) -> tuple[int, str]:
    text = (description or "").strip()
    if not text:
        return 1, "Blank or empty description."

    words = [w for w in re.split(r"\s+", text) if w]
    allowed = _allowed_activity_terms()
    if _words_include_allowed(words, allowed):
        if len(words) == 1:
            return 3, "Standard activity label (allowlisted term)."
        if len(words) < 10:
            return 3, "Activity note includes allowlisted term."
        return 4, "Reasonably clear description."

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

    name_by_id = payload.get("user_name_by_id") or {}

    allowed = _allowed_activity_terms()

    for user_id, entries in payload.get("time_entries_by_user", {}).items():
        raw_name = (name_by_id.get(user_id) or "").strip()
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
            if (
                desc
                and desc.lower() in repeated
                and not _description_tokens_include_allowed(desc, allowed)
            ):
                # Same text on multiple days → poor, unless it uses an allowlisted activity term.
                repeated_note = " Repeated across multiple days."
                score = min(score, 2)

            if score <= 2:
                poor_descriptions.append(
                    {
                        "user_id": user_id,
                        "user": raw_name,
                        "date": entry.get("date", ""),
                        "project": entry.get("project", ""),
                        "description": desc,
                        "score": score,
                        "reason": f"{reason}{repeated_note}".strip(),
                    }
                )
            elif not _description_tokens_include_allowed(desc, allowed):
                # Allowlisted activity terms stay local-only so the LLM does not re-flag them.
                time_entries_to_llm_by_user.setdefault(user_id, []).append(entry)

    return poor_descriptions, time_entries_to_llm_by_user


def _merge_poor_descriptions(
    local_poor: list[dict], llm_poor: list[dict]
) -> list[dict]:
    """
    Merge lists without losing entries. If the same entry appears in both,
    keep the LLM version (it should be at least as informative).
    """
    def _key(d: dict) -> tuple:
        uid = (d.get("user_id") or "").strip()
        if not uid:
            uid = (d.get("user") or "").strip()
        return (
            uid,
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


def _normalize_poor_description_rows(rows: list[dict], name_by_id: dict[str, str]) -> None:
    """Ensure user_id + user (raw name) after LLM merge; LLM puts Clockify id in user."""
    for row in rows:
        uid = (row.get("user_id") or "").strip()
        ufield = (row.get("user") or "").strip()
        if uid:
            row["user"] = name_by_id.get(uid, row.get("user") or "")
            continue
        if ufield in name_by_id:
            row["user_id"] = ufield
            row["user"] = name_by_id[ufield]
        elif ufield:
            row["user_id"] = ufield
            row["user"] = name_by_id.get(ufield, "")


def run_analysis(
    start_date: str,
    end_date: str,
    leave_csv_path: str | None = None,
) -> dict:
    model_name = _openai_model_name()
    payload = gather_payload(start_date, end_date, leave_csv_path=leave_csv_path)

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
            "workspace_users": _workspace_user_names(payload),
            "user_email_by_name": _user_email_by_name(payload),
            "user_name_by_id": payload.get("user_name_by_id") or {},
            "user_email_by_id": payload.get("user_email_by_id") or {},
            "workspace_user_ids": payload.get("workspace_user_ids") or [],
            "total_hours_by_user_id": payload.get("total_hours_by_user_id") or {},
            "min_hours_per_day": payload.get("min_hours_per_day", MIN_HOURS),
        }

    # 3) Minimal LLM payload: only borderline entries, compact JSON, no missing_logs/users/projects.
    llm_body = {
        "time_entries_by_user": _slim_entries_for_llm(entries_to_llm_by_user),
    }
    user_message = (
        f"Date range:{start_date} to {end_date}. "
        f"JSON:{json.dumps(llm_body, ensure_ascii=False, separators=(',', ':'))}"
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
            temperature=0,
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
        _normalize_poor_description_rows(merged_poor, payload.get("user_name_by_id") or {})

        return {
            "missing_logs": payload["missing_logs"],
            "poor_descriptions": merged_poor,
            "workspace_users": _workspace_user_names(payload),
            "user_email_by_name": _user_email_by_name(payload),
            "user_name_by_id": payload.get("user_name_by_id") or {},
            "user_email_by_id": payload.get("user_email_by_id") or {},
            "workspace_user_ids": payload.get("workspace_user_ids") or [],
            "total_hours_by_user_id": payload.get("total_hours_by_user_id") or {},
            "min_hours_per_day": payload.get("min_hours_per_day", MIN_HOURS),
        }
    except Exception as exc:
        print(f"[runner] OpenAI analysis failed, using local scores only: {exc}")
        return {
            "missing_logs": payload["missing_logs"],
            "poor_descriptions": local_poor_descriptions,
            "workspace_users": _workspace_user_names(payload),
            "user_email_by_name": _user_email_by_name(payload),
            "user_name_by_id": payload.get("user_name_by_id") or {},
            "user_email_by_id": payload.get("user_email_by_id") or {},
            "workspace_user_ids": payload.get("workspace_user_ids") or [],
            "total_hours_by_user_id": payload.get("total_hours_by_user_id") or {},
            "min_hours_per_day": payload.get("min_hours_per_day", MIN_HOURS),
        }
