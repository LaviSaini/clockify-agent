import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

import requests

BASE_URL = "https://api.clockify.me/api/v1"

_pace_lock = threading.Lock()
_last_request_end: float = 0.0


def _debug_enabled() -> bool:
    return os.getenv("CLOCKIFY_DEBUG", "1").strip().lower() in {"1", "true", "yes", "on"}


def _log(message: str) -> None:
    if _debug_enabled():
        print(f"[clockify] {message}")


def _headers():
    return {"X-Api-Key": os.getenv("CLOCKIFY_API_KEY")}


def _pace_before_request() -> None:
    """Global spacing between Clockify API calls (all threads share one limiter)."""
    gap = float(os.getenv("CLOCKIFY_MIN_REQUEST_INTERVAL_SEC", "0.35"))
    if gap <= 0:
        return
    global _last_request_end
    with _pace_lock:
        now = time.monotonic()
        wait = _last_request_end + gap - now
        if wait > 0:
            time.sleep(wait)
        _last_request_end = time.monotonic()


def _request_get_with_retry(
    url: str,
    *,
    params: Optional[dict] = None,
    attempts: int = 12,
) -> requests.Response:
    """GET; pace every attempt; retry 429/503 with Retry-After or backoff."""
    headers = _headers()
    last_response: Optional[requests.Response] = None
    for attempt in range(attempts):
        _pace_before_request()
        last_response = requests.get(url, headers=headers, params=params, timeout=90)
        if last_response.status_code in (429, 503):
            ra = last_response.headers.get("Retry-After")
            try:
                delay = float(ra) if ra is not None else max(2.0**min(attempt, 6), 2.0)
            except ValueError:
                delay = max(2.0**min(attempt, 6), 2.0)
            delay = min(max(delay, 1.0), 120.0)
            _log(
                f"HTTP {last_response.status_code} on GET; sleeping {delay:.1f}s "
                f"(attempt {attempt + 1}/{attempts})"
            )
            time.sleep(delay)
            continue
        last_response.raise_for_status()
        return last_response
    if last_response is not None:
        last_response.raise_for_status()
    raise RuntimeError("Clockify GET failed after retries")


def _get_json_with_retry(url: str, *, params: Optional[dict] = None, attempts: int = 12) -> Any:
    return _request_get_with_retry(url, params=params, attempts=attempts).json()


