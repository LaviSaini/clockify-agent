import os
import re
import requests

BASE_URL = "https://api.clockify.me/api/v1"


def _debug_enabled() -> bool:
    return os.getenv("CLOCKIFY_DEBUG", "1").strip().lower() in {"1", "true", "yes", "on"}


def _log(message: str) -> None:
    if _debug_enabled():
        print(f"[clockify] {message}")


def _headers():
    return {"X-Api-Key": os.getenv("CLOCKIFY_API_KEY")}


def _workspace_id() -> str:
    wid = os.getenv("CLOCKIFY_WORKSPACE_ID", "").strip()
    if wid:
        _log(f"Using workspace from .env: {wid}")
        return wid
    url = f"{BASE_URL}/workspaces"
    _log("Fetching workspaces from Clockify API")
    response = requests.get(url, headers=_headers())
    response.raise_for_status()
    data = response.json()
    if not data:
        raise RuntimeError("No Clockify workspaces for this API key.")
    _log(f"Workspace auto-detected: {data[0]['id']}")
    return data[0]["id"]


def get_all_users() -> list:
    """Returns all members of the workspace."""
    workspace_id = _workspace_id()
    url = f"{BASE_URL}/workspaces/{workspace_id}/users"
    _log(f"GET users for workspace {workspace_id}")
    response = requests.get(url, headers=_headers())
    data = response.json()
    print(len(data))
    users_list = data if isinstance(data, list) else data.get("users", []) 
    users = [
    {"id": u["id"], "name": u["name"], "email": u["email"]}
    for u in users_list
    ]
    print(f"Fetched users: {len(users)}")
    return users


def get_time_entries(user_id: str, start_date: str, end_date: str) -> list:
    """
    Returns all time entries for a user between start_date and end_date.
    Dates must be in YYYY-MM-DD format.
    """
    workspace_id = _workspace_id()
    url = f"{BASE_URL}/workspaces/{workspace_id}/user/{user_id}/time-entries"
    params = {
        "start": f"{start_date}T00:00:00Z",
        "end": f"{end_date}T23:59:59Z",
        "page-size": 500,
    }
    _log(
        f"GET time entries user={user_id} range={start_date}..{end_date} workspace={workspace_id}"
    )
    response = requests.get(url, headers=_headers(), params=params)
    response.raise_for_status()
    entries = []
    for e in response.json():
        duration_str = e.get("timeInterval", {}).get("duration", "PT0S")
        hours = parse_duration(duration_str)
        entries.append({
            "id": e["id"],
            "date": e["timeInterval"]["start"][:10],
            "description": e.get("description", ""),
            "project_id": e.get("projectId", ""),
            "hours": round(hours, 2),
        })
    total_hours = round(sum(item["hours"] for item in entries), 2)
    _log(f"Fetched time entries for user {user_id}: {len(entries)} entries, {total_hours} hours")
    return entries


def get_projects() -> list:
    """Returns all projects in the workspace."""
    url = f"{BASE_URL}/workspaces/{_workspace_id()}/projects"
    response = requests.get(url, headers=_headers())
    response.raise_for_status()
    return [
        {"id": p["id"], "name": p["name"]}
        for p in response.json()
    ]


def parse_duration(duration_str: str) -> float:
    """Converts ISO 8601 duration (e.g. PT2H30M) to decimal hours."""
    if not duration_str or duration_str == "PT0S":
        return 0.0
    hours = re.search(r"(\d+)H", duration_str)
    minutes = re.search(r"(\d+)M", duration_str)
    h = int(hours.group(1)) if hours else 0
    m = int(minutes.group(1)) if minutes else 0
    return h + m / 60
