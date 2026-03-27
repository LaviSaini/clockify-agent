"""Minimal Clockify REST client for scheduled jobs (same data the MCP server exposes)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import httpx

BASE = "https://api.clockify.me/api/v1"


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str | None


class ClockifyClient:
    def __init__(self, api_key: str) -> None:
        self._headers = {"X-Api-Key": api_key}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{BASE}{path}" if path.startswith("/") else f"{BASE}/{path}"
        with httpx.Client(timeout=60.0) as client:
            r = client.get(url, headers=self._headers, params=params)
            r.raise_for_status()
            return r.json()

    def list_workspaces(self) -> list[Workspace]:
        data = self._get("/workspaces")
        return [Workspace(id=w["id"], name=w.get("name") or "") for w in data]

    def list_users(self, workspace_id: str) -> list[User]:
        data = self._get(f"/workspaces/{workspace_id}/users")
        out: list[User] = []
        for u in data:
            uid = u.get("id")
            if not uid:
                continue
            email = (u.get("email") or "").strip()
            name = u.get("name")
            out.append(User(id=uid, email=email, name=name))
        return out

    def find_user_by_email(self, workspace_id: str, email: str) -> User | None:
        needle = email.strip().lower()
        for u in self.list_users(workspace_id):
            if u.email.lower() == needle:
                return u
        return None

    def get_time_entries(
        self,
        workspace_id: str,
        user_id: str,
        start: date | datetime,
        end: date | datetime,
    ) -> list[dict[str, Any]]:
        if isinstance(start, date) and not isinstance(start, datetime):
            start = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        if isinstance(end, date) and not isinstance(end, datetime):
            end = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
        start_s = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_s = end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return self._get(
            f"/workspaces/{workspace_id}/user/{user_id}/time-entries",
            params={"start": start_s, "end": end_s},
        )


def format_entries_for_prompt(entries: list[dict[str, Any]]) -> str:
    """Turn raw Clockify entries into compact text for the LLM."""
    lines: list[str] = []
    for e in entries:
        desc = (e.get("description") or "").strip()
        pid = e.get("projectId") or ""
        tid = e.get("taskId") or ""
        t_start = e.get("timeInterval", {}).get("start") or ""
        t_end = e.get("timeInterval", {}).get("end") or ""
        duration = e.get("timeInterval", {}).get("duration") or ""
        lines.append(
            f"- start={t_start} end={t_end} duration={duration} "
            f"projectId={pid} taskId={tid} description={desc!r}"
        )
    return "\n".join(lines) if lines else "(no entries in range)"
