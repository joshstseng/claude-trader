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

### 2.1 Outcome engine *(shared with 1a.7)* ✅
- Plan + bars after entry → `target` / `stop` / `flat` (3:55 PM), exit price and time, R, dollars
- Stop and target inside the same bar → counted as a stop (conservative)
- Costs applied per side
- Used by the backtest **and** by the live bot after the close (1a.7)

**Done when:** tests pass on hand-made bars (target first, stop first, both in one bar, neither, early close) and on TSLA Oct 19.

**As built** ([app/outcomes.py](../app/outcomes.py)):
- A gap below the stop fills at the bar's open (worse than the stop), as a real stop order would; the target fills at the target price
- Also records **MFE / MAE** (best and worst move before the exit, in R). This lets us see what a different target would have done, e.g. "how many 2R losers reached 1R first?"
- Trade log: new outcome columns (gross R, cost, MFE, MAE, bars held), added automatically to existing databases (including Railway's)
- TSLA Oct 19 (Alpaca bars): the v1 signal went **flat** at 3:55 PM, +0.17R after costs. Best +0.52R, never near the stop
- Found while building it: **Alpaca and Yahoo report very different 5-minute volume** (TSLA 10:30 bar: 0.4× vs 7.98× the range average). Prices match. This affects the volume filter, so it gets measured in 2.3

### 2.2 Historical data ✅
- Alpaca 5-minute bars (SIP) for each day's focus list; daily bars for the whole stock list
- Local cache in `data/bars/`, so each day is downloaded once
- Historical focus list for each day (no look-ahead)

**Done when:** 2 years are downloaded and cached, and the focus list for any past day can be rebuilt.

**As built** ([app/backtest/data.py](../app/backtest/data.py), `python -m app backtest-data --from … --to …`):
- **512 market days, 2024-11-01 → 2026-11-17**, downloaded in 21 min; reruns only fetch what's missing. 176 MB in `data/bars/` (git-ignored)
- Calendar from Alpaca, including the 5 early closes in the range (the skill's calendar only covers 2026–2027)
- Daily bars (split-adjusted) for 5,928 of 5,929 stocks; 5-minute bars (raw prices) for each day's 200 focus stocks (199–200 found every day)
- Focus list per day, the same way the live bot builds it: last session's price × volume, plus the skill's own `find_setups` on ~3 months of closes, nothing from the day itself
- **Check: the backtest's focus list for Nov 18 matched the live bot's (built from Yahoo after the close) 200 of 200**
- Safety: requests stop 16 minutes before "now" (the free plan refuses fresher SIP data); a failed download is never cached; a bad symbol is isolated by splitting the batch

**Data findings (Oct 19, 232 stocks, Alpaca vs the repo's saved Yahoo data):**
- Prices are identical (median difference 0.000%, 95% within 0.03%)
- Volume matches bar for bar, except: the **9:30 bar** (Alpaca ~18% lower, since the opening auction is counted differently), and **Yahoo's newest bar while the market is open** (TSLA's 10:30 bar: ~25× too high)
- The volume filter agrees 94% of the time. TSLA's "10:35 trigger at 7.98×" in our replays came from that bad newest bar: with correct volume it was 0.4× and wouldn't have triggered

### 2.3 Signal engine ✅
- The live ORB rules applied to history, in-process (fast), using the same logic as the skill's scripts
- **Consistency check:** the saved Oct 19 Yahoo data → the same 16 signals as the live pipeline replay

**Done when:** the consistency check passes and one full historical day runs in under a second.

**As built** ([app/backtest/signals.py](../app/backtest/signals.py)):
- Calls the **skill's own functions**, so no rule is re-typed: `entry.evaluate` (the trigger), `exit.compute` (stop and target), `size.size_trade` (shares and refusals), then the 2.1 outcome engine
- Mirrors the live scan's filters: the $5 price floor at the check, and skipping a stock with a missing 5-minute bar. Ties within the same bar go alphabetically, like the live bot
- **Consistency check: on the saved Oct 19 data, the same 16 signals as the live pipeline**: same order, times, entries, stops, targets and shares (now a permanent test)
- **All 512 days in 80 seconds**: 20,690 signals, 20,602 tradable (88 refused, mostly a share costing more than the $5k account allows)

**First look (every signal taken, before 2.4's selection rules), not the final answer:**
- Results: 2,772 target · 8,553 stop · 9,277 flat (3:55). **−0.082R a trade after costs**; −0.015R before costs (costs ≈ 0.067R a trade)
- Tight stops do worst: stop under 0.5% of price → about −0.21R a trade; over 1% → −0.06R (supports the minimum stop distance idea)
- Trigger time: no window is clearly positive (−0.07R to −0.13R)
- 37% of trades reached +1R at some point, but only 13% reached +2R (relevant for 1R vs 2R)
- Rough cap-5 first come first served: about −0.03R a trade (2.4 will do this properly, with the daily trade and loss limits)

### 2.4 Selection rules + costs ✅
- Cap N a day, first come first served (baseline)
- Max trades a day and the daily loss limit, from `config/risk.json`
- Room for more rules later (ranking, minimum stop distance)

**Done when:** selection rules apply to saved signals in seconds.

**As built** ([app/backtest/select.py](../app/backtest/select.py)): 2 years in 0.02 s. Each day, in trigger order: the first 5 tradable signals are alerted, you approve all, then the risk check's own daily rules apply: max 3 entries; the max losses at the stops of today's entries + this one ≤ $150 (win or lose); and, optionally, **cash** (open positions + this one ≤ $4,500, with positions freeing their cash when they exit). Every signal gets a reason it was or wasn't taken.

**Results (v1 settings, 2024-11-01 → 2026-11-17):**

| View | Trades | Avg per trade | Total | Worst drawdown |
|---|---|---|---|---|
| Every signal | 20,602 | −0.082R | −$50,853 | −$51,937 |
| Cap 5 FCFS + risk rules, cash limit off | 1,536 (3 a day, every day) | −0.043R | −$2,304 | −$3,147 |
| Cap 5 FCFS + risk rules, cash limit on | 683 (~1.3 a day) | −0.038R | −$650 | −$1,664 |

The $150 daily loss rule never binds (3 trades × at most $50 = $150). **Open decision: is the cash limit on or off in the baseline?** A real $5k account without margin can usually hold only one ~$3,500 position at a time; Alpaca's paper account has $100k+ and would allow all 3.

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
