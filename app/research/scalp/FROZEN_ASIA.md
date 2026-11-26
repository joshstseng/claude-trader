# Asia session research: rules frozen before any test (2026-11-24 ~2:08 PM PT)

User request: Asia session, forex pairs and gold, trade only with the trend, VWAP or EMA entries; Claude may add
strategies it believes in. Data: HistData free 1-minute bid bars (fixed EST = UTC-5, no volume) for USD/JPY,
AUD/USD, EUR/USD and XAU/USD (spot gold, the stand-in for MGC), 2016 to October 2026.

## Session and windows
- **Asia session:** 19:00 to 03:00 EST (09:00-17:00 Tokyo, 00:00-08:00 UTC). It belongs to the next calendar date.
- **Dev 2016-2019** (all choices), **validation 2020-2022** (one look per candidate), **final 2023-Oct 2026** (one look).
- Sessions need at least 400 of 480 minutes; missing minutes are filled from the last close.

## Costs (per side, half spread + commission, on bid data) and execution
USD/JPY 0.5 bp, EUR/USD 0.5 bp, AUD/USD 0.8 bp, XAU/USD 0.8 bp; stop exits +0.3 bp. Stress test: double.
Signals on completed bars, entry at the next 1-minute open, stop beats target inside a bar, flat at 03:00 EST.

## Family T: trend pullback (the user's idea), every instrument
1. **Trend, decided at 19:00 before the session:** `d20` = the 19:00 price vs the average of the last 20 sessions'
   19:00 prices; or `h1` = the 1-hour EMA50 (continuous) is higher (lower) than 5 hours ago and price is above (below) it.
   Only trades in the trend's direction.
2. **Entry, on 5-minute bars:**
   `ema` = EMA9 > EMA20, close > EMA20, EMA20 rising, low of the last 3 bars touched EMA9, close above the previous
   bar's high and EMA9 (shorts mirror).
   `twap` = close above the session's time-weighted average price (from 19:00), the high of the last 6 bars was at
   least 0.10% above it, the low of the last 3 bars came within 0.02% of it, close above the previous bar's high.
3. Signals 19:30-02:00 EST, at most 3 a session, one position at a time.
4. Stop: lowest low of the last 5 five-minute bars (mirror for shorts). Skip if risk < `min_risk` or > 0.60%.
5. Exit: 2R, 3R or `rule` (a 5-minute close back through EMA20 or the TWAP), or 03:00.
Grid per instrument: trend {d20, h1} x entry {ema, twap} x min_risk {0.05%, 0.10%} x exit {2R, 3R, rule} = 24;
96 variants in all.

## Family F: Tokyo fix (Krohn, Mueller and Whelan 2021; Bessho et al. 2023)
The dollar tends to rise against other currencies before the 9:55 Tokyo fix (19:55 EST), then revert.
- `pre`: buy USD at the 19:00 open, sell at the 19:54 close. `post`: sell USD at the 19:56 open, buy back at the 21:00 close.
- Pairs: USD/JPY (buy), AUD/USD and EUR/USD (sell the pair to be long USD). Days: `all` or `gotobi` (Japanese calendar
  days 5, 10, 15, 20, 25, 30; if not a trading day, the previous trading day; the last day of the month if no 30th).
- 2 x 3 x 2 = 12 variants. No stop; fixed size.

## Family G: gold drifts up in Asian hours (CBS study, weaker evidence)
- Buy XAU/USD at the 19:00 open and sell at the 03:00 close every session. Variants: `all`, or only when the `d20` trend is up.
- 2 variants. No stop; fixed size.

## Measuring
- T: R per trade after costs; daily results at 0.25% risk a trade.
- F and G: return per session after costs at 1x notional, scaled to 10% annual volatility for comparison.

## Choosing and the bar
- Per family, the best dev Sharpe with at least 200 dev trades (F gotobi: 100), and its neighbors (one setting changed)
  must have a positive median. At most one candidate per family to validation; any that pass go to the final test once.
- **Bar (validation and final, each):** positive after costs, profit factor >= 1.10, Sharpe >= 0.8, still positive at
  double costs, positive in 2 of 3 validation years and 3 of 4 final years, at least 150 trades (F gotobi: 80).
- 110 variants are tested on dev, so a lucky pass is possible; the untouched validation and final windows are the guard.

