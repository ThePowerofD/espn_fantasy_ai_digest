"""CLI behavior with fetch replaced by fakes. No network."""

from datetime import datetime, timezone
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from espn_digest import cli
from espn_digest.fetch import FetchError
from factories import FAKE_S2, FAKE_SWID, snapshot

MX = ZoneInfo("America/Mexico_City")


def test_digest_filename_uses_local_day():
    # 03:00 UTC Wednesday is still Tuesday evening in Mexico City.
    late_tuesday = datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)
    assert cli.digest_filename(2026, 5, late_tuesday, MX) == "digest_2026_week05_10-06_tue.md"


def test_scrub_removes_raw_and_decoded_secret_forms():
    text = f"cookie={FAKE_S2} decoded={unquote(FAKE_S2)} swid={FAKE_SWID}"
    cleaned = cli.scrub(text, [FAKE_S2, FAKE_SWID])
    assert FAKE_S2 not in cleaned and unquote(FAKE_S2) not in cleaned and FAKE_SWID not in cleaned
    assert cleaned.count(cli.REDACTED) == 3


def test_writes_day_tagged_digest(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_snapshot", lambda cfg: snapshot())
    assert cli.main([]) == 0
    written = fake_env / "output" / "digest_2026_week05_10-08_thu.md"
    assert written.read_text(encoding="utf-8").startswith("# Me - Week 5, 2026")
    assert "Wrote" in capsys.readouterr().out


def test_stdout_mode_writes_no_file(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_snapshot", lambda cfg: snapshot())
    assert cli.main(["--stdout"]) == 0
    assert capsys.readouterr().out.startswith("# Me - Week 5, 2026")
    assert not (fake_env / "output").exists()


def test_config_error_exit_code(clean_env, capsys):
    assert cli.main([]) == 2
    assert "Config error: LEAGUE_ID is required" in capsys.readouterr().err


def _failing_fetch(cfg):
    try:
        raise RuntimeError(f"request failed with cookie {cfg.espn_s2} and swid {cfg.swid}")
    except RuntimeError as exc:
        raise FetchError(f"Failed to read league {cfg.league_id}: RuntimeError") from exc


def test_fetch_error_is_short_without_debug(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_snapshot", _failing_fetch)
    assert cli.main([]) == 1
    err = capsys.readouterr().err
    assert "ESPN error: Failed to read league 123: RuntimeError" in err
    assert "--debug" in err
    assert "Traceback" not in err


def test_debug_shows_traceback_with_credentials_scrubbed(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_snapshot", _failing_fetch)
    assert cli.main(["--debug"]) == 1
    err = capsys.readouterr().err
    assert "Traceback" in err and "request failed with cookie <redacted> and swid <redacted>" in err
    assert FAKE_S2 not in err and unquote(FAKE_S2) not in err and FAKE_SWID not in err
