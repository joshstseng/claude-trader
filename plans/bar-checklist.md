# Brix: what we're adding from the user's discretion

Rules taken from the user's own trading ([October journal](bar-journal/2026-10.md), [trades](bar-journal/2026-10-trades.csv)), ordered **easiest to hardest** to build. **Baseline is now run #63 (= #62: rules 1–5, the user's 4h/1h/15m trend read, break-even at the first 15m internal level or a 5m high inside a gap, else 2R, and trailing to pullback lows; +0.103R a trade, +$17.9k; set 2026-11-20).** Before that #57 (= #55), #52 (= #49), #35. Each is tested **one at a time** against the baseline over the full 6 years, then kept or dropped.

October for reference: the user made +11.2R on 14 trades, Brix +1.8R on 6 (+10.9R on 17 with the trend filter off).

## Easy

- [x] **1. Enter at the body midpoint.** *Built (`entry.midpoint="body"`, small = body < 0.5 × 15m ATR). Run #36: −0.004R a trade vs −0.006R, a wash.* The limit order goes at the midpoint of the 8:00 ET 15m candle's **body** (open to close), not the whole candle. If the body is small, use the whole candle, wicks included (10/7).
  - Brix missed fills on 10/9, 10/12 and 10/28, all wins for the user.
  - *To decide:* what counts as "small" (e.g. a body under X points, or under half the candle's range).

- [x] **2. Cancel the order if the target is reached first.** *Built (`entry.cancel_if_target_first`). Run #37: 355 trades, −0.017R a trade, but worst drawdown −$9.3k vs −$17.0k.* If price reaches the target level before the limit fills, the move has happened without us, so cancel.
  - Days: 10/1, 10/13, 10/14, 10/16; 10/23 was the user's "bad trade, should have gotten out".

- [x] **3. The user's target rule.** *Built (`target.mode="levels"`, big stop = > 2 × 15m ATR). Run #38: −0.023R a trade, worse.*
  - Target the nearest internal high or low (or an unfilled 1h FVG) if it's at least 2R away.
  - If the next level is beyond 3R, use a flat 3R.
  - If the stop is large in points, use 2R.
  - Today Brix uses a flat 2R; the user's wins averaged 2.3R.
  - *To decide:* what counts as a "large" stop.

- [x] **4. Longs only near an all-time high.** *Built (`filters.ath_longs_only_pct=0.5`: the latest 1h swing high is the ATH, or within 0.5%). Run #39: 15 shorts skipped, −0.006R, no change.* When the 8:00 candle sits near the all-time high, take no shorts (10/2, 10/6).
  - *To decide:* how near counts (e.g. within 0.5%).

- [x] **5. No trade in accumulation.** *Built (`filters.accumulation_since="03:30"`). Run #40: never triggered, since some 5m gap always forms in the data. Needs a tighter definition.* No trade if no 5m or 15m FVG has formed since 3:30 AM PT (10/21).

## Medium

- [x] **6. A new 1h trend filter, read the way the user reads it.** *First version built (`trend_filter="mtf"`: 4h/1h/15m, gaps decide, BOS/CISD confirm, 2 big candles, 2 of 3 agree). Run #44 alone: −0.034R a trade; #45 with 1–5: +0.003R. October: agrees with the user 9 days, contradicts 1, unclear 11. Without the big-candle rule and stepping back one leg when a leg has no gap events (`trend_big_candles=0`, `trend_legs_back=1`): run #47 alone +0.009R; **run #49 with 1–5: +0.078R a trade, +$13.4k, the best so far**.* The current filter disagreed with the user on 10 of the 12 days it blocked, including 6 of their wins (+15.2R).
  - The user's definition (10/7, bearish): *"the market is dumping. We are disrespecting all bullish gaps and creating 1h bearish gaps. We are cleanly distributing down with almost no retraces."*
  - As a rule, bearish when, over the recent 1h candles:
    - new **bearish 1h FVGs are forming**,
    - **bullish 1h FVGs are being closed through** (disrespected), and
    - retraces are small.
  - Bullish is the mirror image. Mixed signals mean no clear trend, so no trade (or no filter, to test both).
  - *To decide:* how far back "recent" goes (e.g. the last 24 1h candles, or since the previous day's 8:00), and what counts as a small retrace.

- [x] **7. Break-even at the first internal level, instead of at a fixed 1R.** *Built (`exit.breakeven_level` "5m"/"15m": the nearest untaken internal high/low between entry and target, at least 0.5R out; +1R if there's none). Against the new baseline #52: 5m run #53 +0.050R, 15m run #54 +0.074R vs +0.078R. With the fallback at **2R instead of 1R** (user, 2026-11-20): 15m run #55 **+0.092R, +$15.7k, the best so far**; 5m run #56 +0.083R.* Move the stop to break-even once price takes out the first internal low (high for a long) after entry (10/12, 10/20, 10/22, 10/28).
  - The user also moves to break-even when a lower-timeframe gap is disrespected (10/26). That's a later refinement.

- [x] **8. Trail the stop in profit.** *Built (`exit.trail_gaps`): after a pullback into a new 5m gap (1m gaps once past 2R), when price breaks the internal high made before it, the stop goes to the pullback low. Run #60: **+0.102R, +$17.9k, drawdown −$10.1k** (baseline #57: +0.092R). Plus the user's extra break-even trigger (`exit.breakeven_sig5m`: a 5m internal high whose wick sat in a bearish 5m+ FVG): alone #61 +0.093R, both #62 +0.103R.* After a new internal low forms (high for a long), trail the stop to the newest higher-timeframe FVG: 5m, then 3m, then 1m (10/22, 10/26, 10/27).

  - *Later (user, 2026-11-20):* order blocks (10/22) and retrace swing lows (10/27) as trail levels too, not yet.

## Hard

- [ ] **9. The "stronger" stop level.** *First test: the most recent 15m swing first (`stop.swing_tf="15m"` on #49): run #50, +0.052R (vs +0.078R); matches the user on 10/7 (12.2 vs 13.2 pts). Without the 1R break-even (#51): +0.002R, so break-even at 1R helps over 6 years. User's reasons: 10/7 the most recent respected level (the 8:00 candle's own wick area); 10/8 the 3:30 AM wick low = the most recent 1h low (Brix used the same level, 30876 cash, but its distance from entry is 75 pts vs the user's 31; prices to check).* Put the stop behind the level that has already been tested or respected: a 15m high that rejected price, an order block's body, the low an earlier candle bounced from (10/12, 10/13, 10/29).
  - The user's stops ran about 35 points (median) against Brix's 75.
  - *To decide:* a testable definition of "stronger".

## Notes
- **No 9:00 close (run #58):** from 9:00 the stop trails the latest 1m candle's body instead (`window.after_flat="trail_1m_body"`). +0.094R vs +0.092R: the trades still open at 9:00 (about 1 in 10, averaging +0.7R) get stopped out within minutes, so it's nearly the same as closing.
- **The user's liquidity read (10/28):** the gaps said bull, but the bull run was ending and price needed to retrace to the stacked lows below; the user went bear. And 10/15 (a no-trade day): the end of a bear trend, no liquidity, lows or gaps below, accumulating. Not modelled yet.
- **Stops (October check):** Brix's entries line up with the user's (same minute most days), but its stops are about twice as wide (median ~75 pts vs ~35), mostly 1h swings and 15m order blocks further out. Item 9 matters.
- **Later idea (from the user):** when 2 timeframes agree and the third doesn't, we expect it to flip; look for a level that could flip it (a 15m FVG, the 8:00 candle).
- Data caveat: Brix tests on the Nasdaq-100 cash index (HistData), while the user trades MNQ. Prices differ by the basis, and a midpoint fill can differ by a few points.
- October is one month and suited the setup. The 6-year test decides.
