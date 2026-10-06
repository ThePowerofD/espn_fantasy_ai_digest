"""Builders for test data: models with sensible defaults, and raw ESPN-shaped dicts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from espn_digest.models import FreeAgent, LineupPlayer, Matchup, Snapshot

# Fake credentials. ESPN_S2 includes URL-encoded characters like the real cookie does.
FAKE_S2 = "AEBfake%2Bs2%2Fcookie%3Dvalue"
FAKE_SWID = "{11111111-2222-3333-4444-555555555555}"

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)  # Thu 06:00 in Mexico City
SLOTS = (("QB", 1), ("RB", 2), ("RB/WR", 1), ("WR", 2), ("TE", 1), ("D/ST", 1), ("K", 1))


def player(name: str = "Player", slot: str = "WR", **overrides) -> LineupPlayer:
    base = LineupPlayer(
        name=name,
        position="WR",
        slot=slot,
        pro_team="ATL",
        opponent="NO",
        home=True,
        kickoff=NOW + timedelta(days=3),
        points=0.0,
        projected=10.0,
        injury_status="ACTIVE",
        on_bye=False,
        opp_pos_rank=12,
        eligible_slots=("RB/WR", "WR"),
        bye_week=11,
        recent_points=(8.0, None, 12.5),
    )
    return replace(base, **overrides)


def bye_player(name: str = "Bye Guy", slot: str = "WR", **overrides) -> LineupPlayer:
    return player(name, slot, opponent=None, home=None, kickoff=None, on_bye=True, opp_pos_rank=0, **overrides)


def free_agent(name: str = "FA", position: str = "WR", **overrides) -> FreeAgent:
    base = FreeAgent(
        name=name,
        position=position,
        pro_team="BUF",
        injury_status="ACTIVE",
        percent_owned=40.0,
        projected=9.5,
        eligible_slots=("RB/WR", "WR"),
        on_waivers=False,
        waiver_clears=None,
        bye_week=7,
    )
    return replace(base, **overrides)


def snapshot(**overrides) -> Snapshot:
    base = Snapshot(
        season=2026,
        week=5,
        generated_at=NOW,
        team_name="Me",
        num_teams=10,
        waiver_rank=4,
        faab_remaining=None,
        matchup=Matchup(
            opponent_name="Rival",
            i_am_home=True,
            my_score=0.0,
            my_projected=110.0,
            opp_score=0.0,
            opp_projected=120.0,
            opponent_lineup=(player("Rival QB", "QB"), player("Rival Bench", "BE")),
        ),
        lineup=(player("Starter", "WR"),),
        free_agents=(),
        activity=(),
        starting_slots=SLOTS,
        ir_slots=3,
        recent_weeks=(2, 3, 4),
    )
    return replace(base, **overrides)


# ---- raw ESPN response shapes -------------------------------------------------


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def raw_free_agent(pid, name, slots, projected, owned, *, status="ACTIVE", waivers=False,
                   pro_team_id=1, week=5, year=2026, clears=None):
    """One entry of a kona_player_info response."""
    entry = {
        "id": pid,
        "status": "WAIVERS" if waivers else "FREEAGENT",
        "player": {
            "id": pid,
            "fullName": name,
            "eligibleSlots": slots,
            "proTeamId": pro_team_id,
            "injuryStatus": status,
            "ownership": {"percentOwned": owned},
            "stats": [
                {"seasonId": year, "scoringPeriodId": week, "statSourceId": 1,
                 "statSplitTypeId": 1, "appliedTotal": projected},
            ],
        },
    }
    if clears is not None:
        entry["waiverProcessDate"] = ms(clears)
    return entry
