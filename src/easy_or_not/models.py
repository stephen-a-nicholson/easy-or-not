"""The normalised shape every data source is converted into before analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Sample:
    """One recorded point in a run."""

    elapsed_s: float
    heart_rate: int | None
    speed_mps: float | None


@dataclass
class Run:
    """A single running activity, reduced to what the analysis needs."""

    run_id: str
    start: datetime
    samples: list[Sample] = field(default_factory=list)
    treadmill: bool = False

    @property
    def duration_s(self) -> float:
        return self.samples[-1].elapsed_s - self.samples[0].elapsed_s if self.samples else 0.0
