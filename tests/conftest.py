from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import FileType, Manufacturer, Sport, SubSport

from easy_or_not.models import Run, Sample
from easy_or_not.zones import Zones

ZONES = Zones(z2=120, z3=140, z4=160, z5=175, source="test")


def make_run(
    hr_profile: list[tuple[int, int]],
    *,
    speed: float = 3.3,
    cadence: float | None = None,
    start: datetime | None = None,
    treadmill: bool = False,
    run_id: str = "r",
) -> Run:
    """Build a run from (seconds, heart_rate) segments, one sample per second."""
    samples: list[Sample] = []
    t = 0
    for seconds, hr in hr_profile:
        for _ in range(seconds):
            samples.append(
                Sample(elapsed_s=float(t), heart_rate=hr, speed_mps=speed, cadence_spm=cadence)
            )
            t += 1
    return Run(
        run_id=run_id,
        start=start or datetime(2026, 10, 5, 7, 0, tzinfo=UTC),
        samples=samples,
        treadmill=treadmill,
    )


def fit_bytes(
    *,
    sport: Sport = Sport.RUNNING,
    sub_sport: SubSport = SubSport.GENERIC,
    minutes: int = 20,
    hr: int = 130,
    speed: float = 3.33,
    cadence: int | None = None,
) -> bytes:
    start = datetime(2026, 10, 20, 7, 0, tzinfo=UTC)
    start_ms = round(start.timestamp() * 1000)
    builder = FitFileBuilder(auto_define=True)

    file_id = FileIdMessage()
    file_id.type = FileType.ACTIVITY
    file_id.manufacturer = Manufacturer.DEVELOPMENT.value
    file_id.time_created = start_ms
    builder.add(file_id)

    for i in range(minutes * 60):
        rec = RecordMessage()
        rec.timestamp = round((start + timedelta(seconds=i)).timestamp() * 1000)
        rec.heart_rate = hr
        rec.speed = speed
        if cadence is not None:
            rec.cadence = cadence
        builder.add(rec)

    session = SessionMessage()
    session.start_time = start_ms
    session.timestamp = start_ms + minutes * 60_000
    session.sport = sport
    session.sub_sport = sub_sport
    builder.add(session)
    return builder.build_bytes()


def zipped(data: bytes, name: str = "123_ACTIVITY.fit") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def zones() -> Zones:
    return ZONES
