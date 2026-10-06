"""Render Markdown for Claude to read. Pure: no network, no clock, no env.

`render_report` is the weekly digest: only data that changes, stated as facts.
Judging moves (start/sit, drops, IR) is left to the reader, not decided here.
`render_rules` is static league context, meant to be pasted once.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .models import FreeAgent, LeagueRules, LineupPlayer, Snapshot, Transaction

_BENCH_SLOTS = {"BE", "IR"}
_HEALTHY = {"ACTIVE", "NORMAL", ""}
_IR_STATUS = {"OUT", "INJURY_RESERVE"}
_ACTION_LABELS = {
    "FA ADDED": "Added (FA)",
    "WAIVER ADDED": "Added (waiver)",
    "DROPPED": "Dropped",
    "TRADED": "Traded",
    "TRADE_SENT": "Traded away",
    "TRADE_RECEIVED": "Traded for",
}


def _fmt_dt(dt: datetime | None, tz: ZoneInfo) -> str:
    if dt is None:
        return "-"
    return dt.astimezone(tz).strftime("%a %b %d %H:%M")


def _fmt_pts(value: float) -> str:
    return f"{value:.1f}"


def _injury(status: str) -> str:
    return "" if status in _HEALTHY else status.replace("_", " ").title()


def _opponent(p: LineupPlayer) -> str:
    if p.on_bye or p.opponent is None:
        return "BYE"
    prefix = "vs" if p.home else "@" if p.home is False else ""
    return f"{prefix} {p.opponent}".strip()


def _elig(slots: tuple[str, ...]) -> str:
    return ", ".join(slots) or "-"


def _escape(text: str) -> str:
    return text.replace("|", "\\|")


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(_escape(c) for c in row) + " |" for row in rows]
    return lines


_LINEUP_HEADERS = ["Slot", "Player", "Pos", "Elig", "Opp", "Kickoff", "Opp rank", "Proj", "Pts", "Status"]


def _lineup_rows(players: list[LineupPlayer], tz: ZoneInfo) -> list[list[str]]:
    return [
        [
            p.slot,
            p.name,
            p.position,
            _elig(p.eligible_slots),
            _opponent(p),
            _fmt_dt(p.kickoff, tz) if not p.on_bye else "-",
            str(p.opp_pos_rank) if p.opp_pos_rank else "-",
            _fmt_pts(p.projected),
            _fmt_pts(p.points),
            _injury(p.injury_status),
        ]
        for p in players
    ]


def _free_agent_rows(agents: tuple[FreeAgent, ...]) -> list[list[str]]:
    return [
        [
            a.name,
            a.position,
            _elig(a.eligible_slots),
            a.pro_team,
            _fmt_pts(a.projected),
            f"{a.percent_owned:.1f}%" if a.percent_owned >= 0 else "-",
            _injury(a.injury_status),
        ]
        for a in agents
    ]


def _activity_rows(rows: tuple[Transaction, ...], tz: ZoneInfo) -> list[list[str]]:
    return [[_fmt_dt(t.when, tz), t.team, _ACTION_LABELS.get(t.action, t.action.title()), t.player] for t in rows]


def _empty_slots(starters: list[LineupPlayer], slots: tuple[tuple[str, int], ...]) -> list[str]:
    """One entry per required starting slot that has no player in it."""
    empty = []
    for slot, count in slots:
        filled = sum(1 for p in starters if p.slot == slot)
        empty += [slot] * max(0, count - filled)
    return empty


def _in_slot_order(starters: list[LineupPlayer], slots: tuple[tuple[str, int], ...]) -> list[LineupPlayer]:
    order = {slot: i for i, (slot, _count) in enumerate(slots)}
    return sorted(starters, key=lambda p: order.get(p.slot, len(order)))


def _roster_status(s: Snapshot, starters: list[LineupPlayer], empty_slots: list[str]) -> list[str]:
    """Roster facts worth noticing. No recommendations."""
    bench = [p for p in s.lineup if p.slot == "BE"]
    ir = [p for p in s.lineup if p.slot == "IR"]
    notes: list[str] = []

    notes += [f"Starting slot empty: {slot}" for slot in empty_slots]
    for p in starters:
        if p.on_bye:
            notes.append(f"Starter on bye: {p.name} ({p.slot})")
        elif p.injury_status not in _HEALTHY:
            notes.append(f"Starter injured: {p.name} ({p.slot}) - {_injury(p.injury_status)}")
    if s.ir_slots:
        notes.append(f"IR spots used: {len(ir)} of {s.ir_slots}")
    for p in ir:
        if p.injury_status not in _IR_STATUS:
            notes.append(f"On IR but status is {_injury(p.injury_status) or 'Active'}: {p.name}")
    for p in bench:
        if p.injury_status in _IR_STATUS:
            notes.append(f"On bench with status {_injury(p.injury_status)}: {p.name}")
    return [f"- {n}" for n in notes] or ["- Nothing unusual."]


def render_report(snapshot: Snapshot, tz: ZoneInfo) -> str:
    s = snapshot
    out: list[str] = [
        f"# {s.team_name} - Week {s.week}, {s.season}",
        "",
        f"_Generated {s.generated_at.astimezone(tz).strftime('%a %b %d %Y %H:%M %Z')}_",
        "",
        f"- **Waiver priority:** {s.waiver_rank} of {s.num_teams}",
    ]
    if s.faab_remaining is not None:
        out.append(f"- **FAAB remaining:** {s.faab_remaining:g}")

    out += ["", "## Matchup", ""]
    if s.matchup is None:
        out.append("No matchup this week.")
    else:
        m = s.matchup
        venue = "home" if m.i_am_home else "away"
        out += [
            f"**{s.team_name}** ({venue}) vs **{m.opponent_name}**",
            "",
            *_table(
                ["", "Score", "Projected"],
                [
                    [s.team_name, _fmt_pts(m.my_score), _fmt_pts(m.my_projected)],
                    [m.opponent_name, _fmt_pts(m.opp_score), _fmt_pts(m.opp_projected)],
                ],
            ),
        ]

    starters = [p for p in s.lineup if p.slot not in _BENCH_SLOTS]
    reserves = [p for p in s.lineup if p.slot in _BENCH_SLOTS]
    empty_slots = _empty_slots(starters, s.starting_slots)

    out += ["", "## Roster status", ""]
    out += _roster_status(s, starters, empty_slots)

    rows = _lineup_rows(_in_slot_order(starters, s.starting_slots), tz)
    rows += [[slot, "(empty)", "-", "-", "-", "-", "-", "-", "-", ""] for slot in empty_slots]
    out += ["", "## Starting lineup", ""]
    out += _table(_LINEUP_HEADERS, rows) if rows else ["No lineup available."]

    if reserves:
        out += ["", "## Bench and IR", ""]
        out += _table(_LINEUP_HEADERS, _lineup_rows(reserves, tz))

    out += ["", "## Top free agents", ""]
    out += (
        _table(["Player", "Pos", "Elig", "Team", "Proj", "Owned", "Status"], _free_agent_rows(s.free_agents))
        if s.free_agents
        else ["None."]
    )

    out += ["", "## Recent league activity", ""]
    out += _table(["When", "Team", "Action", "Player"], _activity_rows(s.activity, tz)) if s.activity else ["None."]

    return "\n".join(out) + "\n"


def render_rules(rules: LeagueRules, tz_name: str) -> str:
    """One-time context: league rules plus how to read the weekly digest."""
    r = rules
    lineup = ", ".join(f"{slot} x{count}" if count > 1 else slot for slot, count in r.starting_slots)
    out = [
        f"# League context - {r.league_name}",
        "",
        f"- **Teams:** {r.num_teams}",
        f"- **Starting lineup:** {lineup}",
        f"- **Bench:** {r.bench_slots} | **IR:** {r.ir_slots}",
        f"- **Waivers:** {r.waivers}",
        "",
        "## Scoring",
        "",
        *_table(["Rule", "Points"], [[label, f"{pts:g}"] for label, pts in r.scoring]),
        "",
        "## How to read the weekly digest",
        "",
        "- **Proj** is ESPN's projection for the week; **Pts** is points scored so far.",
        "- **Opp rank** is how the opposing defense ranks against that player's position: "
        "1 = toughest matchup, 32 = easiest.",
        "- **Elig** lists the starting slots a player can fill in this league.",
        f"- All times are {tz_name}.",
    ]
    return "\n".join(out) + "\n"
