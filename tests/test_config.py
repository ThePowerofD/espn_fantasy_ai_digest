import os

import pytest

from espn_digest.config import ConfigError, load_config, load_dotenv
from factories import FAKE_S2, FAKE_SWID


def write_env(folder, text):
    (folder / ".env").write_text(text, encoding="utf-8")


def test_loads_values_from_dotenv(fake_env):
    cfg = load_config()
    assert cfg.league_id == 123
    assert cfg.espn_s2 == FAKE_S2
    assert cfg.swid == FAKE_SWID
    assert cfg.season == 2026
    assert cfg.team_id is None
    assert cfg.tz == "America/Mexico_City"


def test_defaults_when_optional_values_missing(clean_env):
    write_env(clean_env, f"LEAGUE_ID=1\nESPN_S2=x\nSWID={FAKE_SWID}\n")
    cfg = load_config()
    assert cfg.tz == "America/Mexico_City"
    assert str(cfg.output_dir) == "output"


def test_quotes_comments_and_export_are_handled(clean_env):
    write_env(clean_env, '# comment\n\nexport LEAGUE_ID="42"\nESPN_S2=\'abc\'\nSWID = {A-B}\n')
    load_dotenv()
    assert os.environ["LEAGUE_ID"] == "42"
    assert os.environ["ESPN_S2"] == "abc"
    assert os.environ["SWID"] == "{A-B}"


def test_real_environment_wins_over_dotenv(fake_env):
    os.environ["LEAGUE_ID"] = "999"
    assert load_config().league_id == 999


@pytest.mark.parametrize("missing", ["LEAGUE_ID", "ESPN_S2", "SWID"])
def test_missing_required_value_is_an_error(clean_env, missing):
    values = {"LEAGUE_ID": "1", "ESPN_S2": "x", "SWID": FAKE_SWID}
    del values[missing]
    write_env(clean_env, "".join(f"{k}={v}\n" for k, v in values.items()))
    with pytest.raises(ConfigError, match=missing):
        load_config()


def test_swid_without_braces_is_rejected_without_echoing_it(clean_env):
    write_env(clean_env, "LEAGUE_ID=1\nESPN_S2=x\nSWID=SECRET-SWID-VALUE\n")
    with pytest.raises(ConfigError, match="curly braces") as err:
        load_config()
    assert "SECRET-SWID-VALUE" not in str(err.value)


def test_non_integer_league_id(clean_env):
    write_env(clean_env, f"LEAGUE_ID=abc\nESPN_S2=x\nSWID={FAKE_SWID}\n")
    with pytest.raises(ConfigError, match="LEAGUE_ID must be an integer"):
        load_config()


def test_repr_never_shows_credentials(fake_env):
    cfg = load_config()
    for text in (repr(cfg), str(cfg)):
        assert FAKE_S2 not in text and FAKE_SWID not in text
        assert "<redacted>" in text