def _time_entries_array_from_body(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("timeEntries", "timeentries", "entries", "data"):
            inner = data.get(key)
            if isinstance(inner, list):
                return inner
    return []


def _agent_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "agent_config.json"

def _excluded_emails_from_agent_config() -> frozenset[str]:
    """
    Reads excluded_emails from config/agent_config.json (JSON array of strings).
    Override path with LOGLLENS_AGENT_CONFIG_PATH.
    """
    path = _agent_config_path()
    if not path.is_file():
        return frozenset()

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _log(f"agent_config unreadable ({path}): {e}")
        return frozenset()

    if not isinstance(data, dict):
        _log(f"agent_config must be a JSON object: {path}")
        return frozenset()

    emails = data.get("excluded_emails")
    if emails is None:
        return frozenset()
    if not isinstance(emails, list):
        _log(f"agent_config excluded_emails must be an array: {path}")
        return frozenset()

    return frozenset(
        e.strip().lower() for e in emails if isinstance(e, str) and e.strip()
    )

def _workspace_id() -> str:
    wid = os.getenv("CLOCKIFY_WORKSPACE_ID", "").strip()
    if wid:
        _log(f"Using workspace from .env: {wid}")
        return wid
    url = f"{BASE_URL}/workspaces"
    _log("Fetching workspaces from Clockify API")
    data = _get_json_with_retry(url)
    if not data:
        raise RuntimeError("No Clockify workspaces for this API key.")
    if not isinstance(data, list):
        raise RuntimeError("Unexpected workspaces response.")
    _log(f"Workspace auto-detected: {data[0]['id']}")
    return data[0]["id"]


def fetch_all_users(page: int = 1, page_size: int = 50):
    workspace_id = _workspace_id()
    url = f"{BASE_URL}/workspaces/{workspace_id}/users"
    return _request_get_with_retry(
        url,
        params={"page": page, "page-size": page_size},
    )


def get_all_users() -> list:
    """Returns all members of the workspace."""

    final_users_data = []
    page = 1
    page_size = 50

    while True:
        response = fetch_all_users(page, page_size)
        data = response.json()

        users_list = data if isinstance(data, list) else data.get("users", [])

        users = [
            {"id": u["id"], "name": u["name"], "email": u["email"]}
            for u in users_list
        ]

        final_users_data.extend(users)

        last_page = response.headers.get("Last-Page", "false")

        if last_page == "true":
            break

        page += 1

    excluded = _excluded_emails_from_agent_config()
    if excluded:
        before = len(final_users_data)
        final_users_data = [
            u
            for u in final_users_data
            if (u.get("email") or "").strip().lower() not in excluded
        ]
        dropped = before - len(final_users_data)
        if dropped:
            _log(
                f"CLOCKIFY exclude emails (env + agent_config excluded_emails): skipped {dropped} user(s), "
                f"{len(final_users_data)} remaining"
            )

    print(len(final_users_data), "final users data")
    return final_users_data


def get_time_entries(user_id: str, start_date: str, end_date: str) -> list:
    """
    Returns all time entries for a user between start_date and end_date.
    Dates must be in YYYY-MM-DD format.
    """
    if not user_id:
        raise ValueError("get_time_entries requires a non-empty user_id")

    workspace_id = _workspace_id()
    url = f"{BASE_URL}/workspaces/{workspace_id}/user/{user_id}/time-entries"
    page_size = min(int(os.getenv("CLOCKIFY_TIME_ENTRIES_PAGE_SIZE", "500")), 1000)
    page_size = max(page_size, 1)

    raw_rows: list = []
    page = 1
    max_pages = int(os.getenv("CLOCKIFY_TIME_ENTRIES_MAX_PAGES", "500"))

    _log(
        f"GET time entries user={user_id} range={start_date}..{end_date} workspace={workspace_id}"
    )
    while page <= max_pages:
        params = {
            "start": f"{start_date}T00:00:00Z",
            "end": f"{end_date}T23:59:59Z",
            "page-size": page_size,
            "page": page,
        }
        body = _get_json_with_retry(url, params=params)
        chunk = _time_entries_array_from_body(body)
        for row in chunk:
            if isinstance(row, dict):
                raw_rows.append(row)
        if len(chunk) < page_size:
            break
        page += 1

    entries = []
    for e in raw_rows:
        ti = e.get("timeInterval")
        if not isinstance(ti, dict):
            ti = {}
        start_raw = ti.get("start")
        date_str = ""
        if isinstance(start_raw, str) and len(start_raw) >= 10:
            date_str = start_raw[:10]
        duration_str = ti.get("duration") or "PT0S"
        if not isinstance(duration_str, str):
            duration_str = "PT0S"
        hours = parse_duration(duration_str)
        eid = e.get("id")
        entries.append(
            {
                "id": str(eid) if eid is not None else "",
                "date": date_str,
                "description": e.get("description", "") or "",
                "project_id": e.get("projectId", "") or "",
                "hours": round(hours, 2),
            }
        )
    total_hours = round(sum(item["hours"] for item in entries), 2)
    _log(f"Fetched time entries for user {user_id}: {len(entries)} entries, {total_hours} hours")
    return entries


def get_projects() -> list:
    """Returns all projects in the workspace."""
    url = f"{BASE_URL}/workspaces/{_workspace_id()}/projects"
    data = _get_json_with_retry(url)
    if isinstance(data, list):
        projects = data
    elif isinstance(data, dict) and isinstance(data.get("projects"), list):
        projects = data["projects"]
    else:
        projects = []
    out = []
    for p in projects:
        if not isinstance(p, dict):
            continue
        pid, name = p.get("id"), p.get("name")
        if pid is not None and name is not None:
            out.append({"id": pid, "name": name})
    return out


def parse_duration(duration_str: str) -> float:
    """Converts ISO 8601 duration (e.g. PT2H30M) to decimal hours."""
    if not duration_str or duration_str == "PT0S":
        return 0.0
    hours = re.search(r"(\d+)H", duration_str)
    minutes = re.search(r"(\d+)M", duration_str)
    h = int(hours.group(1)) if hours else 0
    m = int(minutes.group(1)) if minutes else 0
    return h + m / 60
