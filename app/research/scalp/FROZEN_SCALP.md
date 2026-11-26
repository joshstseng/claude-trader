# Scalp research: rules frozen before any test (2026-11-24, ~1:22 PM PT)

Goal: find a VWAP or EMA pullback scalp with a genuine edge after realistic MNQ costs.

## Data and windows
- QQQ 1-minute SIP bars, split/dividend adjusted, regular session only, 2016-01-04 to 2026-10-30 (Alpaca).
- Full sessions only (>= 370 bars and a 3:59 PM bar). Shortened days are skipped, like the live bots.
- **Dev 2016-2019** (choose everything here), **validation 2020-2022** (one look per finalist), **final 2023-Oct 2026**
  (one look, for the single chosen candidate only). No re-tuning after a window has been seen.

## Execution model (both families)
- Signals use completed bars only. Entry at the **next 1-minute bar's open**.
- Stop: a stop order. If a bar's low (long) reaches it, exit at the stop, or at the open if the bar opened past it.
- Target: a limit. If stop and target are both inside one bar, **the stop wins** (conservative).
- Rule exits (close back through VWAP or the 20 EMA) exit at the next 1-minute open.
- Entries allowed from 9:45 AM ET; window variants below. Everything is flat at the 3:55 PM bar's close.
- One position at a time, at most 3 entries a day.
- Skip a trade when the risk (entry to stop) is under 0.06% or over 0.60% of price. The minimum keeps costs
  from eating most of each trade (lesson from Orbi's tiny stops).
- **Costs:** 0.6 bp of price per side on every fill, plus 0.3 bp extra on stop exits. That is about twice MNQ's
  1 tick + $0.75 per contract per side. Stress test: double it (1.2 bp per side + 0.6 bp on stops).

## Family A: VWAP pullback (long; shorts mirror)
At a completed bar i:
1. Above VWAP: close > session VWAP, and VWAP is higher than 30 minutes ago.
2. Extended first: the highest high of the last 30 bars was at least `ext` above VWAP.
3. Pulled back: the lowest low of the last 3 bars came within `tol` of VWAP (or below it).
4. Resumed: this bar closes above the previous bar's high.
Stop: the lowest low of the last 5 bars minus $0.01.

## Family B: EMA pullback, on 1m or 5m bars (long; shorts mirror)
EMAs 9 and 20, continuous across days. At a completed bar j:
1. Trend: EMA9 > EMA20, close > EMA20, EMA20 higher than 5 bars ago.
2. Pulled back: the lowest low of the last 3 bars touched EMA9.
3. Resumed: this bar closes above the previous bar's high and above EMA9.
Stop: `swing` = lowest low of the last 5 bars minus $0.01, or `ema20` = EMA20 minus $0.01.

## Dev grid (2016-2019 only)
- A: ext in {0.15%, 0.30%} x tol in {0, 0.03%}
- B: timeframe in {1m, 5m} x stop in {swing, ema20}
- Both: exit in {1R, 1.5R, 2R, 3R, rule (VWAP / EMA20 close-through)} x sides in {both, long only}
  x window in {all day 9:45-3:30, morning 9:45-11:30}
- 160 variants. Report all of them.

## Choosing the candidate (dev only)
Highest dev daily Sharpe among variants with >= 400 dev trades, **and** its neighbors (same family, one setting
changed) must have a positive median expectancy. Ties go to the simpler rule. One candidate per family may go to
validation; the better of the two in validation may go to the final test.

## The bar a candidate must clear (validation and final, each)
- Average result per trade > 0 after base costs, profit factor >= 1.10.
- Daily Sharpe >= 0.8 at 0.25% risk per trade.
- Still profitable at double costs.
- Profitable in at least 2 of 3 validation years and 3 of 4 final years.
- At least 300 trades in the window.
If nothing clears it, the answer is "no genuine edge found," and that is reported as such.

---

# Round 2 (frozen 2026-11-24 ~1:28 PM PT, after round 1 failed on dev: 0 of 160 variants passed, run #80)

Idea: pullbacks are only worth taking on days the Nasdaq is actually trending. Swing v1's noise-band breakout is
the trend filter we already measured. Take a pullback long only while Swing v1 is long, a short only while it is short.

- Swing v1 state rebuilt from the same 1-minute data (5-minute bars, 14-session band, 30-minute checks, from
  app/strategies/swing.py with the FVG exit off). A pullback signal at minute t counts only if Swing v1's side,
  as of the last completed 5-minute bar, matches.
- Everything else as in round 1 (execution, costs, risk limits, 3 a day, flat 3:55).
- Grid: VWAP ext {0.15%, 0.30%} x tol {0, 0.03%}; EMA tf {1m, 5m} x stop {swing, ema20};
  exit {1R, 1.5R, 2R, 3R, rule}; both sides; all-day window. 40 variants, dev 2016-2019 only.
- Same candidate rule and the same bar as round 1. Baseline to beat in the report: Swing v1 itself on the same days.

---

# Round 3 (frozen 2026-11-24 ~1:32 PM PT, after round 2 on dev: best 5m EMA pullback in Swing's direction,
# +0.055R a trade, Sharpe 0.48, PF 1.09; 0 of 40 passed)

Diagnosis: before costs the edge is +0.10 to +0.16R a trade, and costs take ~0.1R because stops are small.
1-minute versions are worse than 5-minute ones every time. Fix the cause, not the score: larger stops, so each trade
pays less cost per unit of risk. VWAP is dropped (fewest trades, negative in rounds 1 and 2).

- EMA 9/20 pullback, Swing v1 direction filter (round 2), both sides, all day, 3 a day, flat 3:55.
- Grid: timeframe {5m, 15m} x stop {swing, ema20} x minimum risk {0.06%, 0.10%, 0.15%} x exit {2R, 3R, rule}.
  36 variants, dev 2016-2019 only. Costs unchanged (0.6 bp per side + 0.3 bp on stops).
- Same candidate rule and bar. Also reported for information only (not used to choose): results at actual MNQ
  costs, about 0.3 bp per side + 0.15 bp on stops.

---

# Candidate chosen on dev (2026-11-24 ~1:35 PM PT), before looking at validation
**Scalp candidate "EP5":** EMA 9/20 pullback on 5-minute bars, only in Swing v1's direction, both sides, swing-low stop
(lowest low of the last 5 five-minute bars, minus $0.01), skip if risk < 0.15% or > 0.60%, target 3R, flat 3:55, 3 a day.
Dev 2016-2019: 573 trades, +0.115R a trade after costs, PF 1.21, Sharpe 0.91. Neighbors: rule exit 0.80, 2R 0.78,
0.10% minimum 0.57. Validation 2020-2022 is looked at once, now.

Validation 2020-2022 (one look, ~1:37 PM PT): 528 trades, +0.101R, PF 1.17, Sharpe 0.94, all 3 years positive, +0.057R at double costs. PASSED. Final test next, once, unchanged.

Final 2023-Oct 2026 (one look, ~1:34 PM PT): 607 trades, +0.086R, PF 1.15, Sharpe 0.81, all 4 years positive,
+0.036R at double costs. PASSED the bar. Information only, afterwards: daily correlation with Swing v1 0.6-0.7, it
makes 3.4%/yr vs Swing's 9.3% (final), Swing + EP5 Sharpe 1.27 vs Swing alone 1.36 in the final window, top 10 days
= 86% of final R, median hold 85 minutes. Posted as runs #81 and #82.

---

# Round 4 (frozen ~1:38 PM PT): VWAP fade on quiet days, a separate family
Idea: EP5 only re-expresses Swing's trend edge. A useful scalp would earn on the days Swing sits out. When the
Nasdaq stays inside its noise band, stretched moves away from VWAP may snap back.
At a completed bar (1m or 5m), long (shorts mirror):
1. Swing v1 is flat (side 0) at that moment.
2. Stretched: close is at least `z` below session VWAP.
3. Turning: the bar closes above the previous bar's high.
4. Entry window 10:00 AM-3:00 PM ET. Stop: lowest low of the last 5 bars minus $0.01, risk between `min_risk` and 0.60%.
Exits: 1R, 2R, or `vwap` (a close at or above VWAP exits at the next 1-minute open). Flat 3:55, 3 a day.
Grid: tf {1m, 5m} x z {0.20%, 0.35%} x min_risk {0.10%, 0.15%} x exit {1R, 2R, vwap}: 24 variants, dev 2016-2019 only.
Same costs, candidate rule and bar. Extra requirement: daily correlation with Swing v1 below 0.3 on dev.

Round 4 result (dev, ~1:36 PM PT): 0 of 24 positive after costs; uncorrelated with Swing but no edge. Dropped.

# Control test (information only, ~1:36 PM PT)
Entering at ANY 5-minute close while Swing v1 is long/short (same stop, 0.15% minimum, 3R, 3 a day) does as well
as EP5: dev +0.101R vs +0.115R, validation +0.162R vs +0.101R, final +0.079R vs +0.086R. EP5 beats 62% of 200
random Swing-direction entry sets in the final window. **The pullback adds nothing; EP5's profit is Swing's edge.**

# SPY check (frozen ~1:37 PM PT, before downloading SPY data)
Run the round 1 grid exactly (160 variants, no Swing filter) on SPY 1-minute bars, dev 2016-2019 only, to see whether
the round 1 failure is QQQ-specific. If any SPY variant clears the dev bar it becomes a new candidate for validation.

SPY result (dev, ~1:42 PM PT): 0 of 160 clear the bar (VWAP 20 positive, best Sharpe 0.45 on 79 trades; EMA see run). No new candidate.
