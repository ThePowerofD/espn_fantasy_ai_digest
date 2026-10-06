import os

import pytest

from factories import FAKE_S2, FAKE_SWID

CONFIG_KEYS = ("LEAGUE_ID", "ESPN_S2", "SWID", "SEASON", "TEAM_ID", "TZ", "OUTPUT_DIR")


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Isolated environment: no real config vars, cwd in a temp dir so the real .env is never read.

    os.environ is swapped for a plain dict because load_dotenv writes into it, and
    monkeypatch can't undo keys it never saw.
    """
    monkeypatch.setattr(os, "environ", {k: v for k, v in os.environ.items() if k not in CONFIG_KEYS})
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def fake_env(clean_env):
    """A complete, valid .env with fake credentials in the temp dir."""
    (clean_env / ".env").write_text(
        f"LEAGUE_ID=123\nESPN_S2={FAKE_S2}\nSWID={FAKE_SWID}\nSEASON=2026\n"
        f"TZ=America/Mexico_City\nOUTPUT_DIR=./output\n",
        encoding="utf-8",
    )
    return clean_env
