# CLAUDE.md

## What this is

`easy-or-not` reads a runner's own activities (exported FIT files, or the Garmin Personal API via Garmin's official `garmin-connect-personal-api-python` client) and reports time in easy, middle and hard heart-rate bands, how much "easy" running drifted into the middle, and metres per heartbeat on outdoor easy runs over time. Everything runs locally.

Code: `src/easy_or_not/` (`fit.py` parsing, `zones.py` bands, `checks.py` data sanity checks, `analysis.py` metrics, `load.py` training load, `report.py` output, `garmin.py` API fetch, `wellness.py` daily HRV/sleep/resting HR, `readiness.py` readiness rules, `setup.py` key setup, `cli.py`). Tests build FIT files in memory with `fit-tool`.

## Current state (22 Oct 2026)

- Pushed to GitHub, CI green. Published to PyPI (0.1.0, 0.1.1 and 0.2.0, 22 Oct 2026) via `.github/workflows/publish.yml` (trusted publishing, GitHub environment `pypi`, run by hand with `gh workflow run publish.yml`). A version can only be uploaded once, so bump `version` in `pyproject.toml` and `__version__` in `src/easy_or_not/__init__.py` before the next publish.
- First run against the owner's real account worked end to end: 37 runs, API shapes for activity type and zones matched.
- **Diagnosed (22 Oct 2026):** the HR data is genuine, not locked to cadence (HR follows pace and warm-up; cadence stays flat; HR often sits 10 to 15 bpm away from steps per minute). The owner really does run most runs at 175 to 185 bpm. Garmin's zones look too low: a 46 minute effort at a median of 185 bpm is not plausible above 96% of max, so the real max is likely around 200 or more. Even with max 205, 69% of time is in the middle band.
- The earlier "easy runs" were artefacts: fragments under 10 minutes, walks logged as runs, and a watch left recording for an hour after a run.
- Added: `easy-or-not setup` (saves the key, checks it), bare `easy-or-not` runs the Garmin report, data checks in `checks.py` (trim trailing non-running, skip short and walking activities, warn when zone 5 is held for 30+ minutes).
- 0.1.1: coloured text output with block bars (`report.Style`); colour only on a terminal and off with `NO_COLOR`, ASCII bars when the output encoding cannot carry blocks.
- Readiness (`easy-or-not readiness`, and a section at the end of the Garmin report): overnight HRV against Garmin's balanced range, resting HR against a 28-day median, Garmin sleep score, and the load ratio. Verified against the live API on 22 Oct 2026: HRV summaries (90 days fine), sleep summaries (HTTP 400 above about 31 days, so fetched in 28-day chunks), daily summaries `heartRate.restingValue`. Nights without the watch come back as nulls. The owner's sleep scores are often under 60, so sleep is the signal that most often says go easy.
- Added training load (`load.py`): Edwards TRIMP per run, last 7 days against the 28-day weekly average, weekly history. Measured to today for the Garmin source. On the owner's data the ratio is 0.91.

## Next work

1. Optional max HR estimate from sustained efforts, clearly labelled as an estimate. Load depends on zones too, so this matters more now.
2. Tune readiness once there are a few weeks of the owner's feedback (does "go easy" match how runs feel?).
3. Tidy CI: actions on Node.js 20 are deprecated, and setup-uv's cache finds no lock file (`uv.lock` is not committed).

## Rules

- Tests never reach Garmin: an autouse fixture in `tests/conftest.py` blocks the real client; tests that need one patch in a fake.
- Never print, log or commit the API key (`~/.config/garmin/connect-personal-api-key`) or any real FIT/ZIP files. They are git-ignored; keep it that way.
- Run `uv run ruff check . && uv run ruff format . && uv run pytest -q` before finishing. Every new check gets a passing and a failing test.
- UK English, no em dashes, no emoji in code, docs or commit messages.
- Commits are authored and committed by Stephen Nicholson only. No co-author or session trailers.
