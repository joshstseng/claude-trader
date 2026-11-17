# Step 2: ORB bot backtest framework

Part of [ROADMAP.md](../ROADMAP.md). Status: 🟨 In progress (started 2026-11-17, alongside the Step 1a live gate)

**Goal:** replay the exact ORB bot rules over ~2 years of history, assuming you approve every alert. Save each run so any two runs can be compared, and post a short summary of each run to `#backtests`.

**Gate (from the roadmap):** expected profit per trade is positive after costs, and the backtest roughly matches live results. If not, tune and backtest again, as many runs as needed.

> **Order note:** the roadmap put the backtest after Step 1b, so that real paper fills could set the cost per trade. We're building it now, while Railway collects the 1a live days, with an **assumed** cost. When 1b produces real fills, we swap in the measured cost and re-run.

---

## Decisions (2026-11-17)

| Decision | Choice |
|---|---|
| Date range | **Nov 2024 → Nov 2026** (~500 market days) |
| Data | Alpaca historical bars, full consolidated feed (SIP): 5-minute bars for the focus list, daily bars for the stock list. Free account confirmed: back to at least Jan 2024, ~0.5 s per 50 stocks per day |
| Baseline settings | Today's live v1: focus 150 most traded + 50 daily-scan hits, scan 9:50–11:30, trigger bar volume ≥ 1.0×, stop at range midpoint, target 2R, flat at 3:55, $5k account / $50 max loss |
| Which alerts get taken | **First come, first served (FCFS), cap 5 a day.** Ranking comes later as a variation |
| Assumed cost | **0.03% of the price per side** (spread + slippage); Alpaca charges no commission. Replaced by measured paper fills after Step 1b |
| Views in every report | **(a) Every signal taken** (does the setup work at all?) and **(b) as the bot alerts** (cap 5, FCFS: what you'd actually get) |
| Where it runs | Your Mac (one-off calculations). Bars cached in `data/bars/` (git-ignored). Not on Railway |

---

## How it works

```
for each market day D:
  focus list   ← top 150 by $ traded on D-1 (over $5) + daily-scan hits on closes up to D-1
  5-min bars   ← Alpaca (cached after the first download)
  signals      ← the live ORB rules: range 9:30–9:45, first 5-min CLOSE above the high
                 with volume ≥ 1.0×, inside 9:50–11:30
  plan + size  ← the live stop / target / share math
  outcome      ← walk the bars after entry: stop or target first? (both in one bar = stop)
                 otherwise exit at the 3:55 PM price; minus the assumed cost
then: selection rules (cap 5 FCFS, trades/day, daily loss stop) → results → report
      → trade log (source = backtest, strategy = orb) → summary to #backtests
```

**Principles**
- **No look-ahead.** Each day only sees what was known at that moment: the focus list uses the previous day's data, and entries use completed bars only.
- **Same rules as live, proven by a test.** On the saved Oct 19 data, the backtest must produce the same 16 signals (entries, stops, targets, share counts) as the live pipeline. If they ever differ, the backtest is wrong.
- **Generate every signal once, pick trades afterwards.** Every signal is stored with its plan and outcome. Selection rules are applied afterwards, so testing a new one takes seconds. Changing an exit rule (1R vs 2R, a different stop) re-runs outcomes from cached bars, with no new download.
- **Every run is saved** with its settings, git commit and date range, and is labeled `orb`.

---

## Sub-steps

### 2.1 Outcome engine *(shared with 1a.7)*
- Plan + bars after entry → `target` / `stop` / `flat` (3:55 PM), exit price and time, R, dollars
- Stop and target inside the same bar → counted as a stop (conservative)
- Costs applied per side
- Used by the backtest **and** by the live bot after the close (1a.7)

**Done when:** tests pass on hand-made bars (target first, stop first, both in one bar, neither, early close) and on TSLA Oct 19.

### 2.2 Historical data
- Alpaca 5-minute bars (SIP) for each day's focus list; daily bars for the whole stock list
- Local cache in `data/bars/`, so each day is downloaded once
- Historical focus list for each day (no look-ahead)

**Done when:** 2 years are downloaded and cached, and the focus list for any past day can be rebuilt.

### 2.3 Signal engine
- The live ORB rules applied to history, in-process (fast), using the same logic as the skill's scripts
- **Consistency check:** the saved Oct 19 Yahoo data → the same 16 signals as the live pipeline replay

**Done when:** the consistency check passes and one full historical day runs in under a second.

### 2.4 Selection rules + costs
- Cap N a day, first come first served (baseline)
- Max trades a day and the daily loss limit, from `config/risk.json`
- Room for more rules later (ranking, minimum stop distance)

**Done when:** selection rules apply to saved signals in seconds.

### 2.5 Runs + reports
- `python -m app backtest --from 2024-11-01 --to 2026-11-16 [--set exit.target=1R] [--label "…"]`
- Saved to the trade log (`source = backtest`) with settings and git commit
- Report: trades, win rate, average R, **expectancy** (average result per trade, in R and $, after costs), profit factor, max drawdown, by month, by entry time; both views (a) and (b); comparison with the baseline
- The blind spots are listed in every report

**Done when:** baseline run #1 has a report.

### 2.6 `#backtests` channel
- One short summary per run, compared with the baseline
- Uses `DISCORD_CHANNEL_BACKTESTS` (only needed on the Mac, where backtests run)

**Done when:** a run summary shows up on your phone.

---

## Variations queue (after the baseline)

1. **Targets:** 1R, 1.5R, 2R, 3R
2. **Stops:** range midpoint, range low, ATR multiple
3. **Scan window:** 9:50–11:30 vs later breakouts (up to 3:30 PM)
4. **Volume check:** off vs 1.0× vs 1.5×
5. **Later:** ranking instead of FCFS (by volume ×, % over the range, $ traded), and a **minimum stop distance** (e.g. HMC's $0.05 stop on Oct 19, 110 shares)
6. Focus list size

## Known blind spots
- **Delisted stocks are missing:** the stock list is today's, so companies delisted in the last 2 years are left out. Results look slightly better than reality.
- **Data source:** the backtest uses Alpaca bars and live alerts use Yahoo. The Oct 19 check measures the difference.
- **Fill costs are assumed** until Step 1b gives real ones.
- **5-minute bars only:** the order of the high and low inside a bar is unknown, hence "both in one bar = stop".
