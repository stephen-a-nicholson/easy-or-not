"""easy-or-not: are your easy runs actually easy?"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from easy_or_not import __version__
from easy_or_not.analysis import analyse
from easy_or_not.fit import NotARun, load_path
from easy_or_not.models import Run
from easy_or_not.report import render_json, render_text
from easy_or_not.zones import Zones, from_max_hr

DEFAULT_CACHE = Path("~/.cache/easy-or-not").expanduser()


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
    sub = p.add_subparsers(dest="source", required=True)

    files = sub.add_parser("files", help="analyse .fit or .zip files you have exported")
    files.add_argument("paths", nargs="+", type=Path)

    garmin = sub.add_parser("garmin", help="fetch your runs with a Garmin Personal API key")
    garmin.add_argument("--days", type=int, default=56, help="how far back to look (default 56)")
    garmin.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    zones: Zones | None = None
    runs: list[Run] = []

    if args.source == "files":
        for path in args.paths:
            try:
                runs.extend(load_path(path))
            except NotARun as e:
                print(f"skipping {e}", file=sys.stderr)
    else:
        from easy_or_not.garmin import fetch  # imported here so `files` works offline

        runs, zones = fetch(args.days, args.cache_dir, quiet=args.json)

    if args.max_hr:
        zones = from_max_hr(args.max_hr)
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
    report = analyse(runs, zones)
    print(render_json(report) if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
