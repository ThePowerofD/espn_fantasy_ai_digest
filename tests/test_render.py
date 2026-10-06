from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from espn_digest.models import LeagueRules, NewsItem
from espn_digest.render import render_report, render_rules
from factories import NOW, SLOTS, bye_player, free_agent, player, snapshot

MX = ZoneInfo("America/Mexico_City")


def section(report: str, title: str) -> str:
    """Text of one '## title' section, up to the next '## '."""
    start = report.index(f"## {title}")
    end = report.find("\n## ", start + 1)
    return report[start:end if end != -1 else None]


def test_header_has_week_waiver_and_generated_time_in_local_tz():
    r = render_report(snapshot(), MX)
    assert r.startswith("# Me - Week 5, 2026")
    assert "Generated Thu Oct 08 2026 06:00 CST" in r
    assert "**Waiver priority:** 4 of 10" in r
    assert "FAAB" not in r


def test_faab_shown_only_when_league_uses_it():
    assert "**FAAB remaining:** 42" in render_report(snapshot(faab_remaining=42.0), MX)


def test_roster_status_states_facts_only():
    lineup = (
        player("Hurt Starter", "WR", injury_status="QUESTIONABLE"),
        bye_player("Bye Starter", "RB"),
        player("Healed", "IR"),
        player("Out Bencher", "BE", injury_status="OUT"),
        player("DTD Bencher", "BE", injury_status="DAY_TO_DAY"),
    )
    status = section(render_report(snapshot(lineup=lineup), MX), "Roster status")
    for fact in (
        "Starting slot empty: QB",
        "Starting slot empty: TE",
        "Starter injured: Hurt Starter (WR) - Questionable",
        "Starter on bye: Bye Starter (RB)",
        "IR spots used: 1 of 3",
        "On IR but status is Active: Healed",
        "On bench with status Out: Out Bencher",
    ):
        assert fact in status
    assert "DTD Bencher" not in status
    lowered = status.lower()
    assert "start " not in lowered.replace("starter", "").replace("starting", "")
    assert "drop" not in lowered


def test_nothing_unusual_when_roster_is_clean():
    full = tuple(player(f"P{i}", slot) for i, (slot, count) in enumerate(SLOTS) for _ in range(count))
    status = section(render_report(snapshot(lineup=full, ir_slots=0), MX), "Roster status")
    assert "Nothing unusual." in status


def test_lineup_is_in_slot_order_with_empty_rows_last():
    lineup = (player("The WR", "WR"), player("The QB", "QB", position="QB", eligible_slots=("QB",)))
    table = section(render_report(snapshot(lineup=lineup), MX), "Starting lineup")
    assert table.index("The QB") < table.index("The WR") < table.index("(empty)")


def test_lineup_columns_recent_points_bye_and_opponent():
    r = render_report(snapshot(lineup=(player("Star", "WR", home=False),)), MX)
    table = section(r, "Starting lineup")
    assert "Wk 2-4 pts" in table
    assert "| Star | WR | RB/WR, WR | @ NO | Sun Oct 11 06:00 | 12 | 10.0 | 0.0 | 8.0, -, 12.5 | 11 |  |" in table


def test_bench_and_ir_section():
    r = render_report(snapshot(lineup=(player("Starter", "WR"), player("Benchie", "BE"))), MX)
    assert "Benchie" in section(r, "Bench and IR")
    assert "Benchie" not in section(r, "Starting lineup")


def test_kickoff_times_follow_us_daylight_saving_end():
    # 1:00 PM Eastern is 17:00 UTC before Nov 1 and 18:00 UTC after; Mexico City has no DST.
    before = player("Before", "WR", kickoff=datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc))
    after = player("After", "QB", kickoff=datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc))
    r = render_report(snapshot(lineup=(before, after)), MX)
    assert "Sun Oct 25 11:00" in r
    assert "Sun Nov 08 12:00" in r


def test_news_section():
    news = (NewsItem("Star", datetime(2026, 10, 5, 22, 0, tzinfo=timezone.utc), "Star caught 7 passes."),)
    assert "- **Star** (Mon Oct 05 16:00): Star caught 7 passes." in render_report(snapshot(news=news), MX)
    assert "- None." in section(render_report(snapshot(), MX), "Player news")


def test_opponent_lineup_shows_starters_only():
    opp = section(render_report(snapshot(), MX), "Opponent lineup - Rival")
    assert "Rival QB" in opp
    assert "Rival Bench" not in opp


def test_no_opponent_sections_without_matchup():
    r = render_report(snapshot(matchup=None), MX)
    assert "No matchup this week." in r
    assert "## Opponent lineup" not in r


def test_free_agents_split_healthy_and_injured_with_availability():
    agents = (
        free_agent("Add Now"),
        free_agent("Claim Me", on_waivers=True, waiver_clears=NOW + timedelta(hours=20)),
        free_agent("Hurt FA", injury_status="OUT"),
    )
    r = render_report(snapshot(free_agents=agents), MX)
    healthy = section(r, "Free agents - top 5 per position")
    injured = section(r, "Free agents - Out or IR")
    assert "| Add Now | WR | RB/WR, WR | BUF | 7 | 9.5 | 40.0% | FA |  |" in healthy
    assert "Waivers, clears Fri Oct 09 02:00" in healthy
    assert "Hurt FA" in injured and "Hurt FA" not in healthy


def test_other_rosters_compact_with_bye_and_status():
    roster = (player("Their QB", "QB", position="QB"), bye_player("Their Bye", "WR"),
              player("Their Hurt", "BE", injury_status="QUESTIONABLE"), player("Their IR", "IR", injury_status="OUT"))
    r = render_report(snapshot(other_teams=(("Other Team", roster),)), MX)
    line = next(l for l in r.splitlines() if l.startswith("- **Other Team**"))
    assert "Start: Their QB QB 10.0; Their Bye WR 10.0 [bye]" in line
    assert "Bench: Their Hurt WR 10.0 [Questionable]" in line
    assert "IR: Their IR WR 10.0 [Out]" in line


def test_pipes_in_names_are_escaped_in_tables():
    r = render_report(snapshot(team_name="A|B"), MX)
    assert "| A\\|B | 0.0 | 110.0 |" in r


def test_render_rules_is_static_context():
    rules = LeagueRules(
        league_name="Test League",
        num_teams=10,
        starting_slots=SLOTS,
        bench_slots=6,
        ir_slots=3,
        waivers="Waiver priority (no FAAB)",
        scoring=(("TD Pass", 4.0), ("Passing Yards", 0.04)),
        waiver_days=("Monday", "Wednesday"),
        dropped_waiver_hours=24,
        waiver_order_resets=True,
        trade_deadline=datetime(2026, 12, 2, 17, 0, tzinfo=timezone.utc),
        regular_season_weeks=14,
        playoff_teams=6,
        playoff_weeks=(15, 16, 17),
        playoff_seeding="Total points scored",
    )
    text = render_rules(rules, "America/Mexico_City")
    for expected in (
        "# League context - Test League",
        "**Starting lineup:** QB, RB x2, RB/WR, WR x2, TE, D/ST, K",
        "**Waivers process on:** Monday, Wednesday",
        "**Trade deadline:** Wed Dec 02 2026 11:00",
        "**Playoffs:** 6 teams, weeks 15, 16, 17, seeded by total points scored",
        "| TD Pass | 4 |",
        "| Passing Yards | 0.04 |",
        "1 = toughest matchup, 32 = easiest",
    ):
        assert expected in text
