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


def _lineup_headers(recent_weeks: tuple[int, ...]) -> list[str]:
    recent = f"Wk {recent_weeks[0]}-{recent_weeks[-1]} pts" if recent_weeks else "Recent pts"
    return ["Slot", "Player", "Pos", "Elig", "Opp", "Kickoff", "Opp rank", "Proj", "Pts", recent, "Bye", "Status"]


def _recent(points: tuple[float | None, ...]) -> str:
    return ", ".join("-" if v is None else f"{v:.1f}" for v in points) or "-"


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
            _recent(p.recent_points),
            str(p.bye_week) if p.bye_week else "-",
            _injury(p.injury_status),
        ]
        for p in players
    ]


_OPPONENT_HEADERS = ["Slot", "Player", "Pos", "Opp", "Kickoff", "Proj", "Pts", "Status"]


def _opponent_rows(players: list[LineupPlayer], tz: ZoneInfo) -> list[list[str]]:
    return [
        [
            p.slot,
            p.name,
            p.position,
            _opponent(p),
            _fmt_dt(p.kickoff, tz) if not p.on_bye else "-",
            _fmt_pts(p.projected),
            _fmt_pts(p.points),
            _injury(p.injury_status),
        ]
        for p in players
    ]


def _availability(a: FreeAgent, tz: ZoneInfo) -> str:
    if not a.on_waivers:
        return "FA"
    return f"Waivers, clears {_fmt_dt(a.waiver_clears, tz)}" if a.waiver_clears else "Waivers"


_FREE_AGENT_HEADERS = ["Player", "Pos", "Elig", "Team", "Bye", "Proj", "Owned", "Avail", "Status"]


def _free_agent_rows(agents: list[FreeAgent], tz: ZoneInfo) -> list[list[str]]:
    return [
        [
            a.name,
            a.position,
            _elig(a.eligible_slots),
            a.pro_team,
            str(a.bye_week) if a.bye_week else "-",
            _fmt_pts(a.projected),
            f"{a.percent_owned:.1f}%" if a.percent_owned >= 0 else "-",
            _availability(a, tz),
            _injury(a.injury_status),
        ]
        for a in agents
    ]


def _compact_roster(players: tuple[LineupPlayer, ...], slots: tuple[tuple[str, int], ...]) -> str:
    """One line per team: starters in slot order, then bench and IR, as 'Name POS proj [status]'."""

    def entry(p: LineupPlayer) -> str:
        status = "bye" if p.on_bye else _injury(p.injury_status)
        return f"{p.name} {p.position} {_fmt_pts(p.projected)}" + (f" [{status}]" if status else "")

    starters = _in_slot_order([p for p in players if p.slot not in _BENCH_SLOTS], slots)
    bench = [p for p in players if p.slot == "BE"]
    ir = [p for p in players if p.slot == "IR"]
    parts = ["Start: " + "; ".join(entry(p) for p in starters)]
    if bench:
        parts.append("Bench: " + "; ".join(entry(p) for p in bench))
    if ir:
        parts.append("IR: " + "; ".join(entry(p) for p in ir))
    return " | ".join(parts)


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

    headers = _lineup_headers(s.recent_weeks)
    rows = _lineup_rows(_in_slot_order(starters, s.starting_slots), tz)
    rows += [[slot, "(empty)"] + ["-"] * (len(headers) - 3) + [""] for slot in empty_slots]
    out += ["", "## Starting lineup", ""]
    out += _table(headers, rows) if rows else ["No lineup available."]

    if reserves:
        out += ["", "## Bench and IR", ""]
        out += _table(headers, _lineup_rows(reserves, tz))

    out += ["", "## Player news (last 7 days; injured players: latest item)", ""]
    out += [f"- **{n.player}** ({_fmt_dt(n.published, tz)}): {n.headline}" for n in s.news] or ["- None."]

    if s.matchup is not None and s.matchup.opponent_lineup:
        opp_players = s.matchup.opponent_lineup
        opp_starters = _in_slot_order([p for p in opp_players if p.slot not in _BENCH_SLOTS], s.starting_slots)
        out += ["", f"## Opponent lineup - {s.matchup.opponent_name}", ""]
        out += _table(_OPPONENT_HEADERS, _opponent_rows(opp_starters, tz))

    healthy = [a for a in s.free_agents if a.injury_status not in _IR_STATUS]
    injured = [a for a in s.free_agents if a.injury_status in _IR_STATUS]
    out += ["", "## Free agents - top 5 per position by projection", ""]
    out += _table(_FREE_AGENT_HEADERS, _free_agent_rows(healthy, tz)) if healthy else ["None."]
    if injured:
        out += ["", "## Free agents - Out or IR, most owned", ""]
        out += _table(_FREE_AGENT_HEADERS, _free_agent_rows(injured, tz))

    out += ["", "## Recent league activity", ""]
    out += _table(["When", "Team", "Action", "Player"], _activity_rows(s.activity, tz)) if s.activity else ["None."]

    if s.other_teams:
        out += ["", "## Other rosters", "", "_Name POS proj [status or bye]_", ""]
        out += [f"- **{name}** - {_compact_roster(players, s.starting_slots)}" for name, players in s.other_teams]

    return "\n".join(out) + "\n"


def render_rules(rules: LeagueRules, tz_name: str) -> str:
    """One-time context: league rules plus how to read the weekly digest."""
    r = rules
    tz = ZoneInfo(tz_name)
    lineup = ", ".join(f"{slot} x{count}" if count > 1 else slot for slot, count in r.starting_slots)
    out = [
        f"# League context - {r.league_name}",
        "",
        f"- **Teams:** {r.num_teams}",
        f"- **Starting lineup:** {lineup}",
        f"- **Bench:** {r.bench_slots} | **IR:** {r.ir_slots}",
        f"- **Waivers:** {r.waivers}",
    ]
    if r.waiver_days:
        out.append(f"- **Waivers process on:** {', '.join(r.waiver_days)}")
    if r.dropped_waiver_hours:
        out.append(f"- **Dropped players sit on waivers:** {r.dropped_waiver_hours} hours")
    out.append(f"- **Waiver order resets weekly:** {'yes' if r.waiver_order_resets else 'no'}")
    if r.trade_deadline:
        out.append(f"- **Trade deadline:** {r.trade_deadline.astimezone(tz).strftime('%a %b %d %Y %H:%M')}")
    if r.regular_season_weeks:
        out.append(f"- **Regular season:** weeks 1-{r.regular_season_weeks}")
    if r.playoff_teams:
        weeks = ", ".join(str(w) for w in r.playoff_weeks) or "?"
        seeding = f", seeded by {r.playoff_seeding.lower()}" if r.playoff_seeding else ""
        out.append(f"- **Playoffs:** {r.playoff_teams} teams, weeks {weeks}{seeding}")
    out += [
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
        "- **Wk N-M pts** are actual points in each recent week, oldest first; '-' means no game.",
        "- **Bye** is the player's NFL bye week.",
        "- **Avail** on free agents: FA = can be added now; Waivers = a claim, processed at the time shown.",
        "- Free agents are picked from the ~300 most-owned available players.",
        f"- All times are {tz_name}, converted from UTC (daylight saving changes are handled).",
    ]
    return "\n".join(out) + "\n"
