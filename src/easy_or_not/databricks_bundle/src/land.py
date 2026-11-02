"""The task the easy-or-not job runs: read Garmin, then land the results in Delta.

It runs the same commands as `easy-or-not --json garmin` and
`easy-or-not --json readiness`, so the tables match what the tool prints locally.
"""

import argparse
import contextlib
import io
import os

from databricks.sdk.runtime import dbutils
from pyspark.sql import SparkSession

from easy_or_not.cli import main
from easy_or_not.databricks import SECRET_KEY, SECRET_SCOPE, land


def run(argv: list[str]) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    if code != 0:
        raise SystemExit(f"easy-or-not {' '.join(argv)} exited with {code}")
    return out.getvalue()


parser = argparse.ArgumentParser()
parser.add_argument("--catalog", required=True)
parser.add_argument("--schema", required=True)
parser.add_argument("--cache-dir", required=True)
args = parser.parse_args()

# Garmin's client reads the key from this variable.
os.environ["GARMIN_PERSONAL_API_KEY"] = dbutils.secrets.get(SECRET_SCOPE, SECRET_KEY)
report = run(["--json", "garmin", "--cache-dir", args.cache_dir])
readiness = run(["--json", "readiness", "--cache-dir", args.cache_dir])
counts = land(report, readiness, args.catalog, args.schema, SparkSession.builder.getOrCreate())
print(", ".join(f"{n} rows in {table}" for table, n in counts.items()))
