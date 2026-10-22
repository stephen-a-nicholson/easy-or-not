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

from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator, resolve_api_key

from easy_or_not.fit import NotARun, load_bytes
from easy_or_not.models import Run
from easy_or_not.zones import Zones, from_garmin

PAGE_SIZE = 50


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
