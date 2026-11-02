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
    "version": "0.3.0",
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
