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


@dataclass(frozen=True)
class FreeAgent:
    name: str
    position: str
    pro_team: str
    injury_status: str
    percent_owned: float  # -1 when unknown
    projected: float = 0.0  # this week
    eligible_slots: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class LeagueRules:
    """Static league settings, for one-time context. Not part of the weekly digest."""

    league_name: str
    num_teams: int
    starting_slots: tuple[tuple[str, int], ...]
    bench_slots: int
    ir_slots: int
    waivers: str  # "FAAB (budget 100)" or "Rolling waiver priority"
    scoring: tuple[tuple[str, float], ...]  # (rule label, points), offense first