## Data fix (2026-11-24 ~2:20 PM PT), before any validation look
The first dev run assumed HistData stamps were fixed EST. They are New York local time with daylight saving
(Sunday opens at 17:00 and gold's daily break ends at 18:00 in both summer and winter), so summer sessions were an
hour off Tokyo time. Timestamps are now converted through UTC to fixed EST, so 19:00 EST = 09:00 Tokyo all year.
The rules and grid are unchanged; the dev grid is rerun. First (wrong-clock) run: 0 of 110 passed.

## Dev result with the correct clock (~2:20 PM PT) and the candidate
- T (trend pullbacks): 2 of 96 positive after costs, best Sharpe 0.27. **No candidate.**
- G (gold Asia drift): negative. **No candidate.**
- F: **USD/JPY `pre` on gotobi days** (buy 19:00 EST = 09:00 Tokyo open, sell 19:54 close): 288 trades, +1.45 bp
  after costs, PF 1.34, Sharpe 0.86, 3 of 4 years positive. Matches Bessho et al. (2023).
  **Flag:** under the neighbor rule as written, its neighbors are pre-all USD/JPY (-0.47 bp), post-gotobi USD/JPY
  (+0.82 bp), pre-gotobi AUD/USD (-0.75 bp) and EUR/USD (-1.46 bp): median negative, so it does NOT strictly meet the
  rule. Claude's argument for continuing: gotobi flows are Japanese importers buying USD with yen, so the effect should
  be yen-specific. It goes to validation labeled as an exception; the bar itself is unchanged.

Validation result (~2:20 PM PT): gotobi pre-fix USD/JPY 2020-2022: 216 trades, -1.07 bp, PF 0.78, Sharpe -0.71,
every year negative. **FAILED.** Final window not looked at. Posted as runs #86 and #87.

---

# Round B (frozen ~2:22 PM PT): trend-following inside the Asia session
Round A's pullback entries had about zero edge even before costs. What worked on the Nasdaq was trend-following
on big moves (Swing). Test that, plus first-hour momentum, on the same four instruments, dev 2016-2019 only.

## B2: Asia noise-band breakout (Swing's idea, adapted)
- 5-minute bars on the session grid. For each 5-minute bar k: sigma_k = average |close_k / session open - 1| over
  the prior 14 sessions. Band = session open x (1 +/- m x sigma_k).
- Checks every `chk` minutes from 19:30 to 02:30 EST on completed 5-minute bars: long above the band, short below,
  flat inside; flip on the opposite side. Fill at the next 1-minute open. Flat at 03:00.
- `exit`: `band` = leave when a check is back inside; `twap` = also leave when a 5-minute close crosses the session
  TWAP against the position (no re-entry until the next check).
- `filter`: `none`, or `d20` = only trade in the daily trend's direction.
- Grid per instrument: m {1.0, 1.5} x chk {30, 60} x exit {band, twap} x filter {none, d20} = 16; 64 in all.

## B1: first-hour momentum
- r1 = 19:00-19:59 return; s1 = average |r1| over the prior 14 sessions. If |r1| >= k x s1, enter in r1's direction
  at the 20:00 open and hold to the 03:00 close; `stop` variant also exits if price returns to the 19:00 open.
- Grid per instrument: k {0.5, 1.0} x exit {close, stop} x filter {none, d20} = 8; 32 in all.

## Measured and judged
Per-session return at 1x notional after the same per-instrument costs (each entry and exit pays). Sharpe from daily
session returns. Candidate: best dev Sharpe per family with >= 150 dev trades and a positive neighbor median (same
instrument, one setting changed). Same bar as round A.

Round B result (dev, ~2:21 PM PT): B2 3 of 64 positive, B1 3 of 32, best Sharpe 0.29. **No candidate.** Trend-following
inside Asia was consistently negative (mean Sharpe EUR -2.7, AUD -2.4, JPY -1.1), a sign Asian moves revert.

---

# Round C (frozen ~2:23 PM PT): fade stretched Asian moves, optionally only against the daily trend
Not a sign-flip of round B: a separate mean-reversion rule with its own stop and target, judged on its own.
- Same 14-session band as B2 (session open x (1 +/- m x sigma_k)). On each completed 5-minute bar from 19:30 to
  02:00 EST: a close above the upper band -> short at the next 1-minute open; below the lower band -> long.
- Target: `twap` = a 5-minute close back through the session TWAP exits at the next open; `open` = a limit at the
  session's 19:00 open price.
- Stop: entry pushed further by `s` x (distance from the session open to the entry), as a stop order.
- `filter`: `none`, or `trend` = only fade moves AGAINST the daily d20 trend (buy dips in uptrends, sell rallies in
  downtrends; the user's "with the trend").
- At most 2 trades a session, one at a time, flat 03:00. Per-instrument costs as before (+0.3 bp on stops).
- Grid per instrument: m {1.0, 1.5, 2.0} x target {twap, open} x s {0.5, 1.0} x filter {none, trend} = 24; 96 in all.
- Same candidate rule and bar. Measured per session at 1x notional.

Round C result (dev, ~2:22 PM PT): 0 of 96 positive after costs. Before costs the fade works (Sharpe up to 2.0 on
EUR/USD, 1.5 on AUD/USD), but it earns only +0.8 to +1.2 bp a trade, so it breaks even at about 0.4-0.6 bp per
side, which is roughly what retail costs are. **No candidate. Research stopped: no Asia edge after costs.**
