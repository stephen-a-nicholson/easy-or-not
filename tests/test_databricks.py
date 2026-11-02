"""The Databricks bundle templates and `land`, with Spark replaced by a fake.

Nothing here calls the Databricks CLI, SDK or a workspace. Whether the live
bundle and Genie APIs accept these files can only be checked with a deploy.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta

import pytest
import yaml

from easy_or_not import databricks
from easy_or_not.analysis import analyse
from easy_or_not.readiness import assess
from easy_or_not.report import readiness_json, render_json
from easy_or_not.wellness import Day

from .conftest import make_run

VALUES = {
    "catalog": "main",
    "schema": "running",
    "user": "runner@example.com",
    "package": "easy-or-not==0.3.0",
    "warehouse_id": "abc123",
    "timezone": "Europe/London",
}
TODAY = date(2026, 11, 2)


# Templates


def test_bundle_renders_every_file_without_placeholders() -> None:
    files = databricks.render_bundle(VALUES)
    assert set(files) == {
        "databricks.yml",
        "resources/genie.yml",
        "resources/job.yml",
        "src/easy_or_not.geniespace.json",
        "src/land.py",
    }
    for text in files.values():
        assert "{{" not in text


def test_bundle_yaml_parses_with_values_filled_in() -> None:
    files = databricks.render_bundle(VALUES)
    for path in ("databricks.yml", "resources/job.yml", "resources/genie.yml"):
        yaml.safe_load(files[path])

    job = yaml.safe_load(files["resources/job.yml"])["resources"]
    task = job["jobs"]["daily"]["tasks"][0]
    params = task["spark_python_task"]["parameters"]
    assert params[params.index("--catalog") + 1] == "main"
    assert params[params.index("--schema") + 1] == "running"
    assert params[params.index("--cache-dir") + 1].startswith("/Volumes/main/running/")
    spec = job["jobs"]["daily"]["environments"][0]["spec"]
    assert spec["dependencies"] == ["easy-or-not==0.3.0"]
    assert job["jobs"]["daily"]["schedule"]["timezone_id"] == "Europe/London"
    assert job["volumes"]["cache"]["catalog_name"] == "main"

    genie = yaml.safe_load(files["resources/genie.yml"])["resources"]["genie_spaces"]
    space = genie["easy_or_not"]
    assert space["warehouse_id"] == "abc123"
    assert "permissions" not in space  # the Genie API does not support them


def test_genie_space_names_all_three_tables() -> None:
    space = json.loads(databricks.render_bundle(VALUES)["src/easy_or_not.geniespace.json"])
    tables = [t["identifier"] for t in space["data_sources"]["tables"]]
    assert tables == ["main.running.days", "main.running.runs", "main.running.weeks"]
    ids = [q["id"] for q in space["config"]["sample_questions"]]
    assert ids == sorted(ids)
    assert all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)


def test_bundle_never_carries_a_secret_value() -> None:
    files = databricks.render_bundle(VALUES)
    # The job reads the key from the secret scope at run time; nothing else.
    assert all("garmin-key" not in text for text in files.values())
    assert "dbutils.secrets.get(SECRET_SCOPE, SECRET_KEY)" in files["src/land.py"]


def test_bundle_refuses_missing_values() -> None:
    with pytest.raises(ValueError, match="warehouse_id"):
        databricks.render_bundle({**VALUES, "warehouse_id": ""})


@pytest.mark.parametrize("bad", ["main.other", "my catalog", "x`; DROP", "a'b"])
def test_bundle_refuses_catalog_names_it_cannot_quote(bad) -> None:
    with pytest.raises(ValueError, match="catalog"):
        databricks.render_bundle({**VALUES, "catalog": bad})


def test_bundle_refuses_values_that_would_break_yaml() -> None:
    with pytest.raises(ValueError, match="timezone"):
        databricks.render_bundle({**VALUES, "timezone": "Europe/London\nfoo: bar"})


def test_write_bundle(tmp_path) -> None:
    databricks.write_bundle(VALUES, tmp_path)
    assert (tmp_path / "resources" / "job.yml").is_file()
    assert "{{" not in (tmp_path / "resources" / "job.yml").read_text()
    assert (tmp_path / "src" / "land.py").is_file()


def test_templates_ship_in_the_wheel(tmp_path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    import zipfile

    (wheel,) = tmp_path.glob("*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    for path in databricks.render_bundle(VALUES):
        assert f"easy_or_not/databricks_bundle/{path}" in names


# Tables


class FakeWriter:
    def __init__(self, spark: FakeSpark, frame: FakeFrame) -> None:
        self.spark, self.frame, self.write_mode = spark, frame, None

    def mode(self, mode: str) -> FakeWriter:
        self.write_mode = mode
        return self

    def saveAsTable(self, name: str) -> None:  # noqa: N802
        self.spark.saved.append((name, self.write_mode, self.frame))


class FakeFrame:
    def __init__(self, spark: FakeSpark, rows: list[tuple], schema: str) -> None:
        self.rows, self.schema = rows, schema
        self.write = FakeWriter(spark, self)


class FakeSpark:
    """Records what land asks Spark to do, in order."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.saved: list[tuple[str, str, FakeFrame]] = []

    def sql(self, statement: str) -> None:
        self.statements.append(statement)

    def createDataFrame(self, rows: list[tuple], schema: str) -> FakeFrame:  # noqa: N802
        return FakeFrame(self, rows, schema)


