# Mr. S: NQ mean reversion (bot #2 candidate)

Your strategy (2026-11-20), "Mr. S" in Discord, strategy id `mrs`. **Micro Nasdaq futures (MNQ)**, the **Asia session** first, then NY AM. Part of [step-2b-bot-fleet.md → 2b.6](step-2b-bot-fleet.md#2b6-bot-2-when-a-second-strategy-earns-it). Hours and the head bot's side: [head-session-hours.md](head-session-hours.md).

## Where it stands
| Part | Status |
|---|---|
| Rules, indicators, the session walk (`app/strategies/mrs.py`, `config/strategies/mrs.json`, `tests/test_mrs.py`) | ✅ built 2026-11-20 |
| Backtest scenarios (one combination at a time, each a saved, repeatable run) | ⬜ next |
| 1m data (years of it) for the real backtest and the 1m entry | ⬜ Databento free credits, or a Kaggle dataset |
| Live bot: Tradovate demo, Discord cards, its own Railway service | ⬜ later, only if the backtest earns it ([mrs-discord.md](mrs-discord.md): M1 join the server → M2 shadow mode → M3 demo) |
| NY AM session | ⬜ after Asia |
| Range-fade version (ADX < 20, both sides) | ⬜ eventually |

Not registered as a live bot yet (`enabled: false`, not in `BRAINS`): the shared bot contract is built around stock days (NYSE hours, watchlists), so wiring it in is part of the live step.

## The rules (version A, "trend pullback")
| | |
|---|---|
| Market | NQ data (`NQ=F`), traded as MNQ: same price, **$2 a point**, tick 0.25 = $0.50 |
| Session | **4:00–10:00 PM PT** (7 PM–1 AM ET); last entry by 9:45 PM PT; everything flat at 10:00 PM |
| Trend (15m) | RSI(14) **> 55 → longs only**, **< 45 → shorts only**; ADX(14) **> 20** (trending). From the last *finished* 15m bar, never one still forming |
| Setup (5m) | A bar **closes outside** the Bollinger Band (20, 2): below the lower band → long, above the upper → short |
| Entry (5m) | Within the next **2 bars** (10 min), the first bar with **any part of its body back inside** the band; enter at its close. Otherwise the setup is dropped |
| Stop | The **extreme** of the setup bar and the entry bar (lowest low for a long, highest high for a short), plus **2 ticks** |
| Target | The **middle band** (it moves every bar) or **2R**, whichever comes first. A bar that touches the stop and a target: the stop counts (conservative). Price gaps through a level: filled at the bar's open |
| Size | **1% of the account** at the stop (with costs), whole contracts, at most 20. Backtest account: **$50,000** → $500 a trade |
| Limits | One trade at a time. The session stops after **2R** of losses (two stop-outs) |
| Skipped | Stop under **5 points** (too tight to survive slippage), middle band under **1R** away (not worth it), stop too wide for even 1 contract at 1% |
| Costs | $0.75 per contract per side, 1 tick of slippage on market fills (entry, stop, session end). Assumed; check against Tradovate |

All of it is in `config/strategies/mrs.json`, so a backtest run can change one setting at a time.

**Later (needs 1m data):** enter on the 1m chart instead. After the 5m setup, the first bullish 1m candle with any part back toward the middle (bearish for a short).

## Notes and decisions
- **The session hours:** 4:00 PM PT is the Tokyo open in winter (in summer Tokyo opens at 5:00 PM PT, since Japan has no daylight saving). **10:00 PM PT is not the London open:** London opens at 8:00 AM London time, which is about **midnight PT** (Frankfurt about 11:00 PM PT). So 10:00 PM PT ends the session about 2 hours before London. Change `session.end` if you want to run up to the London open
- Sessions run Sunday through Thursday nights (CME is closed Friday night and Saturday). Each session needs about 8 hours of earlier bars to warm up the 15m ADX, so after a weekend it reads Friday's bars
- Contract rolls (March, June, September, December): trade the most active contract; the backtest uses Yahoo's front-month series (small jumps at each roll)
- Pings like the ORB bot: `#live-trades` card, `#closed-trades` card with an @mention (removed after the daily summary), each setup logged even when it's taken automatically. **It places its own orders on the demo account** (you're asleep in the Asia session): no Approve button, ahead of the roadmap's Step 4, on demo money only

## First look on real data (not a backtest)
A smoke run on Yahoo's last 60 days of 5m `NQ=F` (2026-09-13 to 2026-11-20, about 48 Asia sessions): **16 trades**, 10 stops, 5 at 2R, 1 at the middle band; average stop 22 points, about 14 contracts. Most setups were filtered out by ADX (164) and RSI (148). **16 trades says nothing about the edge**; it only shows the code runs on real data. The backtest needs years of data.

## Next: backtest scenarios
1. Baseline: version A exactly as above, on as much 5m history as we can get, saved as a repeatable run
2. Then one change at a time (e.g. session end at the London open, `min_reward_r`, the 2R target alone, NY AM), each its own saved run compared to the baseline
3. The 1m entry once 1m data is in
4. The range-fade version
