"""Run easy-or-not on Databricks: the bundle that schedules it, and the tables it writes.

Nothing here imports pyspark or the Databricks SDK. `land` writes with the
Spark session it is given, so it can be tested with a fake, and the base
install never needs either. `deploy` and `destroy` drive the Databricks CLI,
which the user installs separately; tests replace `run_cli` with a fake.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import zoneinfo
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from easy_or_not import __version__

SECRET_SCOPE = "easy-or-not"
SECRET_KEY = "garmin-key"

# Secret scopes and Genie spaces as bundle resources both need a CLI from 2026.
MIN_CLI = (1, 3, 0)
CLI_INSTALL = "https://docs.databricks.com/dev-tools/cli/install.html"
DEFAULT_BUNDLE_DIR = Path("~/.config/easy-or-not/databricks").expanduser()
DEFAULT_KEY_FILE = Path("~/.config/garmin/connect-personal-api-key").expanduser()
JOB_KEY = "daily"
GENIE_KEY = "easy_or_not"

BUNDLE_PACKAGE = "databricks_bundle"
PLACEHOLDERS = ("catalog", "schema", "user", "version", "warehouse_id", "timezone")
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

# Catalog and schema go into SQL, volume paths and Genie table names unquoted,
# so keep them to plain identifiers. Other values go into YAML and paths.
IDENTIFIER = re.compile(r"[A-Za-z0-9_]+")
SAFE_VALUE = re.compile(r"[\w.@/+:-]+")


def _check_identifier(kind: str, value: str) -> None:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{kind} must be letters, digits and underscores only, not {value!r}")


def _template_files(root: Traversable, prefix: str = "") -> Iterator[tuple[str, Traversable]]:
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if entry.name == "__pycache__":
            continue
        path = f"{prefix}{entry.name}"
        if entry.is_dir():
            yield from _template_files(entry, f"{path}/")
        else:
            yield path, entry


def render_bundle(values: Mapping[str, str]) -> dict[str, str]:
    """Fill in the bundle templates. Returns relative path -> file contents."""
    missing = [k for k in PLACEHOLDERS if not values.get(k)]
    if missing:
        raise ValueError(f"missing bundle values: {', '.join(missing)}")
    for kind in ("catalog", "schema"):
        _check_identifier(kind, values[kind])
    for key in PLACEHOLDERS:
        if not SAFE_VALUE.fullmatch(values[key]):
            raise ValueError(f"{key} has characters a bundle cannot carry: {values[key]!r}")

    rendered: dict[str, str] = {}
    for path, entry in _template_files(resources.files("easy_or_not") / BUNDLE_PACKAGE):
        text = entry.read_text(encoding="utf-8")
        for key in PLACEHOLDERS:
            text = text.replace("{{" + key + "}}", values[key])
        if left := PLACEHOLDER.findall(text):
            raise ValueError(f"{path} has unknown placeholders: {', '.join(sorted(set(left)))}")
        rendered[path] = text
    return rendered


def write_bundle(values: Mapping[str, str], dest: Path) -> None:
    for path, text in render_bundle(values).items():
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


# Tables. Genie reads the table and column comments, so every column has one.
# Comments go into SQL string literals: no quote marks.


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    comment: str


@dataclass(frozen=True)
class Table:
    name: str
    comment: str
    columns: tuple[Column, ...]

    def create_sql(self, catalog: str, schema: str) -> str:
        cols = ", ".join(f"`{c.name}` {c.type} COMMENT '{c.comment}'" for c in self.columns)
        return (
            f"CREATE OR REPLACE TABLE {catalog}.{schema}.{self.name} ({cols}) "
            f"USING DELTA COMMENT '{self.comment}'"
        )

    @property
    def ddl(self) -> str:
        """The schema without comments, for createDataFrame."""
        return ", ".join(f"`{c.name}` {c.type}" for c in self.columns)


_BAND = {
    "easy": "zones 1 and 2",
    "middle": "zone 3, the grey zone between easy and hard",
    "hard": "zones 4 and 5",
}
_ZONE_COMMENT = "Seconds in heart-rate zone {z} on this run, from the Garmin zones"
_RATING = "Readiness rating of {what} for this day: ok, watch or low. Only set on the readiness day"

RUNS = Table(
    "runs",
    "One row per run from Garmin, after leaving out walks, fragments under 10 minutes "
    "and time the watch kept recording after the run ended",
    (
        Column("run_id", "STRING", "Garmin activity id"),
        Column("start", "TIMESTAMP", "When the run started"),
        Column("treadmill", "BOOLEAN", "True for treadmill runs, where wrist pace is an estimate"),
        Column(
            "session",
            "BOOLEAN",
            "True when at least 10 percent of the run was hard; false when it was meant to be easy",
        ),
        *(
            Column(f"{band}_s", "DOUBLE", f"Seconds in the {band} band, {zones}")
            for band, zones in _BAND.items()
        ),
        *(Column(f"zone{z}_s", "DOUBLE", _ZONE_COMMENT.format(z=z)) for z in range(1, 6)),
        Column(
            "load",
            "DOUBLE",
            "Training load, Edwards TRIMP: minutes in each heart-rate zone times the zone number",
        ),
        Column(
            "efficiency",
            "DOUBLE",
            "Metres per heartbeat in the easy band after a 5 minute warm-up; higher is better. "
            "Null when there was too little easy running to measure",
        ),
    ),
)

DAYS = Table(
    "days",
    "One row per calendar day of overnight and resting data from Garmin. Overnight values "
    "belong to the morning you woke up. Null means the watch recorded nothing",
    (
        Column("day", "DATE", "Calendar day"),
        Column("hrv", "INT", "Average overnight heart-rate variability, ms"),
        Column("hrv_low", "INT", "Bottom of the balanced HRV range Garmin sets for you, ms"),
        Column("hrv_high", "INT", "Top of the balanced HRV range Garmin sets for you, ms"),
        Column("hrv_status", "STRING", "HRV status as Garmin reports it, such as BALANCED"),
        Column("sleep_s", "INT", "Seconds asleep the night before"),
        Column("sleep_score", "INT", "Garmin sleep score, 0 to 100; under 60 is poor"),
        Column("resting_hr", "INT", "Resting heart rate, bpm"),
        Column(
            "readiness",
            "STRING",
            "Readiness verdict, the estimate of easy-or-not and not Garmin Training Readiness. "
            "Only set on the most recent day",
        ),
        Column("hrv_rating", "STRING", _RATING.format(what="overnight HRV")),
        Column("resting_hr_rating", "STRING", _RATING.format(what="resting heart rate")),
        Column("sleep_rating", "STRING", _RATING.format(what="sleep")),
        Column("load_rating", "STRING", _RATING.format(what="the load ratio")),
    ),
)

WEEKS = Table(
    "weeks",
    "One row per Monday to Sunday week, including weeks without runs",
    (
        Column("week_start", "DATE", "Monday the week starts on"),
        *(
            Column(f"{band}_s", "DOUBLE", f"Seconds of running in the {band} band, {zones}")
            for band, zones in _BAND.items()
        ),
        Column(
            "load",
            "DOUBLE",
            "Training load for the week, Edwards TRIMP, including runs too short for the bands",
        ),
    ),
)

TABLES = (RUNS, DAYS, WEEKS)

SIGNAL_COLUMNS = {
    "HRV": "hrv_rating",
    "Resting HR": "resting_hr_rating",
    "Sleep": "sleep_rating",
    "Load": "load_rating",
}


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _int(value: Any) -> int | None:
    return None if value is None else int(value)


def run_rows(report: Mapping[str, Any]) -> list[tuple]:
    rows = []
    for r in report.get("runs", []):
        seconds = r.get("seconds") or {}
        # JSON from before 0.3.0 has no zone seconds: null, not zero.
        zone_seconds = r.get("zone_seconds")
        zones = [
            None if zone_seconds is None else float(zone_seconds.get(str(z), 0.0))
            for z in range(1, 6)
        ]
        rows.append(
            (
                str(r["id"]),
                datetime.fromisoformat(r["start"]),
                bool(r["treadmill"]),
                bool(r["session"]),
                *(float(seconds.get(band, 0.0)) for band in _BAND),
                *zones,
                _float(r.get("load")),
                _float(r.get("efficiency")),
            )
        )
    return rows


def day_rows(readiness: Mapping[str, Any]) -> list[tuple]:
    today = readiness.get("day")
    ratings = {s["name"]: s.get("rating") for s in readiness.get("signals", [])}
    days = {d["day"]: d for d in readiness.get("days", [])}
    if today:
        days.setdefault(today, {"day": today})
    rows = []
    for key in sorted(days):
        d = days[key]
        assessed = key == today
        rows.append(
            (
                date.fromisoformat(key),
                *(_int(d.get(f)) for f in ("hrv", "hrv_low", "hrv_high")),
                d.get("hrv_status"),
                *(_int(d.get(f)) for f in ("sleep_s", "sleep_score", "resting_hr")),
                readiness.get("verdict") if assessed else None,
                *(ratings.get(name) if assessed else None for name in SIGNAL_COLUMNS),
            )
        )
    return rows


def week_rows(report: Mapping[str, Any]) -> list[tuple]:
    bands = {w["week"]: w["seconds"] for w in report.get("weekly", [])}
    loads = {w["week"]: w["load"] for w in (report.get("load") or {}).get("weekly", [])}
    return [
        (
            date.fromisoformat(week),
            *(float(bands.get(week, {}).get(band, 0.0)) for band in _BAND),
            _float(loads.get(week)),
        )
        for week in sorted(set(bands) | set(loads))
    ]


def _parse(data: str | Mapping[str, Any]) -> Mapping[str, Any]:
    return json.loads(data) if isinstance(data, str) else data


def land(
    report_json: str | Mapping[str, Any],
    readiness_json: str | Mapping[str, Any],
    catalog: str,
    schema: str,
    spark: Any,
) -> dict[str, int]:
    """Replace the runs, days and weeks tables with this run's results.

    Takes the output of `easy-or-not --json garmin` and `easy-or-not --json
    readiness`. Each table is overwritten, since the source covers the whole
    window every time. Returns the row count per table.
    """
    _check_identifier("catalog", catalog)
    _check_identifier("schema", schema)
    report, readiness = _parse(report_json), _parse(readiness_json)
    # Build every row first so bad input fails before any table is replaced.
    rows = {RUNS: run_rows(report), DAYS: day_rows(readiness), WEEKS: week_rows(report)}
    for table, table_rows in rows.items():
        spark.sql(table.create_sql(catalog, schema))
        frame = spark.createDataFrame(table_rows, schema=table.ddl)
        frame.write.mode("append").saveAsTable(f"{catalog}.{schema}.{table.name}")
    return {table.name: len(table_rows) for table, table_rows in rows.items()}


# Deploy and destroy. Everything remote goes through the Databricks CLI so
# the user's existing profiles and login just work.


class DatabricksError(Exception):
    """Something the user needs to fix, with a message that says what."""


Runner = Callable[..., str]


def run_cli(args: list[str], *, input: str | None = None, cwd: Path | None = None) -> str:
    """Run one Databricks CLI command and return its stdout.

    `input` is for the secret only. It never goes into an argument, the error
    message or anything printed.
    """
    try:
        result = subprocess.run(
            ["databricks", *args], input=input, capture_output=True, text=True, cwd=cwd
        )
    except FileNotFoundError:
        raise DatabricksError(
            f"The Databricks CLI is not installed. Install it from {CLI_INSTALL}"
        ) from None
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise DatabricksError(f"databricks {' '.join(args)} failed: {detail}")
    return result.stdout


class Cli:
    """The CLI with a profile and bundle directory already chosen."""

    def __init__(self, run: Runner, profile: str | None, bundle_dir: Path) -> None:
        self._run, self.profile, self.bundle_dir = run, profile, bundle_dir

    def __call__(self, *args: str, input: str | None = None) -> str:
        argv = list(args) + (["-p", self.profile] if self.profile else [])
        # bundle commands only work from inside the bundle directory.
        cwd = self.bundle_dir if args[0] == "bundle" else None
        return self._run(argv, input=input, cwd=cwd)

    def json(self, *args: str) -> Any:
        out = self(*args, "-o", "json")
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            raise DatabricksError(f"databricks {' '.join(args)} did not return JSON") from None


def check_cli(cli: Cli) -> None:
    out = cli("--version")
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", out)
    if m is None:
        raise DatabricksError(f"Could not read the Databricks CLI version from {out.strip()!r}")
    version = tuple(int(x) for x in m.groups())
    if version < MIN_CLI:
        wanted = ".".join(map(str, MIN_CLI))
        raise DatabricksError(
            f"Databricks CLI {'.'.join(map(str, version))} is too old; "
            f"easy-or-not needs {wanted} or later. See {CLI_INSTALL}"
        )


def read_key(path: Path = DEFAULT_KEY_FILE) -> str:
    """The Garmin key `easy-or-not setup` saved. Returned, never printed."""
    try:
        key = path.read_text(encoding="utf-8").strip()
    except OSError:
        key = ""
    if not key:
        raise DatabricksError(f"No Garmin key at {path}. Run: easy-or-not setup")
    return key


def current_user(cli: Cli) -> str:
    me = cli.json("current-user", "me")
    user = me.get("userName") if isinstance(me, dict) else None
    if not user:
        raise DatabricksError("Could not work out who you are logged in as")
    return str(user)


def pick_warehouse(cli: Cli, name: str | None = None) -> str:
    """A SQL warehouse for Genie: the one named, else the first serverless one."""
    warehouses = [w for w in cli.json("warehouses", "list") if isinstance(w, dict)]
    if name:
        matches = [w for w in warehouses if w.get("name") == name or w.get("id") == name]
        if not matches:
            raise DatabricksError(f"No SQL warehouse called {name!r}")
        return str(matches[0]["id"])
    serverless = [w for w in warehouses if w.get("enable_serverless_compute")]
    chosen = serverless or warehouses
    if not chosen:
        raise DatabricksError(
            "No SQL warehouse found. Genie needs one; create a serverless warehouse "
            "or pass --warehouse"
        )
    return str(chosen[0]["id"])


def ensure_schema(cli: Cli, catalog: str, schema: str) -> bool:
    """Create the schema if it is missing. Returns True when it was created.

    The schema is not a bundle resource on purpose: `destroy` would drop the
    tables with it.
    """
    try:
        cli("schemas", "get", f"{catalog}.{schema}")
        return False
    except DatabricksError:
        cli("schemas", "create", schema, catalog)
        return True


def put_secret(cli: Cli, key: str) -> None:
    try:
        cli("secrets", "create-scope", SECRET_SCOPE)
    except DatabricksError as e:
        if "already exists" not in str(e).lower():
            raise
    # On stdin, so the key is never in a process list or a shell history.
    cli("secrets", "put-secret", SECRET_SCOPE, SECRET_KEY, input=key)


def local_timezone(environ: Mapping[str, str] = os.environ) -> str:
    """The machine's IANA zone, for the job schedule. UTC when it cannot be found."""
    candidates = [environ.get("TZ", "")]
    with contextlib.suppress(OSError):
        candidates.append(Path("/etc/timezone").read_text(encoding="utf-8").strip())
    with contextlib.suppress(OSError):
        link = os.readlink("/etc/localtime")
        candidates.append(link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else "")
    for name in candidates:
        if name and _valid_timezone(name):
            return name
    return "UTC"


