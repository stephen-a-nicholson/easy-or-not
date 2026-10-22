# CLAUDE.md

## What this is

`easy-or-not` reads a runner's own activities (exported FIT files, or the Garmin Personal API via Garmin's official `garmin-connect-personal-api-python` client) and reports time in easy, middle and hard heart-rate bands, how much "easy" running drifted into the middle, and metres per heartbeat on outdoor easy runs over time. Everything runs locally.

Code: `src/easy_or_not/` (`fit.py` parsing, `zones.py` bands, `analysis.py` metrics, `report.py` output, `garmin.py` API fetch, `cli.py`). Tests build FIT files in memory with `fit-tool`.

## Current state (22 Oct 2026)

- Pushed to GitHub, CI green. Not yet on PyPI; publishing is `.github/workflows/publish.yml` with trusted publishing, run by hand once the output is trustworthy.
- First run against the owner's real account worked end to end: 37 runs, API shapes for activity type and zones matched.
- **Open problem:** the numbers are implausible. On Garmin default zones (z3 134, z4 154, z5 173, implying max HR about 192) 77% of running time is "hard" and 52% is above z5, yet the owner's easy runs at 5:00/km feel very easy. Only 3 to 8 runs classify as easy, some of them one-minute activities.
- Suspected causes, in order: wrist HR locking onto cadence (median HR close to steps per minute), or a max HR in Garmin settings that is too low. Check by printing per run median and max HR, median cadence x 2, pace and sub_sport from the cached files in `~/.cache/easy-or-not`.

## Next work

1. Diagnose the cause above from the cached FIT files before changing any thresholds.
2. Add data sanity checks that warn instead of printing a confident number: HR tracking cadence, implausibly high share of time near max, very short activities (ignore runs under about 10 minutes of HR data in the easy-run list).
3. Consider deriving max HR from the data (high percentile across recent hard efforts) as an option, clearly labelled as an estimate.
4. Then a training-load metric from HR (for watches like the Vivoactive 5 that lack Training Load).

## Rules

- Never print, log or commit the API key (`~/.config/garmin/connect-personal-api-key`) or any real FIT/ZIP files. They are git-ignored; keep it that way.
- Run `uv run ruff check . && uv run ruff format . && uv run pytest -q` before finishing. Every new check gets a passing and a failing test.
- UK English, no em dashes, no emoji in code, docs or commit messages.
- Commits are authored and committed by Stephen Nicholson only. No co-author or session trailers.
