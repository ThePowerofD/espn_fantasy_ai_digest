"""Fetch a league snapshot from ESPN. Read-only; the only module that talks to the network.

Output is a `models.Snapshot` of plain data so `render` stays pure and offline-testable.
Credentials are passed straight to espn_api and never logged or put in the Snapshot.
Requests are kept few on purpose: one call per data set, news only for players with
recent news.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone

from espn_api.football import League
from espn_api.football.constant import POSITION_MAP, PRO_TEAM_MAP
from espn_api.football.player import Player

from .config import Config
from .models import (
    FreeAgent,
    LeagueRules,
    LineupPlayer,
    Matchup,
    NewsItem,
    Snapshot,
    Transaction,
)

ACTIVITY_COUNT = 10
RECENT_WEEKS = 3
NEWS_WINDOW = timedelta(days=7)
FA_POOL_SIZE = 300  # most-owned free agents to pick from
FA_PER_POSITION = 5
INJURED_FA_COUNT = 5
FA_POSITIONS = ("QB", "RB", "WR", "TE", "K", "D/ST")
IR_STATUS = {"OUT", "INJURY_RESERVE"}

_ABBREV_TO_PRO_ID = {abbrev.upper(): pid for pid, abbrev in PRO_TEAM_MAP.items() if pid}

log = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """Raised when the league can't be read or my team can't be identified."""


def _utc_from_ms(ms: int | float) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _normalize_id(raw: str) -> str:
    return raw.strip().strip("{}").lower()


def _pro_id(abbrev: str | None) -> int | None:
    return _ABBREV_TO_PRO_ID.get((abbrev or "").upper())


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


def bye_weeks(pro_schedule: dict) -> dict[int, int]:
    """Map pro team id -> bye week: ESPN's byeWeek, else the first week without a game."""
    byes: dict[int, int] = {}
    for pro_team in pro_schedule["settings"]["proTeams"]:
        tid = pro_team.get("id")
        if not tid:
            continue
        if pro_team.get("byeWeek"):
            byes[tid] = int(pro_team["byeWeek"])
            continue
        played = {int(w) for w, g in pro_team.get("proGamesByScoringPeriod", {}).items() if g}
        missing = [w for w in range(1, max(played, default=0) + 1) if w not in played]
        if missing:
            byes[tid] = missing[0]
    return byes


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


def _lineup_player(box_player, games, slots, byes, recent: tuple[float | None, ...] = ()) -> LineupPlayer:
    pro_id = _pro_id(box_player.proTeam)
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
        bye_week=byes.get(pro_id) if pro_id is not None else None,
        recent_points=recent,
    )


def weekly_points(card: dict) -> dict[int, dict[int, float]]:
    """Map player id -> {week: actual fantasy points} from a kona_playercard response."""
    points: dict[int, dict[int, float]] = {}
    for entry in card.get("players", []):
        player = entry.get("player", {})
        by_week = points.setdefault(player.get("id"), {})
        for stat in player.get("stats", []):
            # statSourceId 0 = actual (1 = projection); statSplitTypeId 1 = single scoring period.
            if stat.get("statSourceId") == 0 and stat.get("statSplitTypeId") == 1:
                by_week[int(stat["scoringPeriodId"])] = round(float(stat.get("appliedTotal", 0.0)), 1)
    return points


def last_news_dates(card: dict) -> dict[int, datetime]:
    return {
        e["player"]["id"]: _utc_from_ms(e["player"]["lastNewsDate"])
        for e in card.get("players", [])
        if e.get("player", {}).get("lastNewsDate")
    }


def latest_headline(news: dict) -> tuple[datetime, str] | None:
    """Newest player-specific (Rotowire) item from a player news response."""
    feed = (news.get("news") or {}).get("feed") or []
    items = [i for i in feed if i.get("type") == "Rotowire" and i.get("headline") and i.get("published")]
    if not items:
        return None
    newest = max(items, key=lambda i: i["published"])
    published = datetime.fromisoformat(newest["published"].replace("Z", "+00:00"))
    return published, " ".join(newest["headline"].split())


