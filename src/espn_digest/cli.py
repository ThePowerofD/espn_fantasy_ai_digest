"""Command line entry point: `python -m espn_digest.cli` (or `.\\digest.ps1`).

Default: fetch this week's snapshot and write the digest to OUTPUT_DIR, one file per day.
--rules: write the one-time league context (league_context.md) instead.
--stdout: print instead of writing a file.
--debug: on failure, print the full error with credentials scrubbed; log skipped news lookups.

Errors print a short message and exit non-zero; credentials are never printed.
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import ConfigError, load_config
from .fetch import FetchError, fetch_rules, fetch_snapshot
from .render import render_report, render_rules

RULES_FILENAME = "league_context.md"
REDACTED = "<redacted>"


def digest_filename(season: int, week: int, generated_at: datetime, tz: ZoneInfo) -> str:
    # One file per day, e.g. digest_2026_week05_10-06_tue.md; re-running the same day refreshes it.
    day = generated_at.astimezone(tz)
    return f"digest_{season}_week{week:02d}_{day:%m-%d}_{day:%a}.md".lower()


def scrub(text: str, secrets: list[str]) -> str:
    """Replace each secret, in raw and URL-encoded/decoded forms, with a placeholder."""
    for secret in secrets:
        if not secret:
            continue
        for form in sorted({secret, unquote(secret), quote(secret, safe="")}, key=len, reverse=True):
            text = text.replace(form, REDACTED)
    return text


def _write(output_dir: Path, name: str, text: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / name
    path.write_text(text, encoding="utf-8")
    return path


def _enable_debug_logging() -> None:
    # Only this package's logger: library loggers (urllib3, espn_api) stay quiet.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("debug: %(message)s"))
    logger = logging.getLogger("espn_digest")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="espn_digest", description="ESPN fantasy football digest for Claude.")
    parser.add_argument("--rules", action="store_true", help=f"write the one-time league context ({RULES_FILENAME})")
    parser.add_argument("--stdout", action="store_true", help="print the Markdown instead of writing a file")
    parser.add_argument("--debug", action="store_true", help="show full errors (credentials scrubbed)")
    args = parser.parse_args(argv)
    if args.debug:
        _enable_debug_logging()

    cfg = None
    try:
        cfg = load_config()
        tz = ZoneInfo(cfg.tz)
        if args.rules:
            name, text = RULES_FILENAME, render_rules(fetch_rules(cfg), cfg.tz)
        else:
            snapshot = fetch_snapshot(cfg)
            name = digest_filename(snapshot.season, snapshot.week, snapshot.generated_at, tz)
            text = render_report(snapshot, tz)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except ZoneInfoNotFoundError:
        print("Config error: unknown timezone in TZ.", file=sys.stderr)
        return 2
    except FetchError as exc:
        print(f"ESPN error: {exc}", file=sys.stderr)
        if args.debug:
            detail = "".join(traceback.format_exception(exc))
            print(scrub(detail, [cfg.espn_s2, cfg.swid]), file=sys.stderr)
        else:
            print("Run again with --debug for details.", file=sys.stderr)
        return 1

    if args.stdout:
        sys.stdout.write(text)
        return 0
    try:
        path = _write(cfg.output_dir, name, text)
    except OSError as exc:
        print(f"Could not write to {cfg.output_dir}: {exc.strerror}", file=sys.stderr)
        return 1
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
