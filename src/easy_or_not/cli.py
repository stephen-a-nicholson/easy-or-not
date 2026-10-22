"""easy-or-not: are your easy runs actually easy?"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TextIO

from easy_or_not import __version__
from easy_or_not.analysis import analyse
from easy_or_not.fit import NotARun, load_path
from easy_or_not.models import Run
from easy_or_not.report import Style, render_json, render_text
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
    p.set_defaults(days=56, cache_dir=DEFAULT_CACHE)  # for a bare `easy-or-not`
    sub = p.add_subparsers(dest="source", metavar="{garmin,files,setup}")

    sub.add_parser("setup", help="save your Garmin Personal API key (run this once)")

    files = sub.add_parser("files", help="analyse .fit or .zip files you have exported")
    files.add_argument("paths", nargs="+", type=Path)

    garmin = sub.add_parser(
        "garmin", help="fetch your runs with a Garmin Personal API key (the default)"
    )
    garmin.add_argument("--days", type=int, default=56, help="how far back to look (default 56)")
    garmin.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
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
        from easy_or_not.garmin import GarminPersonalApiError, fetch  # so `files` works offline

        try:
            runs, zones = fetch(args.days, args.cache_dir, quiet=args.json)
        except GarminPersonalApiError as e:
            print(f"Could not reach your Garmin account: {e}", file=sys.stderr)
            print("If you have not saved a key yet, run: easy-or-not setup", file=sys.stderr)
            return 2

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
    # From the API, load is measured to today, so a week off shows as a week off.
    as_of = date.today() if args.source == "garmin" else None
    report = analyse(runs, zones, as_of=as_of)
    if args.json:
        print(render_json(report))
    else:
        print(render_text(report, terminal_style(sys.stdout, os.environ)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