def _fetch_news(league: League, players, news_dates: dict[int, datetime], now: datetime) -> tuple[NewsItem, ...]:
    """Latest headline for players with news in NEWS_WINDOW; for injured players, whatever its age.

    A status like "Day To Day" can hide the real story (e.g. a suspension), so the
    newest item is worth showing even when it's old.
    """
    items: list[NewsItem] = []
    for p in players:
        when = news_dates.get(p.playerId)
        flagged = (p.injuryStatus or "ACTIVE") not in ("ACTIVE", "NORMAL")
        if when is None or (not flagged and now - when > NEWS_WINDOW):
            continue
        try:
            found = latest_headline(league.espn_request.get_player_news(p.playerId))
        except Exception as exc:  # noqa: BLE001 - news is optional; never fail the digest over it
            log.debug("News lookup failed for %s: %s", p.name, type(exc).__name__)
            continue
        if found and (flagged or now - found[0] <= NEWS_WINDOW):
            items.append(NewsItem(player=p.name, published=found[0], headline=found[1]))
    return tuple(sorted(items, key=lambda n: n.published, reverse=True))


def _free_agent_pool(league: League, week: int) -> list[dict]:
    """One request for the most-owned free agents and waiver players, with this week's projections."""
    filters = {
        "players": {
            "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
            "limit": FA_POOL_SIZE,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        }
    }
    data = league.espn_request.league_get(
        params={"view": "kona_player_info", "scoringPeriodId": week},
        headers={"x-fantasy-filter": json.dumps(filters)},
    )
    return data.get("players", [])


def select_free_agents(pool: list[dict], year: int, week: int, slots, byes) -> tuple[FreeAgent, ...]:
    """Top FA_PER_POSITION healthy players per position by projection, plus the most-owned injured ones."""
    agents = []
    for entry in pool:
        p = Player(entry, year)
        pro_id = _pro_id(p.proTeam)
        agents.append(
            FreeAgent(
                name=p.name,
                position=p.position,
                pro_team=p.proTeam,
                injury_status=p.injuryStatus or "ACTIVE",
                percent_owned=float(p.percent_owned),
                projected=float(p.stats.get(week, {}).get("projected_points", 0.0)),
                eligible_slots=_playable(p.eligibleSlots, slots),
                on_waivers=entry.get("status") == "WAIVERS",
                waiver_clears=_utc_from_ms(entry["waiverProcessDate"]) if entry.get("waiverProcessDate") else None,
                bye_week=byes.get(pro_id) if pro_id is not None else None,
            )
        )
    healthy = [a for a in agents if a.injury_status not in IR_STATUS]
    chosen: list[FreeAgent] = []
    for pos in FA_POSITIONS:
        at_pos = sorted((a for a in healthy if a.position == pos), key=lambda a: a.projected, reverse=True)
        chosen += at_pos[:FA_PER_POSITION]
    injured = sorted((a for a in agents if a.injury_status in IR_STATUS), key=lambda a: a.percent_owned, reverse=True)
    return tuple(chosen + injured[:INJURED_FA_COUNT])


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

    pro_schedule = league.espn_request.get_pro_schedule()
    games = pro_games_for_week(pro_schedule, week)
    byes = bye_weeks(pro_schedule)
    raw_settings = league.espn_request.league_get(params={"view": "mSettings"})
    slots = starting_slots(raw_settings)

    # My roster's recent weekly points and news dates: one player-card request.
    recent_weeks = tuple(range(max(1, week - RECENT_WEEKS), week))
    card = league.espn_request.get_player_card([p.playerId for p in team.roster], week)
    by_week = weekly_points(card)

    # Every team's lineup comes from the same box-score request.
    boxes = league.box_scores(week)
    matchup = None
    lineup: list[LineupPlayer] = []
    my_box_players = []
    rosters: dict[int, tuple[str, tuple[LineupPlayer, ...]]] = {}
    for box in boxes:
        for side, side_lineup in ((box.home_team, box.home_lineup), (box.away_team, box.away_lineup)):
            tid = getattr(side, "team_id", None)
            if tid is None or tid == team.team_id:
                continue
            rosters[tid] = (side.team_name, tuple(_lineup_player(p, games, slots, byes) for p in side_lineup))
        if team.team_id not in (getattr(box.home_team, "team_id", None), getattr(box.away_team, "team_id", None)):
            continue
        i_am_home = box.home_team.team_id == team.team_id
        my_box_players = box.home_lineup if i_am_home else box.away_lineup
        lineup = [
            _lineup_player(p, games, slots, byes, tuple(by_week.get(p.playerId, {}).get(w) for w in recent_weeks))
            for p in my_box_players
        ]
        opp = box.away_team if i_am_home else box.home_team
        if opp is not None and not isinstance(opp, int):
            matchup = Matchup(
                opponent_name=opp.team_name,
                i_am_home=i_am_home,
                my_score=float(box.home_score if i_am_home else box.away_score),
                my_projected=float(box.home_projected if i_am_home else box.away_projected),
                opp_score=float(box.away_score if i_am_home else box.home_score),
                opp_projected=float(box.away_projected if i_am_home else box.home_projected),
                opponent_lineup=rosters.get(opp.team_id, ("", ()))[1],
            )

    opponent_id = None
    if matchup is not None:
        opponent_id = next((tid for tid, (name, _r) in rosters.items() if name == matchup.opponent_name), None)
    other_teams = tuple(sorted((r for tid, r in rosters.items() if tid != opponent_id), key=lambda r: r[0].lower()))

    free_agents = select_free_agents(_free_agent_pool(league, week), league.year, week, slots, byes)
    activity = tuple(_transaction_rows(league.recent_activity(size=ACTIVITY_COUNT)))
    news = _fetch_news(league, my_box_players or team.roster, last_news_dates(card), now)

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
        recent_weeks=recent_weeks,
        news=news,
        other_teams=other_teams,
    )


