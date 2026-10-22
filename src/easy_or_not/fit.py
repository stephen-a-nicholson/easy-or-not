"""Read FIT files (or the ZIP that Garmin wraps them in) into Run objects."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import fitdecode

from easy_or_not.models import Run, Sample

# Sub-sports Garmin uses for indoor running, where speed comes from the
# accelerometer rather than GPS and pace is not trustworthy.
INDOOR_SUB_SPORTS = {"treadmill", "indoor_running", "indoor"}


class NotARun(ValueError):
    """The file parsed but is not a running activity."""


def load_path(path: Path) -> list[Run]:
    """Load one .fit or .zip file, or every such file in a directory."""
    if path.is_dir():
        runs: list[Run] = []
        for child in sorted(path.iterdir()):
            if child.suffix.lower() in {".fit", ".zip"}:
                runs.extend(_load_quietly(child))
        return runs
    return load_bytes(path.read_bytes(), run_id=path.stem)


def _load_quietly(path: Path) -> list[Run]:
    try:
        return load_path(path)
    except NotARun:
        return []


def load_bytes(data: bytes, run_id: str) -> list[Run]:
    """Parse FIT bytes, or a ZIP containing one or more FIT files."""
    if zipfile.is_zipfile(io.BytesIO(data)):
        runs: list[Run] = []
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".fit"):
                    try:
                        runs.append(parse_fit(archive.read(name), run_id=run_id))
                    except NotARun:
                        continue
        if not runs:
            raise NotARun(f"{run_id}: no running activity in archive")
        return runs
    return [parse_fit(data, run_id=run_id)]


def parse_fit(data: bytes, run_id: str) -> Run:
    """Parse a single FIT file into a Run. Raises NotARun for other sports."""
    sport: str | None = None
    sub_sport: str | None = None
    start: datetime | None = None
    first_ts: datetime | None = None
    samples: list[Sample] = []

    with fitdecode.FitReader(io.BytesIO(data)) as reader:
        for frame in reader:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name in {"sport", "session"}:
                sport = sport or _str(frame, "sport")
                sub_sport = sub_sport or _str(frame, "sub_sport")
                if frame.name == "session" and start is None:
                    start = _get(frame, "start_time")
            elif frame.name == "record":
                ts = _get(frame, "timestamp")
                if ts is None:
                    continue
                first_ts = first_ts or ts
                speed = _get(frame, "enhanced_speed")
                if speed is None:
                    speed = _get(frame, "speed")
                samples.append(
                    Sample(
                        elapsed_s=(ts - first_ts).total_seconds(),
                        heart_rate=_get(frame, "heart_rate"),
                        speed_mps=float(speed) if speed is not None else None,
                        cadence_spm=_steps_per_minute(frame),
                    )
                )

    if sport != "running":
        raise NotARun(f"{run_id}: sport is {sport!r}, not running")
    if not samples:
        raise NotARun(f"{run_id}: no record data")

    start = start or first_ts or datetime.fromtimestamp(0, UTC)
    return Run(
        run_id=run_id,
        start=start,
        samples=samples,
        treadmill=sub_sport in INDOOR_SUB_SPORTS,
    )


def _steps_per_minute(frame: fitdecode.FitDataMessage) -> float | None:
    # Running cadence in FIT is strides per minute (one foot), so double it.
    cadence = _get(frame, "cadence")
    if cadence is None:
        return None
    return (float(cadence) + float(_get(frame, "fractional_cadence") or 0.0)) * 2


def _get(frame: fitdecode.FitDataMessage, name: str):  # noqa: ANN202 - FIT values are loosely typed
    return frame.get_value(name) if frame.has_field(name) else None


def _str(frame: fitdecode.FitDataMessage, name: str) -> str | None:
    value = _get(frame, name)
    return str(value) if value is not None else None
