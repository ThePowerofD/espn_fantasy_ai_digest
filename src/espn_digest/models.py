"""Plain data handed from fetch to render.

Everything here is a frozen dataclass of builtins: no espn_api objects, no
credentials. Datetimes are timezone-aware UTC; render converts them for display.

Only data that changes week to week belongs here. Static league rules live in
`LeagueRules`, rendered once as paste-in context, not in every digest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LineupPlayer:
    name: str
    position: str
    slot: str  # lineup slot, e.g. "QB", "RB/WR", "BE", "IR"
    pro_team: str
    opponent: str | None  # None on a bye
    home: bool | None  # None when unknown or on a bye
    kickoff: datetime | None  # aware UTC
    points: float
    projected: float
    injury_status: str  # "ACTIVE", "QUESTIONABLE", ...
    on_bye: bool
    opp_pos_rank: int  # opponent defense rank vs this position: 1 toughest, 32 easiest, 0 unknown
    eligible_slots: tuple[str, ...] = ()  # starting slots this player may fill
    bye_week: int | None = None
    recent_points: tuple[float | None, ...] = ()  # last few weeks, oldest first; None = no game


@dataclass(frozen=True)
class FreeAgent:
    name: str
    position: str
    pro_team: str
    injury_status: str
    percent_owned: float  # -1 when unknown
    projected: float = 0.0  # this week
    eligible_slots: tuple[str, ...] = ()
    on_waivers: bool = False  # False = free agent, can be added right away
    waiver_clears: datetime | None = None  # aware UTC, ESPN's waiverProcessDate
    bye_week: int | None = None


@dataclass(frozen=True)
class NewsItem:
    player: str
    published: datetime  # aware UTC
    headline: str


@dataclass(frozen=True)
class Transaction:
    when: datetime  # aware UTC
    team: str
    action: str
    player: str


@dataclass(frozen=True)
class Matchup:
    opponent_name: str
    i_am_home: bool
    my_score: float
    my_projected: float
    opp_score: float
    opp_projected: float
    opponent_lineup: tuple[LineupPlayer, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    season: int
    week: int
    generated_at: datetime  # aware UTC
    team_name: str
    num_teams: int
    waiver_rank: int
    faab_remaining: float | None  # None unless the league uses FAAB
    matchup: Matchup | None  # None when there is no matchup this week
    lineup: tuple[LineupPlayer, ...]  # every rostered slot, starters and bench/IR
    free_agents: tuple[FreeAgent, ...]
    activity: tuple[Transaction, ...]
    starting_slots: tuple[tuple[str, int], ...] = ()  # (slot, count) the league requires, bench/IR excluded
    ir_slots: int = 0  # IR spots the league allows
    recent_weeks: tuple[int, ...] = ()  # the weeks LineupPlayer.recent_points covers
    news: tuple[NewsItem, ...] = ()  # latest item per rostered player with recent news
    other_teams: tuple[tuple[str, tuple[LineupPlayer, ...]], ...] = ()  # (team name, roster)


@dataclass(frozen=True)
class LeagueRules:
    """Static league settings, for one-time context. Not part of the weekly digest."""

    league_name: str
    num_teams: int
    starting_slots: tuple[tuple[str, int], ...]
    bench_slots: int
    ir_slots: int
    waivers: str  # "FAAB (budget 100)" or "Waiver priority (no FAAB)"
    scoring: tuple[tuple[str, float], ...]  # (rule label, points), offense first
    waiver_days: tuple[str, ...] = ()  # days ESPN processes claims
    dropped_waiver_hours: int = 0  # hours a dropped player sits on waivers
    waiver_order_resets: bool = False
    trade_deadline: datetime | None = None  # aware UTC
    regular_season_weeks: int = 0
    playoff_teams: int = 0
    playoff_weeks: tuple[int, ...] = ()
    playoff_seeding: str = ""
