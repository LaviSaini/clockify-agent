import os
from datetime import datetime, timedelta

MIN_HOURS = float(os.getenv("MIN_HOURS_PER_DAY", 8))


def detect_missing_logs(user_name: str, entries: list, start_date: str, end_date: str) -> list:
    """
    Given a list of time entries for a user, detects missing or incomplete days.
    Skips weekends. Returns a list of flagged days with severity:
      - 'Missing'    → 0 hours logged
      - 'Incomplete' → logged but under MIN_HOURS_PER_DAY
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    # Build a map of date → total hours logged
    hours_by_date = {}
    for entry in entries:
        date = entry["date"]
        hours_by_date[date] = hours_by_date.get(date, 0) + entry["hours"]

    flagged = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # Monday–Friday only
            date_str = current.strftime("%Y-%m-%d")
            day_name = current.strftime("%A")
            hours = hours_by_date.get(date_str, 0)

            if hours == 0:
                severity = "Missing"
            elif hours < MIN_HOURS:
                severity = "Incomplete"
            else:
                severity = None

            if severity:
                flagged.append({
                    "user": user_name,
                    "date": date_str,
                    "day": day_name,
                    "hours_logged": round(hours, 2),
                    "severity": severity,
                })
        current += timedelta(days=1)

    return flagged
