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

## Databricks and Genie (built 2 Nov 2026, not yet run live)

Goal: one command deploys a Databricks Declarative Automation Bundle that runs the tool on a schedule, lands the results in Delta, and creates a Genie space so the owner can ask questions like "which weeks did I train too hard?" in plain English. The local tool stays exactly as it is for everyone else.

**State on 2 Nov 2026:** all four steps done; 0.3.0 published to PyPI (also adds `--as-of`). Deployed for real to the owner's workspace (profile `agent-factory-dev`, catalog `workspace`, schema `running`, target `dev`, with `--wheel` since 0.3.0 is not on PyPI): 30 runs, 35 days and 9 weeks landed with every column comment, and the Genie space answered "which weeks did I train too hard?" with sensible SQL. Live findings, all fixed in code:

- `databricks --version` takes no `-p`; `Cli` skips the profile for bare flags.
- Relative paths in `resources/job.yml` resolve from `resources/`, so a local wheel is `../wheels/<name>`.
- Genie refuses a space over tables that do not exist (403 at `POST /genie/spaces`), and the job creates them, so `deploy` is two-phase: `bundle deploy --select jobs.daily,volumes.cache`, `bundle run daily`, then a full `bundle deploy`.
- Confirmed as written: `secrets put-secret` reads stdin, `dbutils.secrets.get` works in a serverless `spark_python_task`, serverless environment version 4 exists, the `.geniespace.json` layout was accepted, `${resources.volumes.cache.name}` resolves in the volume path, and `bundle summary -o json` has `resources.genie_spaces.<key>.url`.
- `databricks genie ask` is a general agent, not a space. To test the space from a script use `genie start-conversation`, poll `get-message`, then `get-message-attachment-query-result`.
- On the owner's data Genie says every week was too hard, because of the zone problem in "Current state": there is no `--max-hr` on the job yet. Worth adding as a deploy option.

What was built differs from the plan below in these ways:

- No `[databricks]` extra and no `databricks-sdk` dependency: `databricks.py` only shells out to the Databricks CLI, and `land.py` runs on the job where `databricks.sdk.runtime` already exists.
- The job reads the key with `dbutils.secrets.get` in `land.py`; the `{{secrets/...}}` syntax is for classic cluster environment variables, not serverless.
- Two template values the plan did not have: `warehouse_id` (Genie needs one; `--warehouse`, else the first serverless) and `timezone` (`--timezone`, else the machine's).
- The schema is created by `deploy` if missing rather than being a bundle resource, so `destroy` does not drop the tables.
- `--json` output gained `zone_seconds` per run (the one change to local output), so the `runs` table can carry zones 1 to 5.
- Column names in the generated SQL are backticked; comments are SQL string literals and must not contain a quote mark.
- `deploy`/`destroy` resolve `run_cli`, `DEFAULT_KEY_FILE` and `DEFAULT_BUNDLE_DIR` at call time, and an autouse fixture in `conftest.py` replaces all three. Keep it that way: the first test run reached the real CLI before that fixture existed.
- The `.geniespace.json` layout (`version`, `data_sources.tables`, `instructions.text_instructions`, `config.sample_questions` with sorted 32-hex ids) was written from memory because the CLI schema leaves `serialized_space` untyped. Expect this to be the first thing the live deploy disagrees with, along with the `${resources.volumes.cache.name}` reference in the volume path, `put-secret` reading stdin, and the shape of `bundle summary -o json`.
- The `genie_spaces` resource fields in CLI 1.16.0: `title`, `description`, `warehouse_id`, `parent_path`, `file_path` or `serialized_space`, `etag`, `lifecycle`, `permissions` (unused).

### User experience

```bash
uv tool install 'easy-or-not[databricks]'
easy-or-not databricks deploy --catalog main --schema running [--profile DEFAULT] [--target dev]
easy-or-not databricks destroy
```

`deploy` writes the bundle to `~/.config/easy-or-not/databricks/` with catalog, schema and the current user filled in, creates a secret scope `easy-or-not` holding the Garmin key (read from the same key file `setup` writes, piped to the CLI, never passed on a command line or printed), runs `databricks bundle deploy`, runs the job once, and prints the Genie space URL. `destroy` runs `databricks bundle destroy` and deletes the scope. Both check the Databricks CLI is installed and at least 1.3.0 first and fail with a clear message if not.

### Design constraints

- **Optional extra.** `databricks-sdk` goes in `[project.optional-dependencies] databricks`. Nothing under `src/easy_or_not/` imports it except the new module, and `cli.py` imports that module lazily inside the subcommand so the base install never touches it. The Databricks CLI itself is a prerequisite the user installs, not a Python dependency.
- **New module `src/easy_or_not/databricks.py`** with two jobs: `deploy`/`destroy` (template rendering, secret, bundle CLI calls via `subprocess`) and `land(report_json, readiness_json, catalog, schema)` which the job calls to write the JSON into three Delta tables. `land` must work with a `SparkSession` passed in, so it is testable with a fake.
- **Bundle templates ship inside the package** under `src/easy_or_not/databricks_bundle/`: `databricks.yml`, `resources/job.yml`, `resources/genie.yml`, `src/land.py` (the notebook or script the job runs), and the Genie space definition. Add them to the wheel include list. Use simple `{{catalog}}`-style placeholders and `str.replace`, not Jinja, to keep dependencies at zero.
- **The job**: serverless, one Python task, environment installs `easy-or-not` from PyPI pinned to the running version. It sets `GARMIN_PERSONAL_API_KEY` from `{{secrets/easy-or-not/garmin-key}}` (Garmin's client already reads that variable, so no auth code changes), runs the equivalent of `easy-or-not garmin --json --cache-dir /Volumes/<catalog>/<schema>/cache` and `easy-or-not readiness --json`, then calls `land`. The volume is a bundle resource too, so cached activity files persist between runs. Schedule daily at 06:30 in the owner's timezone, paused in the `dev` target as bundles do by default.
- **Tables** (all managed Delta, overwritten each run since the source is the full window): `runs` (one row per run: id, start, treadmill, session, seconds per band, zone seconds 1 to 5, load, efficiency), `days` (one row per calendar day: hrv, hrv_low, hrv_high, sleep_s, sleep_score, resting_hr, plus the readiness verdict and each signal's status for that day where computed), `weeks` (week_start, seconds per band, load). Column comments on every column, because Genie reads them.
- **Genie space** as a `genie_spaces` bundle resource over the three tables, with instructions explaining the bands, what load and the ratio mean, and that readiness is the tool's estimate rather than Garmin's. No `permissions` block (the API does not support it, see the agent-factory notes). Verify the current resource schema in the CLI JSON schema before writing it, since this resource is newer than most.
- **Secrets**: `databricks secrets create-scope easy-or-not` (ignore "already exists"), then `databricks secrets put-secret easy-or-not garmin-key` with the key on stdin. The key never appears in logs, output, the rendered bundle or tests.
- **Tests**: template rendering (placeholders all replaced, YAML parses), `land` against a fake Spark session that records `saveAsTable` calls and schemas, CLI wiring (`deploy` refuses without the CLI, refuses without a key file), and that the base package still imports with `databricks-sdk` absent. No test may call the real Databricks CLI or SDK; follow the pattern of the Garmin fakes.
- **Docs**: a "Databricks" section in the README (what it creates, cost note that serverless jobs and a Genie space are cheap but not free, how to remove it), and a `docs/databricks.md` with the table schemas and example Genie questions.
- Bump to 0.3.0. The local commands and output must not change at all; the existing tests prove that.

### Order of work

1. Done. Templates and `land`, with tests, before any CLI wiring.
2. Done. `deploy`/`destroy` with the CLI checks and secret handling.
3. Done (2 Nov 2026), see the live findings above. On WSL, `databricks auth login` mangles the OAuth URL when it opens the Windows browser (the `&`s are lost); open the printed URL with `powershell.exe -Command "Start-Process '<url>'"` instead.
4. Done. README section, `docs/databricks.md`, 0.3.0 published 2 Nov 2026. **Next:** redeploy without `--wheel` to prove the PyPI path on the job. Note `gh workflow run` fires on whatever `main` GitHub has, so push first and never chain it after a piped `git push`.

### Still open from before

- Optional max HR estimate from sustained efforts, clearly labelled as an estimate.
- Tune readiness once there are a few weeks of the owner's feedback.
- Tidy CI: actions on Node.js 20 are deprecated, and setup-uv's cache finds no lock file (`uv.lock` is not committed).

## Rules

- Tests never reach Garmin: an autouse fixture in `tests/conftest.py` blocks the real client; tests that need one patch in a fake.
- Never print, log or commit the API key (`~/.config/garmin/connect-personal-api-key`) or any real FIT/ZIP files. They are git-ignored; keep it that way.
- Run `uv run ruff check . && uv run ruff format . && uv run pytest -q` before finishing. Every new check gets a passing and a failing test.
- UK English, no em dashes, no emoji in code, docs or commit messages.
- Commits are authored and committed by Stephen Nicholson only. No co-author or session trailers.