# Python types Spark accepts for each SQL type without casting.
SPARK_TYPES = {
    "STRING": str,
    "TIMESTAMP": datetime,
    "BOOLEAN": bool,
    "DOUBLE": float,
    "INT": int,
    "DATE": date,
}


def _outputs() -> tuple[str, str]:
    """The JSON the two commands print, from a few weeks of fake runs and nights."""
    start = datetime(2026, 10, 1, 7, tzinfo=UTC)
    runs = [
        make_run([(1800, 130)], start=start, run_id="easy"),
        make_run([(900, 130), (900, 150)], start=start + timedelta(days=2), run_id="drift"),
        make_run([(600, 130), (600, 170)], start=start + timedelta(days=9), treadmill=True),
        make_run([(400, 130)], start=start + timedelta(days=30), run_id="short"),
    ]
    from .conftest import ZONES

    report = analyse(runs, ZONES, as_of=TODAY)
    wellness = {
        TODAY - timedelta(days=1): Day(day=TODAY - timedelta(days=1), hrv=50, resting_hr=48),
        TODAY: Day(
            day=TODAY, hrv=52, hrv_low=45, hrv_high=60, hrv_status="BALANCED", sleep_score=55
        ),
    }
    readiness = assess(wellness, TODAY, None)
    return render_json(report), json.dumps(readiness_json(readiness, wellness))


def _landed() -> tuple[FakeSpark, dict[str, int]]:
    spark = FakeSpark()
    report, readiness = _outputs()
    return spark, databricks.land(report, readiness, "main", "running", spark)


def _frames(spark: FakeSpark) -> dict[str, FakeFrame]:
    return {name.rsplit(".", 1)[1]: frame for name, _, frame in spark.saved}


def test_land_replaces_three_tables() -> None:
    spark, counts = _landed()
    assert [name for name, _, _ in spark.saved] == [
        "main.running.runs",
        "main.running.days",
        "main.running.weeks",
    ]
    assert len(spark.statements) == 3
    for statement, (name, mode, _) in zip(spark.statements, spark.saved, strict=True):
        assert statement.startswith(f"CREATE OR REPLACE TABLE {name} (")
        assert mode == "append"  # into the table just replaced, so comments survive
    assert counts == {"runs": 3, "days": 2, "weeks": 6}


def test_land_rows_match_their_schema() -> None:
    spark, _ = _landed()
    for table in databricks.TABLES:
        frame = _frames(spark)[table.name]
        assert frame.schema == table.ddl
        for row in frame.rows:
            assert len(row) == len(table.columns)
            for value, column in zip(row, table.columns, strict=True):
                if value is not None:
                    assert type(value) is SPARK_TYPES[column.type], (table.name, column.name)


def test_every_column_has_a_comment() -> None:
    spark, _ = _landed()
    for table, statement in zip(databricks.TABLES, spark.statements, strict=True):
        assert table.comment
        for column in table.columns:
            assert column.comment, column.name
            assert f"`{column.name}` {column.type} COMMENT '" in statement
        # Comments are SQL string literals.
        assert "'" not in table.comment + "".join(c.comment for c in table.columns)


