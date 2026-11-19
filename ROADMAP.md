# claude-trader Roadmap

**Goal:** an app that scans the market, finds setups, builds a full entry and exit plan for each, and in the end places trades by itself.

**How:** a Python app (`app/`) that runs the scripts in [day-trader-skill/](day-trader-skill/) on a market schedule. Alpaca is the broker and Discord is how you see setups and approve trades. Claude builds and tunes the app; it never places orders. Later it may act as a filter that can only say no to a trade.

> Each step gets its own detailed plan, broken into sub-steps, when we start it. Those plans go under the step below.

---

## Overview

```
STEP 1a          STEP 1b              STEP 2           STEP 2b          STEP 3          STEP 4         STEP 5
Alerts      ──►  Approve → paper ──►  Backtest    ──►  Bot fleet   ──►  Claude      ──► Hands-off ──►  Hands-off
+ trade log      orders               (approve all)    (head, data,     filter (in      on paper       real money
                                      + strategy work  shared DB)       head bot)
no orders        paper orders         no orders        paper orders     paper orders    paper orders   real orders,
                 you tap Approve                                        you tap         no tap         tiny size
```

| Step | Name | Status |
|---|---|---|
| 1a | Alerts + trade log | 🟨 Built and live on Railway · 5-day live gate from Nov 18 |
| 1b | One-tap approval → paper orders | 🟨 Built (1b.1–1b.7, 1b.8 part 1, 1b.9 live trade cards) · paper orders ON · gate: 2–3 weeks, ≥20 trades |
| 2 | Backtest #1 (baseline) | 🟨 Framework done · baseline + 4 target runs · strategy variations next |
| 2b | Bot fleet (strategy interface, shared DB, head bot, data service) | 🟨 2b.1 strategy interface ✅ · 2b.2 per-bot config ✅ · 2b.3 shared database ✅ · 2b.4 head bot built, going live |
| 3 | Claude filter + Backtest #2 | ⬜ Not started (built into the head bot) |
| 4 | Hands-off on paper | ⬜ Not started |
| 5 | Hands-off with real money | ⬜ Not started |

Status key: ⬜ Not started · 🟨 In progress · ✅ Done

**Daily checklist while the live gates run:** [plans/live-checklist.md](plans/live-checklist.md)

---

## Rules that apply to every step

- **The risk check can always block a trade.** Nothing reaches Alpaca without passing `trader-risk/check.py`.
- **Stops are held by Alpaca.** Every order is a bracket order (entry + stop-loss + take-profit), so a crash in the app never leaves a position unprotected.
- **Paper only is enforced in code** until Step 5. The app refuses to start against a live account.
- **Keys stay in `.env`** (ignored by git) and never go in chat or commits.
- **Nothing moves to the next step until its gate is passed.**

---

## Step 1a: Alerts + trade log

**What:** the app runs every market day, finds setups, builds the full plan and posts it to Discord. No orders. Every alert is logged, and after the close the app works out what each alert would have done.

**Includes:**
- Project layout (`app/`), `.env` for keys, a settings file for rules (account size, max loss per trade, daily loss limit, setups, times)
- Market clock and scheduler using Alpaca's market calendar (handles holidays and half-days)
- Daily routine: pre-market scan + news → watchlist; 9:45–11:30 AM checks every 5 minutes for opening-range breakouts and entry triggers; on a trigger: exit plan → Time Machine → position size → risk check → alert
- Discord setup (private server, bot, channels `#setups` `#trades` `#daily-summary` `#system`)
- Discord bot built into the app: alerts with the full plan; commands `/status` `/today` `/pause` `/resume`
- SQLite trade log: every setup, its plan, its odds, your response and what it would have done
- End-of-day summary; keeps the Mac awake during market hours; starts automatically; health pings

**Gate:** 5 market days in a row with no manual help; alerts and summaries arrive in Discord.

**Plan:** [plans/step-1a-orb-alerts.md](plans/step-1a-orb-alerts.md). Sub-steps 1a.1–1a.8: skeleton → accounts → pipeline wrapper → trade log → scheduler → Discord bot → after the close → running unattended.

---

## Step 1b: One-tap approval → paper orders

**What:** alerts get **[Approve] [Skip]**. Approve sends a bracket order to your Alpaca **paper** account.

**Includes:**
- Order sending through Alpaca's API (bracket orders), and only your Discord user can approve
- Stale-approval check: refuses an approval that comes in too late or after the price has moved too far from the entry
- Tracks fills, stops hit and targets hit; posts them to `#trades`
- Position tracking and the 3:55 PM flatten, which also works after a mid-day restart
  - **Alpaca doesn't close positions at the end of the day.** At the close it cancels a bracket's stop and target orders but leaves the shares in the account. So at 3:55 PM (12:55 PM on early-close days) the app must cancel any remaining stop/target orders and sell at market
  - **Backup:** a second check at 3:58 PM flattens anything still open, and @mentions you in `#system` if a position is still open after that (e.g. the app was down mid-redeploy). Nothing is ever held overnight