def _valid_timezone(name: str) -> bool:
    try:
        zoneinfo.ZoneInfo(name)
        return True
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return False


def genie_url(summary: Any) -> str | None:
    try:
        return summary["resources"]["genie_spaces"][GENIE_KEY]["url"] or None
    except (KeyError, TypeError):
        return None


@dataclass(frozen=True)
class DeployOptions:
    catalog: str
    schema: str
    profile: str | None = None
    target: str = "dev"
    warehouse: str | None = None
    timezone: str | None = None
    bundle_dir: Path | None = None  # DEFAULT_BUNDLE_DIR
    key_file: Path | None = None  # DEFAULT_KEY_FILE


def deploy(
    options: DeployOptions, run: Runner | None = None, out: Callable[[str], None] = print
) -> str:
    """Deploy the bundle, store the key, run the job once. Returns the Genie URL."""
    # Defaults are looked up at call time so tests can replace them on the module.
    bundle_dir = options.bundle_dir or DEFAULT_BUNDLE_DIR
    cli = Cli(run or run_cli, options.profile, bundle_dir)
    check_cli(cli)
    key = read_key(options.key_file or DEFAULT_KEY_FILE)  # fail before touching the workspace
    timezone = options.timezone or local_timezone()
    if not _valid_timezone(timezone):
        raise DatabricksError(f"Unknown timezone {timezone!r}; use an IANA name like Europe/London")

    user = current_user(cli)
    out(f"Deploying as {user} to target {options.target}")
    warehouse_id = pick_warehouse(cli, options.warehouse)
    if ensure_schema(cli, options.catalog, options.schema):
        out(f"Created schema {options.catalog}.{options.schema}")
    write_bundle(
        {
            "catalog": options.catalog,
            "schema": options.schema,
            "user": user,
            "version": __version__,
            "warehouse_id": warehouse_id,
            "timezone": timezone,
        },
        bundle_dir,
    )
    out(f"Bundle written to {bundle_dir}")
    put_secret(cli, key)
    out(f"Garmin key stored in secret scope {SECRET_SCOPE}")
    cli("bundle", "deploy", "--auto-approve", "-t", options.target)
    out("Bundle deployed; running the job once (this fetches your runs from Garmin)")
    cli("bundle", "run", JOB_KEY, "-t", options.target)
    summary = cli.json("bundle", "summary", "-t", options.target)
    url = genie_url(summary)
    out(f"Tables are in {options.catalog}.{options.schema}: runs, days, weeks")
    out(f"Genie space: {url}" if url else "Genie space: see databricks bundle summary")
    paused = " (paused in dev)" if options.target == "dev" else ""
    out(f"The job runs daily at 06:30 {timezone}{paused}")
    return url or ""


def destroy(
    profile: str | None = None,
    target: str = "dev",
    bundle_dir: Path | None = None,
    run: Runner | None = None,
    out: Callable[[str], None] = print,
) -> None:
    """Remove the job, volume and Genie space, and the secret. The tables stay."""
    bundle_dir = bundle_dir or DEFAULT_BUNDLE_DIR
    cli = Cli(run or run_cli, profile, bundle_dir)
    check_cli(cli)
    if not (bundle_dir / "databricks.yml").is_file():
        raise DatabricksError(f"No bundle at {bundle_dir}; nothing to destroy")
    cli("bundle", "destroy", "--auto-approve", "-t", target)
    out("Job, cache volume and Genie space removed")
    try:
        cli("secrets", "delete-scope", SECRET_SCOPE)
        out(f"Secret scope {SECRET_SCOPE} deleted")
    except DatabricksError as e:
        if "does not exist" not in str(e).lower() and "not found" not in str(e).lower():
            raise
    out("The runs, days and weeks tables were left in place; drop them yourself if you want")