def test_runs_rows() -> None:
    spark, _ = _landed()
    rows = {row[0]: row for row in _frames(spark)["runs"].rows}
    names = [c.name for c in databricks.RUNS.columns]
    easy = dict(zip(names, rows["easy"], strict=True))
    assert easy["start"] == datetime(2026, 10, 1, 7, tzinfo=UTC)
    assert easy["session"] is False and easy["treadmill"] is False
    assert easy["easy_s"] == pytest.approx(1799)
    assert easy["middle_s"] == 0.0
    assert easy["load"] == pytest.approx(1799 / 60 * 2)
    # Test zones: z2 starts at 120, z3 at 140.
    assert easy["zone2_s"] == pytest.approx(1799)
    assert easy["zone1_s"] == 0.0 and easy["zone3_s"] == 0.0
    assert "short" not in rows  # under 10 minutes: counts for load, not as a run


def test_runs_rows_without_zone_seconds_leave_them_empty() -> None:
    report = json.loads(_outputs()[0])
    del report["runs"][0]["zone_seconds"]
    row = databricks.run_rows(report)[0]
    zone_index = [c.name for c in databricks.RUNS.columns].index("zone1_s")
    assert row[zone_index : zone_index + 5] == (None,) * 5


def test_days_rows_carry_readiness_only_on_the_day_it_was_assessed() -> None:
    spark, _ = _landed()
    names = [c.name for c in databricks.DAYS.columns]
    yesterday, today = (dict(zip(names, r, strict=True)) for r in _frames(spark)["days"].rows)
    assert yesterday["day"] == TODAY - timedelta(days=1)
    assert yesterday["readiness"] is None and yesterday["sleep_rating"] is None
    assert yesterday["hrv"] == 50 and yesterday["sleep_score"] is None
    assert today["day"] == TODAY
    assert today["hrv_status"] == "BALANCED"
    assert today["readiness"] == "go easy today"  # sleep 55 is poor, HRV in range
    assert today["sleep_rating"] == "low" and today["hrv_rating"] == "ok"
    assert today["load_rating"] is None


def test_days_rows_include_the_readiness_day_without_data() -> None:
    rows = databricks.day_rows({"day": "2026-11-02", "verdict": "x", "signals": [], "days": []})
    assert rows[0][0] == TODAY
    assert rows[0][1:8] == (None,) * 7


def test_weeks_rows_include_empty_weeks() -> None:
    spark, _ = _landed()
    names = [c.name for c in databricks.WEEKS.columns]
    weeks = [dict(zip(names, r, strict=True)) for r in _frames(spark)["weeks"].rows]
    # Every Monday from the first run to the day load is measured to.
    assert [w["week_start"] for w in weeks] == [
        date(2026, 9, 28) + timedelta(weeks=n) for n in range(6)
    ]
    first = weeks[0]
    assert first["easy_s"] == pytest.approx(1799 + 900)
    assert first["middle_s"] == pytest.approx(899)
    assert weeks[3]["easy_s"] == 0.0 and weeks[3]["load"] == 0.0
    # The short run on 31 Oct only counts towards load.
    assert weeks[4]["easy_s"] == 0.0 and weeks[4]["load"] > 0


def test_weeks_rows_without_load() -> None:
    report = {"weekly": [{"week": "2026-10-05", "seconds": {"easy": 60}}], "load": None}
    assert databricks.week_rows(report) == [(date(2026, 10, 5), 60.0, 0.0, 0.0, None)]


def test_land_writes_nothing_when_the_input_is_bad() -> None:
    spark = FakeSpark()
    report = json.loads(_outputs()[0])
    report["runs"][0]["start"] = "not a date"
    with pytest.raises(ValueError):
        databricks.land(report, json.loads(_outputs()[1]), "main", "running", spark)
    assert spark.statements == [] and spark.saved == []


def test_land_refuses_names_it_cannot_quote() -> None:
    spark = FakeSpark()
    with pytest.raises(ValueError, match="schema"):
        databricks.land({}, {}, "main", "running; DROP TABLE x", spark)
    assert spark.statements == []


def test_base_package_imports_without_spark_or_the_sdk() -> None:
    code = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('databricks', 'pyspark'):\n"
        "            raise ImportError(name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "import easy_or_not.cli, easy_or_not.databricks\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# Deploy and destroy