- Market data switches from Yahoo (delayed) to Alpaca's live feed (free IEX)
  - *Found in Step 2.2:* Yahoo's **newest** 5-minute bar during the session can have badly wrong volume (TSLA 10:30 on Oct 19: ~25× too high), and the live bot reads exactly that bar for its volume check. But Alpaca's free real-time feed is IEX only (one exchange, a few % of volume), and its full feed (SIP) is 15 minutes delayed. Options: IEX volume ratios, waiting one extra minute for Yahoo to settle, or a paid SIP plan. Decide here
- Records real fill prices, so we can measure how much worse fills are than the chart price
- **Enforce the simulated $5k account's cash** (no margin): a new entry only if open positions + it fit $4,500. Alpaca's paper account has far more, but the backtest baseline uses this rule (decided 2026-11-17), so live paper must too

**Gate:** a few weeks of paper trades without errors, with fills, stops, targets and flattens all handled correctly.

**Plan:** [plans/step-1b-paper-orders.md](plans/step-1b-paper-orders.md). **Add-on 1b.9, live trade management** (`#live-trades` cards with Close / Break-even / Move stop / Move target, `#closed-trades`): [plans/step-1b9-live-trades.md](plans/step-1b9-live-trades.md). Sub-steps 1b.1–1b.8: live data (measure, then choose a free source) → one engine for live and backtest → simulated $5k account + risk state → Approve → order → fills tracking → 3:55 flatten + safety net → restart safety → measured costs.

---

## Step 2: Backtest #1 (baseline, no Claude)

**What:** replay the exact Step 1 pipeline over 1–2 years of Alpaca historical minute bars, **assuming every trade is approved**.

**Includes:**
- Backtester that replays the pipeline day by day, without looking at data from later in the day (no look-ahead)
- Cost per trade taken from the real paper fills in Step 1b
- Every run saved with its settings, code version and date range, so any two runs can be compared
- Results in the same trade log as live alerts, so we can check backtest against live
- Compare approve-all with your actual taps: does your judgment add anything?
- Known blind spots to account for: delisted stocks missing from the data, fill costs, data gaps
- **ORB bot variations to test** (each run labeled `orb`):
  - Targets: 1R, 1.5R, 2R, 3R
  - Stops: range midpoint, range low, ATR multiple
  - Scan window: 9:50–11:30 AM vs later breakouts (up to 3:30 PM)
  - Volume check on the trigger bar: off vs 1.0× vs 1.5×
  - Focus list size and how signals are picked
  - **Ranking vs first come, first served** *(noted 2026-11-17)*: in the Oct 19 replay the 5 earliest signals (CDNS, CVX, HUM, ELV, EOG, all by 9:55) used the whole daily cap, so later ones like TSLA, MSFT and AMZN were held back. Test ranking by volume ×, % over the range, or dollars traded instead
  - **Minimum stop distance** *(noted 2026-11-17)*: HMC's stop was only $0.05 (0.15%) below the entry, which gave 110 shares. A stop that tight is likely to be hit by normal price wiggle and the bid-ask spread. Test a minimum stop distance (e.g. a % of price or a multiple of ATR)
- **Discord `#backtests` channel:** one short summary per backtest run (settings, trade count, win rate, average R, expectancy, max drawdown, compared with the baseline), with a link to the full report. Create the channel when this step starts

**Plan:** [plans/step-2-orb-backtest.md](plans/step-2-orb-backtest.md). Sub-steps 2.1–2.6: outcome engine → historical data → signal engine → selection rules + costs → runs + reports → `#backtests` channel.

**Gate:** expected profit per trade is positive after costs, and the backtest roughly matches live paper results. If not, tune the setups or rules and backtest again (as many runs as needed).

**Sub-steps:** *to be planned*

---

## Step 2b: Bot fleet

**What:** turn the one-bot app into a fleet: one bot per strategy (own brain, own Discord bot, own Alpaca paper account), a **head bot** that watches them all, one **market data service**, one **shared database**. The ORB bot keeps running unchanged throughout.

