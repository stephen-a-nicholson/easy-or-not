"""easy-or-not: are your easy runs actually easy?"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import TextIO

from easy_or_not import __version__, load
from easy_or_not.analysis import analyse
from easy_or_not.fit import NotARun, load_path
from easy_or_not.models import Run
from easy_or_not.readiness import assess
from easy_or_not.report import (
    Style,
    readiness_json,
    render_json,
    render_readiness,
    render_text,
)
from easy_or_not.wellness import Day
from easy_or_not.zones import Zones, from_max_hr

DEFAULT_CACHE = Path("~/.cache/easy-or-not").expanduser()

# Enough for four weeks of load and a four-week resting HR baseline.
WELLNESS_DAYS = 35


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="easy-or-not", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--max-hr", type=int, help="derive zones from max HR instead of Garmin's")
    p.add_argument(
        "--easy-up-to",
        type=int,
        choices=(2, 3),
        default=2,
        help="highest heart-rate zone that counts as easy (default 2; try 3 on Garmin defaults)",
    )
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    p.set_defaults(days=56, cache_dir=DEFAULT_CACHE)  # for a bare `easy-or-not`
    sub = p.add_subparsers(dest="source", metavar="{garmin,readiness,files,setup}")

    sub.add_parser("setup", help="save your Garmin Personal API key (run this once)")

    files = sub.add_parser("files", help="analyse .fit or .zip files you have exported")
    files.add_argument("paths", nargs="+", type=Path)

    garmin = sub.add_parser(
        "garmin", help="fetch your runs with a Garmin Personal API key (the default)"
    )
    garmin.add_argument("--days", type=int, default=56, help="how far back to look (default 56)")
    garmin.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)

    ready = sub.add_parser(
        "readiness", help="today's readiness from overnight HRV, sleep, resting HR and load"
    )
    ready.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    return p


def terminal_style(stream: TextIO, env: Mapping[str, str]) -> Style:
    """Colour only on a real terminal, never when piped or when NO_COLOR is set.

    Block bars only when the output encoding can carry them (a Windows code
    page redirected to a file cannot).
    """
    colour = stream.isatty() and not env.get("NO_COLOR") and env.get("TERM") != "dumb"
    try:
        "\u2588\u2591".encode(stream.encoding or "ascii")
        blocks = True
    except (LookupError, UnicodeEncodeError):
        blocks = False
    return Style(colour=colour, blocks=blocks)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.source = args.source or "garmin"
    zones: Zones | None = None
    runs: list[Run] = []
    wellness: dict[date, Day] = {}

    if args.source == "setup":
        from easy_or_not.setup import setup

        return setup()
    if args.source == "files":
        for path in args.paths:
            try:
                runs.extend(load_path(path))
            except NotARun as e:
                print(f"skipping {e}", file=sys.stderr)
    else:
        from easy_or_not.garmin import GarminPersonalApiError, fetch, fetch_wellness

        days = WELLNESS_DAYS if args.source == "readiness" else args.days
        try:
            runs, zones = fetch(max(days, WELLNESS_DAYS), args.cache_dir, quiet=args.json)
            wellness = fetch_wellness(WELLNESS_DAYS, quiet=args.json)
        except GarminPersonalApiError as e:
            print(f"Could not reach your Garmin account: {e}", file=sys.stderr)
            print("If you have not saved a key yet, run: easy-or-not setup", file=sys.stderr)
            return 2
        if args.source == "garmin":
            # Load covers the requested window; readiness needs at least five weeks.
            cutoff = date.today() - timedelta(days=args.days)
            runs = [r for r in runs if r.start.date() >= cutoff]

    if args.max_hr:
        zones = from_max_hr(args.max_hr)
    if args.source == "readiness":
        return _readiness(args, runs, zones, wellness)
    if zones is None:
        print(
            "No heart-rate zones: pass --max-hr, or use the garmin source to read yours.",
            file=sys.stderr,
        )
        return 2
    if not runs:
        print("No running activities found.", file=sys.stderr)
        return 1

    zones = replace(zones, easy_up_to=args.easy_up_to)
    # From the API, load is measured to today, so a week off shows as a week off.
    as_of = date.today() if args.source == "garmin" else None
    report = analyse(runs, zones, as_of=as_of)
    today = assess(wellness, date.today(), load.status(report)) if args.source == "garmin" else None
    if args.json:
        print(render_json(report, today))
    else:
        print(render_text(report, terminal_style(sys.stdout, os.environ), today))
    return 0


def _readiness(
    args: argparse.Namespace, runs: list[Run], zones: Zones | None, wellness: dict[date, Day]
) -> int:
    today = date.today()
    load_status = None
    if zones is not None and runs:
        load_status = load.status(analyse(runs, zones, as_of=today))
    readiness = assess(wellness, today, load_status)
    if args.json:
        print(json.dumps(readiness_json(readiness, wellness), indent=2))
    else:
        style = terminal_style(sys.stdout, os.environ)
        print(render_readiness(readiness, wellness, style))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
