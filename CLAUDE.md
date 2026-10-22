# CLAUDE.md

## What this is

`easy-or-not` reads a runner's own activities (exported FIT files, or the Garmin Personal API via Garmin's official `garmin-connect-personal-api-python` client) and reports time in easy, middle and hard heart-rate bands, how much "easy" running drifted into the middle, and metres per heartbeat on outdoor easy runs over time. Everything runs locally.

Code: `src/easy_or_not/` (`fit.py` parsing, `zones.py` bands, `analysis.py` metrics, `report.py` output, `garmin.py` API fetch, `cli.py`). Tests build FIT files in memory with `fit-tool`.

## Current state (22 Oct 2026)

- Pushed to GitHub, CI green. Not yet on PyPI; publishing is `.github/workflows/publish.yml` with trusted publishing, run by hand once the output is trustworthy.
- First run against the owner's real account worked end to end: 37 runs, API shapes for activity type and zones matched.
- **Diagnosed (22 Oct 2026):** the HR data is genuine, not locked to cadence (HR follows pace and warm-up; cadence stays flat; HR often sits 10 to 15 bpm away from steps per minute). The owner really does run most runs at 175 to 185 bpm. Garmin's zones look too low: a 46 minute effort at a median of 185 bpm is not plausible above 96% of max, so the real max is likely around 200 or more. Even with max 205, 69% of time is in the middle band.
- The earlier "easy runs" were artefacts: fragments under 10 minutes, walks logged as runs, and a watch left recording for an hour after a run.
- Added: `easy-or-not setup` (saves the key, checks it), bare `easy-or-not` runs the Garmin report, data checks in `checks.py` (trim trailing non-running, skip short and walking activities, warn when zone 5 is held for 30+ minutes).

## Next work

1. Publish to PyPI (run `publish.yml` by hand) so `uv tool install easy-or-not` works; until then install instructions in the README fail.
2. Optional max HR estimate from sustained efforts, clearly labelled as an estimate.
3. A training-load metric from HR (for watches like the Vivoactive 5 that lack Training Load).

## Rules

- Never print, log or commit the API key (`~/.config/garmin/connect-personal-api-key`) or any real FIT/ZIP files. They are git-ignored; keep it that way.
- Run `uv run ruff check . && uv run ruff format . && uv run pytest -q` before finishing. Every new check gets a passing and a failing test.
- UK English, no em dashes, no emoji in code, docs or commit messages.
- Commits are authored and committed by Stephen Nicholson only. No co-author or session trailers.