**Plan:** [plans/step-2b-bot-fleet.md](plans/step-2b-bot-fleet.md). Diagram: [Trading Bot Fleet](https://claude.ai/artifact/CWdoipSXSR7AKbiqwQJhup). Sub-steps: strategy interface → one codebase, many deployments → shared database → head bot v1 → (when a 2nd strategy earns it) market data service → bot #2.

**Gate:** the ORB bot behaves exactly as before on the new structure, and the head bot's watchdog and combined summary are live. Bot #2 joins only when a second strategy shows an edge in the backtest.

---

## Step 3: Claude filter + Backtest #2

**What:** add Claude as a filter that can only say no to a trade, then rerun the Step 2 backtest and compare. It lives in the **head bot** (Step 2b), reviewing every bot's setups. If the head is down or slow, a bot trades without the filter (the baseline), so trading never waits on it ([how the head grows](plans/step-2b-bot-fleet.md#the-head-bot-from-here)).

*Not designed yet on purpose. We plan this step when we get here.*

**Gate:** the filter measurably beats the baseline. If it doesn't, leave it out.

---

## Step 4: Hands-off on paper

**What:** the approval tap turns off, and the risk check is the only gate. Discord becomes a feed of what happened, plus `/pause`, `/flatten` and a kill switch.

**Likely includes:** global limits enforced across bots (each bot checks them itself from the shared database) and the head bot's automatic pause on a breached limit or a misbehaving bot. Uptime is covered: the head's watchdog (2b.4) already pings you when a bot stops responding.

**Gate:** ~100+ hands-off trades with positive expected profit, matching the backtest, with no runaway bugs.

---

## Step 5: Hands-off with real money

**What:** switch to the live Alpaca account with tiny position sizes, a hard daily loss limit and a kill switch. Grow size slowly as results hold up.

**Gate:** ongoing. Results are reviewed regularly against the backtest, and the app pauses itself when the daily loss limit is hit.

---

## Decisions log

| Date | Decision |
|---|---|
| 2026-11-17 | Vendored `day-trader-skill` into this repo; skills also installed to `~/.claude/skills/` |
| 2026-11-17 | Python app runs the scripts on a schedule; Claude is not in the loop that places orders |
| 2026-11-17 | Broker: **Alpaca** (paper first) |
| 2026-11-17 | Notifications and approvals: **Discord** (separate channels) instead of Telegram |
| 2026-11-17 | One-tap approval (1b) comes **before** the backtest; the backtest assumes every trade is approved |
| 2026-11-17 | Backtests are repeatable and compared; the baseline has no Claude filter, and the filter is tested later |
| 2026-11-17 | ~~Starts on the Mac; moves to a server by Step 4~~ → **Runs on Railway from Step 1a** (you didn't want to keep the Mac on). Trade log on a Railway volume |
| 2026-11-17 | First strategy is the **ORB bot** (opening range breakout, long only, US stocks only). Everything is tagged with a strategy id so more bots can be added later |
| 2026-11-18 | **No `[ORB]` tag in the trading bot's Discord messages**: each bot posts under its own Discord name. Logs keep the tag; each strategy's backtests post as its own bot (`DISCORD_BOT_TOKEN_<ID>` on the Mac), tagged only when another bot posts them |
| 2026-11-18 | **Step 2b: Bot fleet** before Step 3: one bot per strategy (own brain, Discord bot and Alpaca paper account, shared channels), a head bot (summary, watchdog, global limits; later the Claude filter), a market data service (not a Discord bot) and a shared Postgres database. Every trading bot stays safe on its own. Bot #2 only once a second strategy backtests well |
| 2026-11-19 | **Head bot v1** (2b.4): same code with `BOT_ROLE=head`, its own Discord bot, **no broker keys**, a second service in the same Railway project. Watchdog (3 min, 9:00 AM ET to 20 min after the close), fleet summary at 4:35 PM ET (each bot's own summary stays), `/fleet`, `/pause-all`, `/resume-all`, `/flatten-all` through a commands table each bot answers with its own keys |
| 2026-11-18 | **Live trade management** in Discord: `#live-trades` (one updating card per trade, buttons; stops only move up) and `#closed-trades` (renamed `#trades`, @mention on close). Resolved alerts in `#setups` collapse to one grey line with an ET timestamp |
| 2026-11-17 | Step 1b uses **free live data only** (measure Alpaca IEX vs Yahoo first; TradingView CME/COMEX can't be used: futures, no API) and moves the live bot onto the **backtest's engine** |
| 2026-11-17 | Backtest baseline and Step 1b both use a **cash limit**: the $5k account can't use margin, so usually one ~$3.5k position at a time |
| 2026-11-17 | Backtest framework started in parallel with the Step 1a live gate (assumed cost 0.03%/side until Step 1b's real fills). Baseline: Nov 2024 → Nov 2026, live v1 settings, cap 5 first come first served; ranking tested later |
| 2026-11-17 | Step 1a v1 settings: focus list = top ~150 most traded over $5 plus daily-scan hits; scan window 9:50–11:30 AM; trigger bar volume ≥ 1.0×; at most 5 alerts a day; stop at range midpoint, target 2R; $5k account / $50 max loss / $150 daily loss limit / 3 trades a day; shared Discord channels tagged `[ORB]` |

---

> **Not financial advice.** Most day traders lose money. Paper first, small size, and the gates exist for a reason.
