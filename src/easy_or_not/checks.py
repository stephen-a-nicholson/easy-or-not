"""Data sanity checks: catch recordings that would make the numbers misleading.

Each check either cleans a run up, drops it with a stated reason, or adds a
warning to the report. None of them changes the zones.
"""

from __future__ import annotations

from dataclasses import replace
from statistics import median

from easy_or_not.models import Run, Sample

# Running is almost always above this many steps per minute and walking below it.
RUNNING_CADENCE_SPM = 140.0

# Without cadence, treat anything slower than about 9:15/km as not running.
RUNNING_SPEED_MPS = 1.8

# Runs with less heart-rate data than this are fragments (a GPS test, a
# watch started by accident) and say nothing about how you train.
MIN_HR_S = 600.0

# Zone 5 is the top few percent of your range. Holding it for this long is
# not plausible, so it points to zones (or a max HR) set too low.
IMPLAUSIBLE_Z5_S = 30 * 60.0

SHORT_REASON = "under 10 minutes of heart-rate data"


def _is_running(sample: Sample) -> bool | None:
    if sample.cadence_spm is not None:
        return sample.cadence_spm >= RUNNING_CADENCE_SPM
    if sample.speed_mps is not None:
        return sample.speed_mps >= RUNNING_SPEED_MPS
    return None


def trim_tail(run: Run) -> Run:
    """Drop samples after the last running sample.

    This removes a walk home, or a watch left recording on the sofa, which
    would otherwise count as a long stretch of very easy running.
    """
    flags = [_is_running(s) for s in run.samples]
    if not any(flags):
        return run
    last = max(i for i, f in enumerate(flags) if f)
    if last == len(run.samples) - 1:
        return run
    return replace(run, samples=run.samples[: last + 1])


def skip_reason(run: Run, hr_seconds: float) -> str | None:
    """Why this run should be left out of the analysis, or None to keep it.

    `run` is the activity as recorded; `hr_seconds` is the heart-rate time
    left after trimming, so a walk is reported as a walk, not as too short.
    """
    cadences = [s.cadence_spm for s in run.samples if s.cadence_spm]
    if len(cadences) > len(run.samples) / 2 and median(cadences) < RUNNING_CADENCE_SPM:
        return "walking cadence"
    if hr_seconds < MIN_HR_S:
        return SHORT_REASON
    return None