KEY = "not-a-real-garmin-key"
# Captured before the autouse fixture replaces it, for the two tests of run_cli itself.
REAL_RUN_CLI = databricks.run_cli
WAREHOUSES = [
    {"id": "classic1", "name": "Classic", "enable_serverless_compute": False},
    {"id": "sls1", "name": "Serverless", "enable_serverless_compute": True},
]


class FakeCli:
    """Stands in for run_cli: records every call, answers from a table of prefixes."""

    def __init__(
        self, responses: dict[str, str] | None = None, fail: dict[str, str] | None = None
    ) -> None:
        self.calls: list[tuple[list[str], object]] = []
        self.inputs: list[str | None] = []  # stdin, kept apart from the arguments
        self.responses = {
            "--version": "Databricks CLI v1.16.0\n",
            "current-user me": json.dumps({"userName": "runner@example.com"}),
            "warehouses list": json.dumps(WAREHOUSES),
            "bundle summary": json.dumps(
                {"resources": {"genie_spaces": {"easy_or_not": {"url": "https://x/genie/1"}}}}
            ),
            **(responses or {}),
        }
        self.fail = fail or {}

    def __call__(self, args: list[str], *, input: str | None = None, cwd=None) -> str:
        self.calls.append((list(args), cwd))
        self.inputs.append(input)
        line = " ".join(args)
        for prefix, message in self.fail.items():
            if line.startswith(prefix):
                raise databricks.DatabricksError(message)
        for prefix, response in self.responses.items():
            if line.startswith(prefix):
                return response
        return ""

    def commands(self) -> list[str]:
        """Each call as 'group verb', or just the flag for --version."""
        return [a[0] if a[0].startswith("-") else " ".join(a[:2]) for a, _ in self.calls]


def _options(tmp_path, **kw) -> databricks.DeployOptions:
    key_file = tmp_path / "key"
    key_file.write_text(KEY + "\n")
    defaults = {
        "catalog": "main",
        "schema": "running",
        "timezone": "Europe/London",
        "bundle_dir": tmp_path / "bundle",
        "key_file": key_file,
    }
    return databricks.DeployOptions(**{**defaults, **kw})


def test_deploy_end_to_end(tmp_path) -> None:
    cli = FakeCli()
    lines: list[str] = []
    url = databricks.deploy(_options(tmp_path, profile="work"), run=cli, out=lines.append)

    assert cli.commands() == [
        "--version",
        "current-user me",
        "warehouses list",
        "schemas get",
        "secrets create-scope",
        "secrets put-secret",
        "bundle deploy",  # job and volume only: the Genie space needs the tables to exist
        "bundle run",
        "bundle deploy",  # everything, now the job has made the tables
        "bundle summary",
    ]
    assert url == "https://x/genie/1"
    assert any("https://x/genie/1" in line for line in lines)
    first, second = (a for a, _ in cli.calls if a[:2] == ["bundle", "deploy"])
    assert first[first.index("--select") + 1] == "jobs.daily,volumes.cache"
    assert "--select" not in second

    # Every command carries the profile (--version cannot take one); bundle
    # commands run inside the bundle directory.
    for args, cwd in cli.calls:
        assert (args[-2:] == ["-p", "work"]) == (args[0] != "--version")
        assert (cwd == tmp_path / "bundle") == (args[0] == "bundle")
    assert first[first.index("-t") + 1] == "dev"

    # The bundle got the live values: the first serverless warehouse, the user, the version.
    job = (tmp_path / "bundle" / "resources" / "job.yml").read_text()
    genie = (tmp_path / "bundle" / "resources" / "genie.yml").read_text()
    assert f"easy-or-not=={databricks.__version__}" in job
    assert "Europe/London" in job
    assert "warehouse_id: sls1" in genie
    assert "runner@example.com" in genie


def test_deploy_with_a_local_wheel(tmp_path) -> None:
    wheel = tmp_path / "easy_or_not-0.3.0-py3-none-any.whl"
    wheel.write_bytes(b"PK")
    lines: list[str] = []
    databricks.deploy(_options(tmp_path, wheel=wheel), run=FakeCli(), out=lines.append)
    job = (tmp_path / "bundle" / "resources" / "job.yml").read_text()
    assert "- ../wheels/easy_or_not-0.3.0-py3-none-any.whl" in job  # relative to job.yml
    assert "easy-or-not==" not in job
    assert (tmp_path / "bundle" / "wheels" / wheel.name).read_bytes() == b"PK"
    assert any("job installs ../wheels/" in line for line in lines)


