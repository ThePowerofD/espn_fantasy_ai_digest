"""The pure parts of fetch.py, fed ESPN-shaped dicts. No network."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from espn_digest.fetch import (
    FA_PER_POSITION,
    FetchError,
    bye_weeks,
    find_my_team,
    ir_slot_count,
    latest_headline,
    playoff_weeks,
    pro_games_for_week,
    select_free_agents,
    starting_slots,
    weekly_points,
)
from factories import FAKE_SWID, NOW, SLOTS, ms, raw_free_agent

KICKOFF = datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)


def game(home, away, when=KICKOFF):
    return {"homeProTeamId": home, "awayProTeamId": away, "date": ms(when)}


SCHEDULE = {
    "settings": {
        "proTeams": [
            {"id": 0, "abbrev": "FA"},
            {"id": 1, "abbrev": "ATL", "byeWeek": 9,
             "proGamesByScoringPeriod": {"5": [game(18, 1)]}},
            {"id": 18, "abbrev": "NO",  # no byeWeek field: fall back to the gap in the schedule
             "proGamesByScoringPeriod": {"1": [game(18, 3)], "2": [game(4, 18)], "3": [], "5": [game(18, 1)]}},
        ]
    }
}


def test_pro_games_for_week_keeps_home_away_and_utc_kickoff():
    games = pro_games_for_week(SCHEDULE, 5)
    assert games == {1: (False, KICKOFF), 18: (True, KICKOFF)}
    assert games[1][1].tzinfo is not None


def test_pro_games_for_week_missing_week_means_bye():
    assert pro_games_for_week(SCHEDULE, 3) == {}


def test_bye_weeks_prefers_espn_field_then_schedule_gap():
    assert bye_weeks(SCHEDULE) == {1: 9, 18: 3}


SETTINGS = {
    "settings": {
        "rosterSettings": {
            "lineupSlotCounts": {"0": 1, "2": 2, "3": 1, "4": 2, "6": 1, "16": 1, "17": 1,
                                 "20": 6, "21": 3, "23": 0, "5": 0}
        }
    }
}


def test_starting_slots_in_slot_order_without_bench_ir_or_unused():
    assert starting_slots(SETTINGS) == SLOTS


def test_ir_slot_count():
    assert ir_slot_count(SETTINGS) == 3


def test_weekly_points_keeps_only_single_week_actuals():
    card = {"players": [{"player": {"id": 7, "stats": [
        {"scoringPeriodId": 2, "statSourceId": 0, "statSplitTypeId": 1, "appliedTotal": 12.345},
        {"scoringPeriodId": 3, "statSourceId": 0, "statSplitTypeId": 1, "appliedTotal": 0},
        {"scoringPeriodId": 4, "statSourceId": 1, "statSplitTypeId": 1, "appliedTotal": 99},  # projection
        {"scoringPeriodId": 0, "statSourceId": 0, "statSplitTypeId": 0, "appliedTotal": 99},  # season total
    ]}}]}
    assert weekly_points(card) == {7: {2: 12.3, 3: 0.0}}


def test_latest_headline_picks_newest_player_blurb_and_tidies_whitespace():
    news = {"news": {"feed": [
        {"type": "Story", "headline": "General article", "published": "2026-10-06T10:00:00Z"},
        {"type": "Rotowire", "headline": "Older  blurb", "published": "2026-10-01T10:00:00Z"},
        {"type": "Rotowire", "headline": "Newer\n blurb", "published": "2026-10-05T10:00:00Z"},
    ]}}
    published, headline = latest_headline(news)
    assert headline == "Newer blurb"
    assert published == datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


def test_latest_headline_none_when_no_player_blurbs():
    assert latest_headline({"news": {"feed": [{"type": "Story", "headline": "x", "published": "2026-10-01T00:00:00Z"}]}}) is None
    assert latest_headline({"news": {}}) is None


def test_playoff_weeks_from_matchup_period_map():
    schedule = {"matchupPeriodCount": 14, "playoffTeamCount": 6, "playoffMatchupPeriodLength": 1,
                "matchupPeriods": {"15": [15], "16": [16], "17": [17]}}
    assert playoff_weeks(schedule) == (15, 16, 17)


def test_playoff_weeks_fallback_and_two_week_rounds():
    schedule = {"matchupPeriodCount": 13, "playoffTeamCount": 4, "playoffMatchupPeriodLength": 2}
    assert playoff_weeks(schedule) == (14, 15, 16, 17)


def test_playoff_weeks_without_playoffs():
    assert playoff_weeks({"matchupPeriodCount": 14, "playoffTeamCount": 0}) == ()


def test_select_free_agents_top_per_position_plus_injured():
    clears = NOW + timedelta(days=1)
    pool = [raw_free_agent(100 + i, f"RB {i}", [2, 3, 20, 21], projected=float(i), owned=10.0 + i)
            for i in range(7)]
    pool += [
        raw_free_agent(200, "Hurt Star", [2, 3, 20, 21], projected=0.0, owned=90.0, status="OUT"),
        raw_free_agent(201, "IR Guy", [4, 3, 20, 21], projected=0.0, owned=50.0, status="INJURY_RESERVE"),
        raw_free_agent(300, "Waiver WR", [3, 4, 20, 21], projected=11.0, owned=30.0, waivers=True, clears=clears),
        raw_free_agent(400, "Rams D/ST", [16, 20], projected=6.0, owned=80.0),
    ]
    agents = select_free_agents(pool, year=2026, week=5, slots=SLOTS, byes={1: 9})
    names = [a.name for a in agents]

    rbs = [a for a in agents if a.position == "RB" and a.injury_status == "ACTIVE"]
    assert [a.name for a in rbs] == ["RB 6", "RB 5", "RB 4", "RB 3", "RB 2"][:FA_PER_POSITION]
    assert names[-2:] == ["Hurt Star", "IR Guy"]  # injured last, most owned first

    wr = next(a for a in agents if a.name == "Waiver WR")
    assert wr.position == "WR" and wr.on_waivers and wr.waiver_clears == clears.replace(microsecond=0)
    assert wr.eligible_slots == ("RB/WR", "WR")  # BE/IR dropped, league slots only
    assert wr.bye_week == 9 and wr.projected == 11.0

    dst = next(a for a in agents if a.name == "Rams D/ST")
    assert dst.position == "D/ST" and not dst.on_waivers


def team(team_id, owner_id):
    return SimpleNamespace(team_id=team_id, owners=[{"id": owner_id}])


def test_find_my_team_matches_swid_ignoring_case_and_braces():
    league = SimpleNamespace(teams=[team(1, "{AAAA}"), team(5, FAKE_SWID.lower().strip("{}"))])
    assert find_my_team(league, FAKE_SWID, team_id=None).team_id == 5


def test_find_my_team_falls_back_to_team_id():
    league = SimpleNamespace(teams=[team(1, "{AAAA}"), team(5, "{BBBB}")])
    assert find_my_team(league, FAKE_SWID, team_id=5).team_id == 5


def test_find_my_team_fails_clearly():
    league = SimpleNamespace(teams=[team(1, "{AAAA}")])
    with pytest.raises(FetchError, match="Could not identify your team"):
        find_my_team(league, FAKE_SWID, team_id=None)
