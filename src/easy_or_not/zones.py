"""Heart-rate zones: from the user's own Garmin settings, or derived from max HR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Zones:
    """Lower bounds of zones 2 to 5, in bpm. Anything below z2 is zone 1.

    The analysis groups them into three bands, which is the split that matters
    for the question "are my easy runs easy":

    - easy:   zones 1 to `easy_up_to`
    - middle: the next zone up, the "grey zone" that tires you without being a session
    - hard:   everything above that

    With `easy_up_to=2` (the default) that is easy = Z1-2, middle = Z3,
    hard = Z4-5. Garmin's default percent-of-max zones put Z3 at 70-80% of max,
    which is lower than the roughly 80% easy ceiling used in polarised-training
    research, so users on Garmin's defaults may want `easy_up_to=3`.
    """

    z2: int
    z3: int
    z4: int
    z5: int
    source: str
    easy_up_to: int = 2  # highest zone that still counts as easy

    def zone(self, hr: int) -> int:
        if hr >= self.z5:
            return 5
        if hr >= self.z4:
            return 4
        if hr >= self.z3:
            return 3
        if hr >= self.z2:
            return 2
        return 1

    @property
    def easy_ceiling(self) -> int:
        """First bpm that is no longer easy."""
        return self.z3 if self.easy_up_to == 2 else self.z4

    @property
    def hard_floor(self) -> int:
        """First bpm that counts as hard."""
        return self.z4 if self.easy_up_to == 2 else self.z5

    def band(self, hr: int) -> str:
        if hr < self.easy_ceiling:
            return "easy"
        return "middle" if hr < self.hard_floor else "hard"


def from_max_hr(max_hr: int) -> Zones:
    """Zones whose three-band split matches polarised-training research.

    Easy is below 80% of max, middle 80-90%, hard 90% and above. Zone 2 starts
    at 70% only so the five-zone view is still meaningful.
    """
    return Zones(
        z2=round(max_hr * 0.70),
        z3=round(max_hr * 0.80),
        z4=round(max_hr * 0.90),
        z5=round(max_hr * 0.95),
        source=f"max HR {max_hr}",
    )


def from_garmin(payload: Any) -> Zones | None:
    """Read zones from the heart-rate zones endpoint.

    Assumes the shape Garmin Connect has used for years: a list of zone sets,
    one per sport, each with zone2Floor..zone5Floor. That is not yet verified
    against the Personal API, so anything unexpected returns None and the
    caller asks for --max-hr rather than guessing.
    """
    sets = payload if isinstance(payload, list) else [payload]
    sets = [s for s in sets if isinstance(s, dict) and "zone2Floor" in s]
    if not sets:
        return None

    def rank(s: dict[str, Any]) -> int:
        sport = str(s.get("sport", "")).upper()
        return 0 if sport == "RUNNING" else 1 if sport in {"DEFAULT", ""} else 2

    chosen = sorted(sets, key=rank)[0]
    try:
        return Zones(
            z2=int(chosen["zone2Floor"]),
            z3=int(chosen["zone3Floor"]),
            z4=int(chosen["zone4Floor"]),
            z5=int(chosen["zone5Floor"]),
            source=f"your Garmin {str(chosen.get('sport', 'default')).lower()} zones",
        )
    except (KeyError, TypeError, ValueError):
        return None
