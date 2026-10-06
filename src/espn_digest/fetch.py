"""Fetch a league snapshot from ESPN. Read-only; the only module that talks to the network.

Output is a `models.Snapshot` of plain data so `render` stays pure and offline-testable.
Credentials are passed straight to espn_api and never logged or put in the Snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone

from espn_api.football import League
from espn_api.football.constant import POSITION_MAP, PRO_TEAM_MAP

from .config import Config
from .models import (
    FreeAgent,
    LeagueRules,
    LineupPlayer,
    Matchup,
    Snapshot,
    Transaction,
)

FREE_AGENT_COUNT = 10
ACTIVITY_COUNT = 10

_ABBREV_TO_PRO_ID = {abbrev.upper(): pid for pid, abbrev in PRO_TEAM_MAP.items() if pid}


class FetchError(RuntimeError):
    """Raised when the league can't be read or my team can't be identified."""


def _utc_from_ms(ms: int | float) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _normalize_id(raw: str) -> str:
    return raw.strip().strip("{}").lower()


def find_my_team(league: League, swid: str, team_id: int | None):
    """Match SWID against team owners; fall back to TEAM_ID if no owner matches."""
    wanted = _normalize_id(swid)
    for team in league.teams:
        for owner in team.owners or []:
            owner_id = owner.get("id") if isinstance(owner, dict) else None
            if owner_id and _normalize_id(owner_id) == wanted:
                return team
    if team_id is not None:
        for team in league.teams:
            if team.team_id == team_id:
                return team
    raise FetchError("Could not identify your team: no owner matched SWID and TEAM_ID is unset or unknown.")


def pro_games_for_week(pro_schedule: dict, week: int) -> dict[int, tuple[bool, datetime]]:
    """Map pro team id -> (is_home, kickoff UTC) for the given week.

    Built from the raw schedule because espn_api drops the home/away flag and
    converts game dates with the machine's local timezone.
    """
    games: dict[int, tuple[bool, datetime]] = {}
    for pro_team in pro_schedule["settings"]["proTeams"]:
        if not pro_team.get("id"):
            continue
        for game in pro_team.get("proGamesByScoringPeriod", {}).get(str(week), []):
            games[pro_team["id"]] = (
                game["homeProTeamId"] == pro_team["id"],
                _utc_from_ms(game["date"]),
            )
    return games


def starting_slots(settings: dict) -> tuple[tuple[str, int], ...]:
    """(slot name, count) for every starting slot, in ESPN's slot-id order.

    Read from raw rosterSettings: Settings.position_slot_counts can misalign labels.
    """
    counts = settings["settings"]["rosterSettings"]["lineupSlotCounts"]
    slots = []
    for slot_id, count in sorted(counts.items(), key=lambda kv: int(kv[0])):
        name = POSITION_MAP.get(int(slot_id), str(slot_id))
        if count and name not in ("BE", "IR"):
            slots.append((name, int(count)))
    return tuple(slots)


def _slot_count(settings: dict, name: str) -> int:
    counts = settings["settings"]["rosterSettings"]["lineupSlotCounts"]
    return sum(int(c) for sid, c in counts.items() if POSITION_MAP.get(int(sid)) == name)


def ir_slot_count(settings: dict) -> int:
    return _slot_count(settings, "IR")


def _playable(eligible, slots: tuple[tuple[str, int], ...]) -> tuple[str, ...]:
    """Eligible slots narrowed to the ones this league actually starts."""
    used = {name for name, _count in slots}
    return tuple(s for s in (eligible or ()) if s in used)


def _lineup_player(box_player, games: dict[int, tuple[bool, datetime]], slots) -> LineupPlayer:
    pro_id = _ABBREV_TO_PRO_ID.get((box_player.proTeam or "").upper())
    game = games.get(pro_id) if pro_id is not None else None
    on_bye = bool(box_player.on_bye_week) or game is None
    home, kickoff = game if game else (None, None)
    opponent = None if on_bye or box_player.pro_opponent == "None" else box_player.pro_opponent
    return LineupPlayer(
        name=box_player.name,
        position=box_player.position,
        slot=box_player.slot_position,
        pro_team=box_player.proTeam,
        opponent=opponent,
        home=home,
        kickoff=kickoff,
        points=float(box_player.points),
        projected=float(box_player.projected_points),
        injury_status=box_player.injuryStatus or "ACTIVE",
        on_bye=on_bye,
        opp_pos_rank=int(box_player.pro_pos_rank or 0),
        eligible_slots=_playable(box_player.eligibleSlots, slots),
    )


def _transaction_rows(activity) -> list[Transaction]:
    rows: list[Transaction] = []
    for item in activity:
        when = _utc_from_ms(item.date)
        for team, action, player, _bid in item.actions:
            rows.append(
                Transaction(
                    when=when,
                    team=getattr(team, "team_name", None) or "Unknown team",
                    action=str(action),
                    player=getattr(player, "name", None) or str(player),
                )
            )
    return rows


def build_snapshot(league: League, cfg: Config, *, now: datetime | None = None) -> Snapshot:
    """Read everything the report needs from an already-connected League."""
    now = now or datetime.now(timezone.utc)
    week = league.current_week
    team = find_my_team(league, cfg.swid, cfg.team_id)

    games = pro_games_for_week(league.espn_request.get_pro_schedule(), week)
    raw_settings = league.espn_request.league_get(params={"view": "mSettings"})
    slots = starting_slots(raw_settings)

    matchup = None
    lineup: list[LineupPlayer] = []
    for box in league.box_scores(week):
        if team.team_id not in (getattr(box.home_team, "team_id", None), getattr(box.away_team, "team_id", None)):
            continue
        i_am_home = box.home_team.team_id == team.team_id
        mine, theirs = (box.home_lineup, box.away_lineup) if i_am_home else (box.away_lineup, box.home_lineup)
        opp = box.away_team if i_am_home else box.home_team
        lineup = [_lineup_player(p, games, slots) for p in mine]
        if opp is not None and not isinstance(opp, int):
            matchup = Matchup(
                opponent_name=opp.team_name,
                i_am_home=i_am_home,
                my_score=float(box.home_score if i_am_home else box.away_score),
                my_projected=float(box.home_projected if i_am_home else box.away_projected),
                opp_score=float(box.away_score if i_am_home else box.home_score),
                opp_projected=float(box.away_projected if i_am_home else box.home_projected),
            )
        break

    free_agents = tuple(
        FreeAgent(
            name=p.name,
            position=p.position,
            pro_team=p.proTeam,
            injury_status=p.injuryStatus or "ACTIVE",
            percent_owned=float(p.percent_owned),
            projected=float(p.stats.get(week, {}).get("projected_points", 0.0)),
            eligible_slots=_playable(p.eligibleSlots, slots),
        )
        for p in league.free_agents(week=week, size=FREE_AGENT_COUNT)
    )
    activity = tuple(_transaction_rows(league.recent_activity(size=ACTIVITY_COUNT)))

    faab_remaining = None
    if league.settings.faab:
        faab_remaining = float(league.settings.acquisition_budget - team.acquisition_budget_spent)

    return Snapshot(
        season=cfg.season,
        week=week,
        generated_at=now,
        team_name=team.team_name,
        num_teams=len(league.teams),
        waiver_rank=team.waiver_rank,
        faab_remaining=faab_remaining,
        matchup=matchup,
        lineup=tuple(lineup),
        free_agents=free_agents,
        activity=activity,
        starting_slots=slots,
        ir_slots=ir_slot_count(raw_settings),
    )


def build_rules(league: League) -> LeagueRules:
    """Static league settings, for one-time context."""
    raw_settings = league.espn_request.league_get(params={"view": "mSettings"})
    s = league.settings
    waivers = f"FAAB (budget {s.acquisition_budget})" if s.faab else "Waiver priority (no FAAB)"
    # ESPN stat ids run passing -> rushing -> receiving -> kicking -> defense, so sorting groups them.
    scoring = tuple(
        (rule["label"], float(rule["points"]))
        for rule in sorted(s.scoring_format, key=lambda r: r.get("id", 0))
        if rule.get("points")
    )
    return LeagueRules(
        league_name=s.name,
        num_teams=len(league.teams),
        starting_slots=starting_slots(raw_settings),
        bench_slots=_slot_count(raw_settings, "BE"),
        ir_slots=ir_slot_count(raw_settings),
        waivers=waivers,
        scoring=scoring,
    )


def _read_league(cfg: Config, build):
    """Connect and run `build(league)`. Errors never include the cookies."""
    try:
        league = League(
            league_id=cfg.league_id,
            year=cfg.season,
            espn_s2=cfg.espn_s2,
            swid=cfg.swid,
        )
        return build(league)
    except FetchError:
        raise
    except Exception as exc:  # noqa: BLE001 - re-raised without the original message
        raise FetchError(f"Failed to read league {cfg.league_id}: {type(exc).__name__}") from None


def fetch_snapshot(cfg: Config) -> Snapshot:
    return _read_league(cfg, lambda league: build_snapshot(league, cfg))


def fetch_rules(cfg: Config) -> LeagueRules:
    return _read_league(cfg, build_rules)
