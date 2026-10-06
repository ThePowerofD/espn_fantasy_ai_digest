# ESPN Fantasy AI Digest

Pulls your ESPN fantasy football league and writes a Markdown **digest**: a
factual snapshot of your roster, matchup, free agents and league activity, made
to be pasted into Claude (or another AI) so it can advise you.

The digest states facts only. It never recommends moves, because judging
start/sit, drops and pickups is the AI's job, and baked-in advice would bias it.

Read-only: it never changes anything in your league, and it never prints or logs
your ESPN cookies.

---

## How it's meant to be used

1. **Once:** paste `output/league_context.md` into Claude. It holds the static
   rules (lineup slots, scoring, waivers, trade deadline, playoffs) and explains
   how to read the digest's columns.
2. **Whenever you want advice** (e.g. Tuesday after waivers, Thursday before
   the first game, Sunday morning): run the digest and paste the new file.

Each run writes one file per day, so you can compare how things changed during
the week:

```
output/
  league_context.md                  one-time context (refresh with --rules)
  digest_2026_week05_10-06_tue.md
  digest_2026_week05_10-08_thu.md
  digest_2026_week05_10-11_sun.md
```

Running again on the same day replaces that day's file with fresh data.

---

## Setup (Windows)

### 1. Python environment

```powershell
cd E:\coding\small_projects\espn_fantasy_ai_digest
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
```

### 2. Your ESPN cookies

Private leagues need two cookies from a browser where you're logged in to ESPN.
You copy them by hand. The tool deliberately does not log in or read your
browser, so nothing automated touches your account.

1. Open https://fantasy.espn.com and go to your league.
2. Press `F12` and open **Application** (Chrome/Edge) or **Storage** (Firefox),
   then **Cookies**, then `https://fantasy.espn.com`.
3. Copy the values of **`espn_s2`** and **`SWID`**.

Treat both as passwords.

### 3. The `.env` file

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in:

```
LEAGUE_ID=1234567890        # from the league URL: ...?leagueId=1234567890
ESPN_S2=AEB...              # paste as-is: no quotes, keep any % characters
SWID={XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}   # keep the curly braces
```

Optional: `SEASON` (default: this year), `TEAM_ID` (only a fallback; your team is
found from `SWID`), `TZ` (default `America/Mexico_City`), `OUTPUT_DIR` (default
`./output`).

`.env` is git-ignored and Docker-ignored. Never commit it, and fill in `.env`,
**not** `.env.example`. The example file is committed to git.

### 4. Allow local scripts (once)

Windows blocks `.ps1` scripts by default. To allow scripts you create locally,
for your account only:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## Running it

```powershell
.\digest.ps1              # write today's digest to output\
.\digest.ps1 --rules      # rewrite output\league_context.md (only if league rules change)
.\digest.ps1 --stdout     # print instead of saving
.\digest.ps1 --debug      # on failure, show the full error (cookies scrubbed)
```

`digest.ps1` works from any folder (use its full path) and needs no venv
activation. Without the script:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python -m espn_digest.cli
```

### With Docker

```powershell
docker compose run --rm report            # digest -> ./output
docker compose run --rm report --rules    # league context
docker compose run --rm test              # tests (no credentials needed)
```

---

## What's in the digest

| Section | Contents |
|---|---|
| Header | Week, when it was generated, your waiver priority (FAAB if your league uses it) |
| Matchup | Your score and projection vs your opponent's |
| Roster status | Facts worth noticing: empty starting slots, injured or bye starters, IR spots used, healthy players on IR, Out players on the bench |
| Starting lineup / Bench and IR | Slot, eligible slots, NFL opponent (home `vs` / away `@`), kickoff, opponent rank vs position, projection, points, last 3 weeks' points, bye week, injury status |
| Player news | Latest ESPN/Rotowire note for players with news in the last 7 days, and for every injured player regardless of age (a "Day To Day" tag can hide a suspension) |
| Opponent lineup | Their starters with projections and statuses |
| Free agents | Top 5 healthy per position by projection, plus the most-owned Out/IR players; each marked FA (add now) or Waivers (with when the claim processes) |
| Recent league activity | Adds, drops, trades |
| Other rosters | Every other team, one line each: player, position, projection, status or bye |

**Opp rank:** 1 = toughest defense against that position, 32 = easiest
(verified against ESPN's points-allowed data).

### Known limits

- **Practice reports (DNP/LP/FP)** aren't available: ESPN's fantasy data doesn't
  include them.
- **Projections** are ESPN's. Free agents are picked from the ~300 most-owned
  available players, so a deep sleeper can be missed.
- **Standings** are left out on purpose. They don't affect weekly decisions,
  and playoff seeding in this league is by total points.

---

## Troubleshooting

| Message | Meaning and fix |
|---|---|
| `ESPN error: ... ESPNAccessDenied` | Cookies expired or were mistyped. Copy fresh `espn_s2` and `SWID` from your browser into `.env`. Logging out of ESPN can invalidate them. |
| `ESPN error: ... ESPNInvalidLeague` | Wrong `LEAGUE_ID` or `SEASON`. |
| `Config error: X is required` | `.env` is missing, misnamed (`.env.txt`?), or that line is empty. |
| `Config error: SWID must include the surrounding curly braces` | Paste `SWID` with its `{` `}`. |
| `running scripts is disabled on this system` | Run the `Set-ExecutionPolicy` line from setup step 4. |
| `No module named 'espn_digest'` | Run through `digest.ps1`, or set `PYTHONPATH=src`. |
| Anything else | Run with `--debug` for the full error. Cookie values are replaced with `<redacted>`. |

---

## Development

```
src/espn_digest/
  config.py    reads .env / environment; credentials never printed
  fetch.py     the only module that talks to ESPN; returns plain data
  models.py    frozen dataclasses passed from fetch to render
  render.py    pure Markdown rendering: no network, clock or env
  cli.py       command line: file naming, --rules/--stdout/--debug
tests/         offline tests with ESPN-shaped sample data
digest.ps1     Windows launcher
```

Run the tests:

```powershell
.venv\Scripts\python -m pytest
```

Design rules worth keeping:

- **Fetch and render stay separate.** Render is a pure function, so it's tested
  without network or credentials.
- **Few, read-only requests.** One request per data set; news only for players
  with recent news or an injury tag.
- **Times are converted from UTC** with real timezone rules, so US daylight
  saving changes are handled. espn_api's own `game_date` uses the machine's
  local time and isn't used.
- **Credentials never reach output:** not in the digest, error messages,
  `repr`, or `--debug` tracebacks.