def test_deploy_refuses_a_missing_wheel(tmp_path) -> None:
    cli = FakeCli()
    with pytest.raises(databricks.DatabricksError, match="uv build"):
        databricks.deploy(_options(tmp_path, wheel=tmp_path / "nope.whl"), run=cli)
    assert cli.commands() == ["--version"]


def test_deploy_only_passes_the_key_on_stdin(tmp_path) -> None:
    cli = FakeCli()
    lines: list[str] = []
    databricks.deploy(_options(tmp_path), run=cli, out=lines.append)
    for args, _ in cli.calls:
        assert KEY not in " ".join(args)
    assert KEY not in "\n".join(lines)
    for path in (tmp_path / "bundle").rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text()
    stdin = [(a[:2], i) for (a, _), i in zip(cli.calls, cli.inputs, strict=True) if i]
    assert stdin == [(["secrets", "put-secret"], KEY)]


def test_deploy_refuses_without_the_cli(monkeypatch, tmp_path) -> None:
    def missing(*a, **k):
        raise FileNotFoundError("databricks")

    monkeypatch.setattr(databricks.subprocess, "run", missing)
    with pytest.raises(databricks.DatabricksError, match="not installed"):
        databricks.deploy(_options(tmp_path), run=REAL_RUN_CLI)
    assert not (tmp_path / "bundle").exists()


def test_deploy_refuses_an_old_cli(tmp_path) -> None:
    cli = FakeCli({"--version": "Databricks CLI v0.260.0\n"})
    with pytest.raises(databricks.DatabricksError, match="too old"):
        databricks.deploy(_options(tmp_path), run=cli)
    assert cli.commands() == ["--version"]


def test_deploy_refuses_without_a_key_file(tmp_path) -> None:
    cli = FakeCli()
    options = _options(tmp_path, key_file=tmp_path / "missing")
    with pytest.raises(databricks.DatabricksError, match="easy-or-not setup"):
        databricks.deploy(options, run=cli)
    assert cli.commands() == ["--version"]  # nothing touched the workspace


def test_deploy_refuses_an_empty_key_file(tmp_path) -> None:
    options = _options(tmp_path)
    options.key_file.write_text("\n")
    with pytest.raises(databricks.DatabricksError, match="easy-or-not setup"):
        databricks.deploy(options, run=FakeCli())


def test_deploy_refuses_an_unknown_timezone(tmp_path) -> None:
    with pytest.raises(databricks.DatabricksError, match="timezone"):
        databricks.deploy(_options(tmp_path, timezone="Mars/Olympus"), run=FakeCli())


def test_deploy_creates_a_missing_schema(tmp_path) -> None:
    cli = FakeCli(fail={"schemas get": "SCHEMA_DOES_NOT_EXIST"})
    lines: list[str] = []
    databricks.deploy(_options(tmp_path), run=cli, out=lines.append)
    assert ["schemas", "create", "running", "main"] in [a for a, _ in cli.calls]
    assert any("Created schema main.running" in line for line in lines)


def test_deploy_ignores_an_existing_scope(tmp_path) -> None:
    cli = FakeCli(fail={"secrets create-scope": "Scope easy-or-not already exists"})
    databricks.deploy(_options(tmp_path), run=cli)
    assert "secrets put-secret" in cli.commands()


def test_deploy_stops_on_other_scope_errors(tmp_path) -> None:
    cli = FakeCli(fail={"secrets create-scope": "PERMISSION_DENIED"})
    with pytest.raises(databricks.DatabricksError, match="PERMISSION_DENIED"):
        databricks.deploy(_options(tmp_path), run=cli)
    assert "secrets put-secret" not in cli.commands()


def test_deploy_picks_the_named_warehouse(tmp_path) -> None:
    cli = FakeCli()
    databricks.deploy(_options(tmp_path, warehouse="Classic"), run=cli)
    assert "warehouse_id: classic1" in (tmp_path / "bundle/resources/genie.yml").read_text()


def test_deploy_without_any_warehouse(tmp_path) -> None:
    cli = FakeCli({"warehouses list": "[]"})
    with pytest.raises(databricks.DatabricksError, match="No SQL warehouse"):
        databricks.deploy(_options(tmp_path), run=cli)


