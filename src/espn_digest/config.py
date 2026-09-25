"""Configuration, loaded entirely from environment variables.

Nothing here is ever logged: `espn_s2` and `swid` are secrets and must not
appear in stdout, stderr, exceptions, or the generated report.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TZ = "America/Mexico_City"
DEFAULT_OUTPUT_DIR = "/app/output"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


def load_dotenv(path: str | os.PathLike[str] = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Existing environment variables win, so Docker-injected values are never
    shadowed. Missing file is not an error. Stdlib only, by design: the image
    ships no dependency beyond espn_api, and .env never enters the image.
    """
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Config:
    league_id: int
    espn_s2: str
    swid: str
    season: int
    team_id: int | None
    tz: str
    output_dir: Path

    def __repr__(self) -> str:  # pragma: no cover - defensive
        # Never let credentials reach a traceback or a debug print.
        return (
            f"Config(league_id={self.league_id}, season={self.season}, "
            f"team_id={self.team_id}, tz={self.tz!r}, "
            f"output_dir={str(self.output_dir)!r}, espn_s2=<redacted>, swid=<redacted>)"
        )

    __str__ = __repr__


def _required(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ConfigError(
            f"{name} is required but not set. Copy .env.example to .env and fill it in."
        )
    return value


def _optional_int(name: str) -> int | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}.") from exc


def load_config() -> Config:
    load_dotenv()

    raw_league = _required("LEAGUE_ID")
    try:
        league_id = int(raw_league)
    except ValueError as exc:
        raise ConfigError(f"LEAGUE_ID must be an integer, got {raw_league!r}.") from exc

    espn_s2 = _required("ESPN_S2")
    swid = _required("SWID")
    if not (swid.startswith("{") and swid.endswith("}")):
        # Shape check only -- the value itself is never echoed.
        raise ConfigError("SWID must include the surrounding curly braces, e.g. {ABC-...}.")

    season = _optional_int("SEASON") or _dt.date.today().year
    team_id = _optional_int("TEAM_ID")
    tz = (os.environ.get("TZ") or "").strip() or DEFAULT_TZ
    output_dir = Path((os.environ.get("OUTPUT_DIR") or "").strip() or DEFAULT_OUTPUT_DIR)

    return Config(
        league_id=league_id,
        espn_s2=espn_s2,
        swid=swid,
        season=season,
        team_id=team_id,
        tz=tz,
        output_dir=output_dir,
    )
