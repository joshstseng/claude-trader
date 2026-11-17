# Step 1b: One-tap approval → paper orders

Part of [ROADMAP.md](../ROADMAP.md). Status: ⬜ Not started (planned 2026-11-17)

**Goal:** tapping **[Approve]** on an alert places a real bracket order (entry + stop + target) on your Alpaca **paper** account. The bot tracks it to the end, flattens by 3:55 PM, and records real fill prices so we know what trading actually costs.

**Gate to finish:** 2–3 weeks of paper trading (at least 20 approved trades) where every fill, stop, target and 3:55 flatten is handled correctly with no manual fixes, and the **measured cost per trade** is known and fed back into the backtest.

**Still true:** paper only (enforced in code); no options, shorting or margin; the risk check can always block a trade; stops are held by Alpaca.

---

## Decisions (2026-11-17)

| Decision | Choice | Why |
|---|---|---|
| Live market data | **Free sources only.** Measure first (1b.1), then pick **Alpaca IEX real-time** or **Yahoo with an extra minute to settle** | Don't pay for data until the strategy shows an edge. TradingView (CME/COMEX) can't be used: futures, not stocks, and no data API |
| Live engine | **The live bot uses the backtest's in-process engine** (the skill's `entry.evaluate` / `exit.compute` / `size.size_trade`, fed live bars) | Live and backtest make decisions with literally the same code; no Yahoo fetches inside the skill scripts; faster checks |
| Account | **Simulated $5k account with the cash limit ON** (matches the backtest baseline) | The paper account has far more money; the app caps it to $5k, no margin |
| Risk check | The skill's `check.py` stays the final gate before every order, with real state: today's placed orders and the simulated account's cash | The skill's own guard, now counting real entries |
| Entry order | **Limit order** at the alert's entry price plus a small buffer (proposed: the lesser of 0.1R and 0.1%), cancelled if not filled within 2 minutes | Caps slippage; a missed fill is logged, not chased |
| Exits | Bracket: stop and target held by Alpaca; the app flattens at 3:55 PM itself | Alpaca cancels the stop/target at the close but leaves the shares |

---

## Sub-steps

### 1b.1 Live data: measure, then choose
- **Backtest check:** download Alpaca's **IEX** 5-minute bars (free, historical) for ~3 months of focus lists and rerun the signal engine. How often do IEX-based signals match SIP-based ones (the backtest's)? How different are the results?
- **Live audit (already possible with 1a):** after each close, compare each live alert's trigger bar (from Yahoo, as seen live) with Alpaca's full-market bar from 20 minutes later: same trigger? same volume ×?
- **Choose:** Alpaca IEX if it agrees with SIP ≥ ~90% of the time; otherwise Yahoo with a 1-minute settle (alerts ~1 minute later)
- Build the live bar source behind one interface (Alpaca IEX, with Yahoo as automatic fallback)

**Done when:** the numbers are in, the source is chosen, and live checks read bars through it.

### 1b.2 One engine for live and backtest
- Live checks run the backtest's signal engine on live bars (same functions, same filters: $5 floor, missing-bar skip, alphabetical ties)
- The ORB scan pre-filter, the Time Machine and news stay as they are (information for the alert)
- Test: replaying a day through the live path gives the same signals as the backtest for that day

**Done when:** a replayed day gives identical signals both ways.

### 1b.3 Simulated $5k account + real risk state
- `portfolio.json` (cash, open positions) and today's placed orders kept up to date for `check.py`, so it enforces **3 trades a day, the $150 daily loss limit and the cash limit** on real entries
- Account resets each morning (day trades only, nothing held overnight)

**Done when:** `check.py` blocks a 4th trade, a trade over the daily loss limit and a trade the cash can't cover, in tests.

### 1b.4 Approve → order
- Alert buttons become **[Approve] [Skip]**; only you can press them
- On Approve:
  1. **Stale check:** the alert is under N minutes old (proposed 5) and the price hasn't moved more than a set amount past the entry (proposed 0.25R) or below the stop. If it fails, it's refused, with the reason shown on the alert
  2. **Final risk check** (`check.py`, with a fresh price)
  3. **Bracket order** to Alpaca paper (limit entry, stop, target), with the signal id as the order id so a retry can never double-order
- The alert updates live: *submitted → filled at $X (slippage $Y) / not filled, cancelled*

**Done when:** an approval in a paper session places exactly one order, and a stale or blocked approval places none.

### 1b.5 Tracking fills and exits
- Alpaca's live trade updates (stream): entry fills, partial fills, stop hits, target hits
- Posts to **`#trades`**: filled, stopped ❌, target ✅, flattened ➖, with real P&L
- Trade log: new `orders` / `fills` records. **Slippage** = fill price vs plan price, on entry and exit

**Done when:** every state change of a paper trade shows up in `#trades` and the log.

### 1b.6 Flatten at 3:55 PM + safety net
- 3:55 PM (12:55 PM on early closes): cancel any remaining stop/target orders, sell at market, post the result
- **3:58 PM backup** check: anything still open is flattened again, and you're @mentioned in `#system`
- Discord: **`/positions`** (what's open) and **`/flatten`** (kill switch: close everything now and pause)

**Done when:** a test position left open is closed at 3:55, and the 3:58 backup catches one the first pass missed.

### 1b.7 Restart safety
- On startup: read open orders and positions from Alpaca and match them to today's signals; resume tracking, never place duplicates
- A redeploy mid-trade loses nothing: stops and targets stay at Alpaca the whole time

**Done when:** killing and restarting the app with an open position resumes tracking and still flattens at 3:55.

### 1b.8 Measured costs
- Daily summary gains the real numbers: fills vs plan, slippage per trade, measured cost in R
- After ~20+ fills: compare with the backtest's assumed 0.03%/side, update `costs.pct_per_side`, and rerun the key backtests with the real cost

**Done when:** the measured cost is in the backtest settings and the baseline has been rerun with it.

---

## Not in Step 1b
- Hands-off trading (no tap) → Step 4
- Claude filter → Step 3
- Paid data → only if the strategy shows an edge worth protecting
- Strategy changes → Step 2 variations (independent of this plumbing)

## Open questions (to settle while building)
- Exact stale-check limits (5 minutes, 0.25R?) and the entry limit buffer (0.1R / 0.1%?): start with these, adjust after a week of paper fills
- Whether to keep "Took it" for alerts you trade elsewhere (probably not needed once Approve exists)