def test_deploy_with_a_wrong_warehouse_name(tmp_path) -> None:
    with pytest.raises(databricks.DatabricksError, match="Nope"):
        databricks.deploy(_options(tmp_path, warehouse="Nope"), run=FakeCli())


def test_deploy_without_a_genie_url_still_finishes(tmp_path) -> None:
    cli = FakeCli({"bundle summary": json.dumps({"resources": {}})})
    lines: list[str] = []
    assert databricks.deploy(_options(tmp_path), run=cli, out=lines.append) == ""
    assert any("bundle summary" in line for line in lines)


def test_run_cli_error_carries_stderr_not_stdin(monkeypatch) -> None:
    def failing(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom from the server")

    monkeypatch.setattr(databricks.subprocess, "run", failing)
    with pytest.raises(databricks.DatabricksError) as e:
        REAL_RUN_CLI(["secrets", "put-secret", "s", "k"], input=KEY)
    assert "boom from the server" in str(e.value)
    assert KEY not in str(e.value)


def test_local_timezone_prefers_tz() -> None:
    assert databricks.local_timezone({"TZ": "Europe/London"}) == "Europe/London"
    # An unknown TZ falls through to the machine's zone, or UTC.
    assert databricks._valid_timezone(databricks.local_timezone({"TZ": "Not/AZone"}))


def test_destroy(tmp_path) -> None:
    (tmp_path / "databricks.yml").write_text("bundle: {name: x}")
    cli = FakeCli()
    lines: list[str] = []
    databricks.destroy(target="prod", bundle_dir=tmp_path, run=cli, out=lines.append)
    assert cli.commands() == ["--version", "bundle destroy", "secrets delete-scope"]
    destroy_args = cli.calls[1][0]
    assert "--auto-approve" in destroy_args
    assert destroy_args[destroy_args.index("-t") + 1] == "prod"
    assert any("left in place" in line for line in lines)


def test_destroy_without_a_bundle(tmp_path) -> None:
    with pytest.raises(databricks.DatabricksError, match="nothing to destroy"):
        databricks.destroy(bundle_dir=tmp_path, run=FakeCli())


def test_destroy_ignores_a_missing_scope(tmp_path) -> None:
    (tmp_path / "databricks.yml").write_text("bundle: {name: x}")
    cli = FakeCli(fail={"secrets delete-scope": "RESOURCE_DOES_NOT_EXIST: scope does not exist"})
    databricks.destroy(bundle_dir=tmp_path, run=cli)


# CLI wiring


def test_cli_deploy_reports_a_missing_cli(monkeypatch, capsys) -> None:
    from easy_or_not.cli import main

    def missing(*a, **k):
        raise databricks.DatabricksError("The Databricks CLI is not installed. Install it from x")

    monkeypatch.setattr(databricks, "run_cli", missing)
    assert main(["databricks", "deploy", "--catalog", "main", "--schema", "running"]) == 2
    assert "not installed" in capsys.readouterr().err


def test_cli_deploy_reports_a_missing_key(monkeypatch, tmp_path, capsys) -> None:
    from easy_or_not.cli import main

    monkeypatch.setattr(databricks, "run_cli", FakeCli())
    monkeypatch.setattr(databricks, "DEFAULT_KEY_FILE", tmp_path / "missing")
    monkeypatch.setattr(databricks, "DEFAULT_BUNDLE_DIR", tmp_path / "bundle")
    assert main(["databricks", "deploy", "--catalog", "main", "--schema", "running"]) == 2
    assert "easy-or-not setup" in capsys.readouterr().err
    assert not (tmp_path / "bundle").exists()


def test_cli_destroy_reports_errors(monkeypatch, tmp_path, capsys) -> None:
    from easy_or_not.cli import main

    monkeypatch.setattr(databricks, "run_cli", FakeCli())
    monkeypatch.setattr(databricks, "DEFAULT_BUNDLE_DIR", tmp_path)
    assert main(["databricks", "destroy"]) == 2
    assert "nothing to destroy" in capsys.readouterr().err


def test_cli_databricks_needs_an_action() -> None:
    from easy_or_not.cli import main

    with pytest.raises(SystemExit):
        main(["databricks"])


def test_a_test_that_forgets_to_fake_the_cli_fails_loudly(tmp_path) -> None:
    with pytest.raises(AssertionError, match="fake run_cli"):
        databricks.deploy(_options(tmp_path))
