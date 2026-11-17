# Step 1a: ORB bot alerts + trade log

Part of [ROADMAP.md](../ROADMAP.md). Status: 🟨 In progress (1a.1 ✅ 1a.2 ✅ 1a.3 ✅)

**Goal:** the **ORB bot** runs every market day without help, sends setups with a full plan to Discord and logs every signal with what it would have done. **No orders are placed in this step.**

**Gate to finish:** 5 market days in a row with no manual help.

---

## What the ORB bot trades

- **US-listed stocks only** (common shares and ADRs), whole shares, **long only**, closed the same day.
- No options, futures, shorting, margin or crypto (the repo's risk settings turn these off by default).
- Strategy: **Opening Range Breakout** from [day-trader-skill](../day-trader-skill/):
  - **Opening range:** high and low of 9:30–9:45 AM ET (three 5-minute bars)
  - **Entry:** first *completed* 5-minute bar that *closes* above the range high
  - **Stop:** opening-range midpoint
  - **Target:** 2R (2 times the risk)
  - **Flat by:** 3:55 PM, win or lose

## Settings for v1 (decided 2026-11-17)

| Setting | v1 value | Notes |
|---|---|---|
| Strategy id | `orb` | Every log row, alert and run is tagged with it |
| Focus list | ~150 most-traded stocks over $5, plus anything the daily scan flagged | Built pre-market; checking takes ~35 s |
| Scan window | 9:50–11:30 AM ET | Later-day breakouts get tested in the backtest |
| Trigger bar volume | ≥ 1.0× the opening range's average bar volume | |
| Risk check | Must PASS for an alert to be sent | Every signal is still logged |
| Max alerts per day | 5, first come first served | |
| Stop / target | Range midpoint / 2R | 1R, 1.5R, 2R, 3R and other stops get compared in the backtest |
| Account (simulated) | $5,000 | Repo defaults |
| Max loss per trade | $50 | |
| Daily loss limit | $150 | |
| Max trades per day | 3 | |
| Discord channels | Shared (`#setups`, `#trades`, `#daily-summary`, `#system`), each message tagged `[ORB]` | Split per bot later if it gets noisy |

All of these live in settings files, not in code, so the backtest can vary them.

---

## How it fits together

```
 8:30 AM  pre-market   scan.py daily + top-150 most traded  ──►  focus list (~150 + hits)
                                                                        │
 9:50–11:30 every 5 min    entry.py check on the focus list ◄───────────┘
                                   │ trigger
                                   ▼
          per-signal folder runs/<date>/orb/<TICKER>/
          exit.py → timemachine.py → size.py → check.py → news.py
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
             trade log (SQLite)          passes filters? ──► Discord #setups
             every signal                                     [Took it] [Skip]
                                   │
 4:15 PM  after the close   work out each signal's result ──► #daily-summary
```

**Why one folder per signal:** the skill scripts keep one trade at a time in fixed files (`trader/entry.json`, `trader/plan.json`). Running each signal in its own folder stops several signals at once from overwriting each other, and keeps a full record of every signal.

---

## Sub-steps

### 1a.1 Project skeleton ✅
- `app/` Python package; dependencies (`discord.py`, `alpaca-py`, `python-dotenv`)
- `.env.example` (Alpaca paper keys, Discord token, channel IDs, your Discord user ID)
- Settings files: `config/risk.json` (shared rules) and `config/strategies/orb.json` (ORB bot settings)
- A strategy list with `orb` in it, so other bots can be added later
- `day-trader-skill/` is used as-is and never edited

**Done when:** the structure is in place and the repo's own tests still pass (`python3 -m unittest discover -s day-trader-skill/tests`).

### 1a.2 Accounts *(you, with a walkthrough)* ✅
- **Alpaca:** sign up, switch to Paper, generate API keys, put them in `.env`
- **Discord:** create a private server; create `#setups`, `#trades`, `#daily-summary` and `#system`; create the bot in the Developer Portal; invite it with permission to post and use buttons; set phone notifications to "All messages" on `#setups` and `#trades`; copy your user ID
- A check command: `python -m app.check`

**Done when:** the check command prints Alpaca's market clock and posts "hello" in `#system`.

### 1a.3 Pipeline wrapper ✅
- One function takes a signal through entry → exit → Time Machine → budget → risk → news, in its own folder
- Reads each script's JSON output; a step that fails gets logged with the reason and doesn't crash the app
- **Replay mode:** runs on the repo's saved data with a fixed clock (`--offline`, `--now`)

**Done when:** replaying TSLA on 2026-10-19 produces the known plan: entry 364.18 at 10:15, stop 358.32, 8 shares.

### 1a.4 Trade log (SQLite)
- Tables: days, signals, plans, alerts, responses (your button taps), outcomes
- Every row tagged with `strategy` (`orb`), `source` (`live` / `replay` / `backtest`) and a settings snapshot (which settings were in effect)
- Designed so the Step 2 backtest writes into the same tables

**Done when:** replay signals are saved and can be looked up.

### 1a.5 Scheduler + daily routine
- Market calendar from Alpaca (holidays, 1:00 PM early closes)
- Pre-market: refresh the stock list weekly, run the daily scan, build the focus list
- Scan window: check the focus list every 5 minutes, ~1 minute after each bar closes
- Apply the alert filters; log every signal either way
- A simulated clock, so a full past day can be replayed

**Done when:** a full past day replays end to end on the simulated clock.

### 1a.6 Discord bot (built into the app)
- **Alert in `#setups`:**
  - `[ORB]` tag, ticker, opening range, trigger time and price
  - Stop, target, reward-to-risk, shares and max loss in dollars
  - Time Machine odds and verdict, risk check result
  - Top 1–2 headlines and any 8-K filing in the last 24h (for you to read only)
- **Buttons [Took it] [Skip]:** these only record your choice, and only your Discord user can press them
- **Commands:** `/status`, `/today`, `/pause`, `/resume`
- **`#system`:** startup, health ping, errors

**Done when:** replay alerts show up on your phone and button taps are saved.

### 1a.7 After the close
- For **every** signal (alerted or not), work out what it would have done from the 5-minute bars:
  - Target first, stop first, or neither by 3:55 PM
  - If the stop and target both fall inside the same bar, count it as a stop (conservative)
  - Result in R (multiples of the risk) and in dollars
- Post the daily summary to `#daily-summary`: signals, alerts, your taps, results

**Done when:** each replay day ends with a summary.

### 1a.8 Running it unattended
- Starts automatically on your Mac (launchd); keeps the Mac awake during market hours (`caffeinate`); restarts after a crash
- Log files, with old ones deleted automatically; a missed health ping shows in `#system`
- A dry run on a replay day, then live market days

**Done when (Step 1a gate):** 5 market days in a row with no manual help.

---

## Not in Step 1a
- Placing orders → Step 1b
- Market data from Alpaca → Step 1b (Yahoo is fine for alerts; alerts arrive ~1–2 min after the trigger bar closes)
- Claude filter → Step 3
- Other strategy bots → later

## Known limits
- Yahoo data is free, unofficial and can lag or rate-limit us.
- The daily scan's setups (bull flag, oversold…) only feed the focus list. The ORB bot doesn't trade them.
- The focus list leaves out less-traded stocks on purpose (speed and reliable fills).
