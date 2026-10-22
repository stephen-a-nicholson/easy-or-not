"""Fetch runs and zones with Garmin's official Personal API client.

The key is never handled here. Garmin's client finds it in
~/.config/garmin/connect-personal-api-key or GARMIN_PERSONAL_API_KEY, exactly
as its own CLI does, and caches the bearer token next to it.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from garmin_personal_api import (
    GarminPersonalApiClient,
    GarminPersonalApiError,
    PersonalApiAuthenticator,
    resolve_api_key,
)

from easy_or_not.fit import NotARun, load_bytes
from easy_or_not.models import Run
from easy_or_not.wellness import Day, parse
from easy_or_not.zones import Zones, from_garmin

__all__ = ["GarminPersonalApiError", "fetch", "fetch_wellness"]

PAGE_SIZE = 50

# The sleep summaries endpoint returns HTTP 400 for ranges much over a month.
SLEEP_CHUNK_DAYS = 28


def _is_run(activity: dict[str, Any]) -> bool:
    # activityType.typeKey is the Garmin Connect convention (running,
    # treadmill_running, trail_running...). Unverified on the Personal API;
    # if it differs, no runs are found and the CLI says so.
    type_key = str((activity.get("activityType") or {}).get("typeKey", ""))
    return "running" in type_key


def fetch(days: int, cache_dir: Path, quiet: bool = False) -> tuple[list[Run], Zones | None]:
    """Return running activities from the last `days` days and the user's zones.

    Original files are cached by activity id, so a second run only downloads
    activities it has not seen.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    end = date.today()
    start = end - timedelta(days=days)

    with PersonalApiAuthenticator() as auth:
        token = auth.obtain_token(resolve_api_key())

    runs: list[Run] = []
    with GarminPersonalApiClient(token.access_token) as client:
        zones = from_garmin(client.get_heart_rate_zones())

        offset = 0
        activities: list[dict[str, Any]] = []
        while True:
            page = client.search_activities(
                start=offset, limit=PAGE_SIZE, start_date=start, end_date=end
            )
            if not isinstance(page, list) or not page:
                break
            activities.extend(a for a in page if isinstance(a, dict))
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

        for activity in filter(_is_run, activities):
            activity_id = str(activity["activityId"])
            cached = cache_dir / f"{activity_id}.zip"
            if not cached.exists():
                if not quiet:
                    print(f"  downloading {activity_id}", file=sys.stderr)
                cached.write_bytes(client.download_activity(activity_id))
            try:
                runs.extend(load_bytes(cached.read_bytes(), run_id=activity_id))
            except NotARun:
                continue

    return runs, zones


def fetch_wellness(days: int, quiet: bool = False) -> dict[date, Day]:
    """Overnight HRV, sleep and resting HR for the last `days` days, keyed by date.

    Each source is fetched separately, so one failing endpoint loses only its
    own signal (and says so) while the readiness view shows the rest.
    """
    end = date.today()
    start = end - timedelta(days=days - 1)

    with PersonalApiAuthenticator() as auth:
        token = auth.obtain_token(resolve_api_key())

    with GarminPersonalApiClient(token.access_token) as client:

        def get(name: str, call: Any) -> Any:
            try:
                return call()
            except GarminPersonalApiError as e:
                if not quiet:
                    print(f"  could not read {name} from Garmin: {e}", file=sys.stderr)
                return None

        hrv = get("HRV", lambda: client.get_daily_hrv_summaries(start, end))
        sleep: list[Any] = []
        for first, last in _chunks(start, end, SLEEP_CHUNK_DAYS):
            part = get("sleep", lambda f=first, la=last: client.get_daily_sleep_summaries(f, la))
            if isinstance(part, list):
                sleep.extend(part)
        summaries = get("resting heart rate", lambda: client.get_daily_summaries(start, end))
    return parse(hrv, sleep, summaries)


def _chunks(start: date, end: date, size: int) -> list[tuple[date, date]]:
    """Split an inclusive date range into inclusive pieces of at most `size` days."""
    pieces = []
    while start <= end:
        last = min(end, start + timedelta(days=size - 1))
        pieces.append((start, last))
        start = last + timedelta(days=1)
    return pieces
