"""The Garmin layer, with Garmin's client replaced by a fake.

This checks the paging, filtering and caching logic. It cannot check that
Garmin's live responses match the shapes assumed here; that needs a real key.
"""

from __future__ import annotations

from easy_or_not import garmin

from .conftest import fit_bytes, zipped

ZONES = [
    {"sport": "RUNNING", "zone2Floor": 120, "zone3Floor": 140, "zone4Floor": 160, "zone5Floor": 175}
]


class FakeAuth:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def obtain_token(self, key):
        return type("T", (), {"access_token": "tok"})()


class FakeClient:
    downloads: list[str] = []

    def __init__(self, token):
        assert token == "tok"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def get_heart_rate_zones(self):
        return ZONES

    def search_activities(self, *, start, limit, start_date, end_date):
        acts = [
            {"activityId": 1, "activityType": {"typeKey": "running"}},
            {"activityId": 2, "activityType": {"typeKey": "cycling"}},
            {"activityId": 3, "activityType": {"typeKey": "treadmill_running"}},
        ]
        return acts if start == 0 else []

    def download_activity(self, activity_id):
        FakeClient.downloads.append(activity_id)
        return zipped(fit_bytes(minutes=5))


def test_fetch_filters_runs_and_caches(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(garmin, "PersonalApiAuthenticator", FakeAuth)
    monkeypatch.setattr(garmin, "GarminPersonalApiClient", FakeClient)
    monkeypatch.setattr(garmin, "resolve_api_key", lambda: "key")
    FakeClient.downloads = []

    runs, zones = garmin.fetch(28, tmp_path, quiet=True)
    assert [r.run_id for r in runs] == ["1", "3"]
    assert zones is not None and zones.z3 == 140
    assert FakeClient.downloads == ["1", "3"]

    garmin.fetch(28, tmp_path, quiet=True)
    assert FakeClient.downloads == ["1", "3"], "second fetch should use the cache"


class FakeWellnessClient(FakeClient):
    def get_daily_hrv_summaries(self, start, end):
        return {"hrvSummaries": [{"calendarDate": str(end), "lastNightAvg": 88}]}

    def get_daily_sleep_summaries(self, start, end):
        raise garmin.GarminPersonalApiError("sleep endpoint down")

    def get_daily_summaries(self, start, end):
        return {"data": [{"calendarDate": str(end), "heartRate": {"restingValue": 46}}]}


def test_fetch_wellness_survives_one_endpoint_failing(monkeypatch) -> None:
    monkeypatch.setattr(garmin, "PersonalApiAuthenticator", FakeAuth)
    monkeypatch.setattr(garmin, "GarminPersonalApiClient", FakeWellnessClient)
    monkeypatch.setattr(garmin, "resolve_api_key", lambda: "key")
    days = garmin.fetch_wellness(7, quiet=True)
    (day,) = days.values()
    assert (day.hrv, day.resting_hr, day.sleep_s) == (88, 46, None)


def test_fetch_wellness_reports_a_failing_endpoint(monkeypatch, capsys) -> None:
    monkeypatch.setattr(garmin, "PersonalApiAuthenticator", FakeAuth)
    monkeypatch.setattr(garmin, "GarminPersonalApiClient", FakeWellnessClient)
    monkeypatch.setattr(garmin, "resolve_api_key", lambda: "key")
    garmin.fetch_wellness(7)
    assert "could not read sleep" in capsys.readouterr().err


class ChunkedSleepClient(FakeWellnessClient):
    ranges: list[tuple] = []

    def get_daily_sleep_summaries(self, start, end):
        if (end - start).days >= 31:
            raise garmin.GarminPersonalApiError("HTTP 400")
        ChunkedSleepClient.ranges.append((start, end))
        return [{"calendarDate": str(end), "sleepTimeSeconds": 25000}]


def test_sleep_is_fetched_in_chunks(monkeypatch) -> None:
    monkeypatch.setattr(garmin, "PersonalApiAuthenticator", FakeAuth)
    monkeypatch.setattr(garmin, "GarminPersonalApiClient", ChunkedSleepClient)
    monkeypatch.setattr(garmin, "resolve_api_key", lambda: "key")
    ChunkedSleepClient.ranges = []
    days = garmin.fetch_wellness(35, quiet=True)
    assert len(ChunkedSleepClient.ranges) == 2
    assert sum((b - a).days + 1 for a, b in ChunkedSleepClient.ranges) == 35
    assert sum(1 for d in days.values() if d.sleep_s) == 2