def playoff_weeks(schedule: dict) -> tuple[int, ...]:
    """Scoring weeks of the playoff rounds, from ESPN's matchup-period map."""
    regular = int(schedule.get("matchupPeriodCount", 0))
    teams = int(schedule.get("playoffTeamCount", 0))
    if not regular or teams < 2:
        return ()
    rounds = math.ceil(math.log2(teams))
    length = int(schedule.get("playoffMatchupPeriodLength", 1)) or 1
    periods = schedule.get("matchupPeriods") or {}
    weeks: list[int] = []
    for mp in range(regular + 1, regular + rounds + 1):
        mapped = periods.get(str(mp))
        if mapped:
            weeks += [int(w) for w in mapped]
        else:
            first = weeks[-1] + 1 if weeks else regular + 1
            weeks += list(range(first, first + length))
    return tuple(weeks)


def build_rules(league: League) -> LeagueRules:
    """Static league settings, for one-time context."""
    raw_settings = league.espn_request.league_get(params={"view": "mSettings"})
    raw = raw_settings["settings"]
    acquisition = raw.get("acquisitionSettings", {})
    schedule = raw.get("scheduleSettings", {})
    deadline = (raw.get("tradeSettings") or {}).get("deadlineDate")
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
        waiver_days=tuple(d.title() for d in acquisition.get("waiverProcessDays", [])),
        dropped_waiver_hours=int(acquisition.get("waiverHours", 0)),
        waiver_order_resets=bool(acquisition.get("waiverOrderReset", False)),
        trade_deadline=_utc_from_ms(deadline) if deadline else None,
        regular_season_weeks=int(schedule.get("matchupPeriodCount", 0)),
        playoff_teams=int(schedule.get("playoffTeamCount", 0)),
        playoff_weeks=playoff_weeks(schedule),
        playoff_seeding=str(schedule.get("playoffSeedingRule", "")).replace("_", " ").capitalize(),
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
    except Exception as exc:  # noqa: BLE001
        # The message carries only the type. The original stays attached as __cause__
        # for `--debug`, which scrubs credentials before printing it.
        raise FetchError(f"Failed to read league {cfg.league_id}: {type(exc).__name__}") from exc


def fetch_snapshot(cfg: Config) -> Snapshot:
    return _read_league(cfg, lambda league: build_snapshot(league, cfg))


def fetch_rules(cfg: Config) -> LeagueRules:
    return _read_league(cfg, build_rules)
