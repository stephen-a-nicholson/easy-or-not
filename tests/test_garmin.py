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
