# Brix in Discord (Break and Retest)

How Brix ([bar-strategy.md](bar-strategy.md), NQ, NY AM) becomes a bot in your Discord server, next to Orbi and Uri. Written 2026-11-20 for Brix; renamed for Brix the same day.

> Keys and tokens go into Railway's Variables page and your local `.env`, never into a chat.

## The catch: live data and a broker
Brix can join the server today, but **trading live needs two things we don't have yet**:
- **Live futures data:** Yahoo's NQ data is about **10 minutes late**, too late to trade a 5m setup. Real-time data comes with Tradovate's API (or a paid feed like Databento)
- **A futures broker:** Alpaca has no futures; Tradovate demo is the plan

So it goes in three stages. Each one is useful on its own, and you only pay for Tradovate in stage 3.

| Stage | What Brix does in Discord | Costs |
|---|---|---|
| **M1. Join the server** | Its own Discord bot. Its backtests post in `#backtests` as **Brix** | Free |
| **M2. Shadow mode** | Runs every NY AM session on Railway on the delayed Yahoo data, with **simulated fills**: posts each setup, a live card, a closed card, roll calls and summaries, all marked 👻 **shadow** (about 10 min behind the market) | Free (a small Railway service) |
| **M3. Demo trading** | The same, on real-time Tradovate data, placing its own orders on the **Tradovate demo** account | Tradovate API + data fees |

**Gates:** M2 starts once the baseline backtest looks worth it. M3 once M2 has run a clean week (every session posted, nothing stuck, numbers match a backtest of the same days).

## What you'll see
Shared channels, under Brix's own name (like Orbi):

| Channel | Brix posts |
|---|---|
| `#system` | 🟢 online / 🔴 stopped; Uri's roll calls ("☀️ **Good morning! NYAM session.** Orbi and Brix are up and trading") |
| `#setups` | Every setup, logged even though it's taken automatically: `🔻 MNQ short · crossed the upper band 6:35 PM PT · RSI 41 · ADX 27 → waiting for a candle back inside` → then `✅ taken at 18,402.25` or `⌛ dropped: didn't come back inside` |
| `#live-trades` | One card per trade: side, contracts, entry, stop, targets (middle band and 2R), now, P&L in $ and R, refreshed every minute. Buttons **Close now** and **Break-even** |
| `#closed-trades` | The final card with an @mention (removed after the daily summary, like Orbi's) |
| `#daily-summary` | Nothing directly: Uri puts Brix's day in the daily summary thread |
| `#backtests` | Its backtest runs |

**Commands:** its own `/pause`, `/resume`, `/flatten` (only Brix's account); `/status Brix` lives on Uri.

## M1. Join the server
**You (~5 min):**
1. **discord.com/developers/applications** → **New Application** → name it **Brix**
2. **Bot** → **Reset Token** → copy it. Turn off **Public Bot**. Optional: give it an avatar
3. **OAuth2 → URL Generator** → scopes **bot** + **applications.commands**; permissions **View Channels, Send Messages, Embed Links, Read Message History, Use Slash Commands** → open the link → add it to the `claude-trader` server
4. On your Mac, add to `.env`: `DISCORD_BOT_TOKEN_BAR=<token>` (its backtests post under its name)
5. Make sure it can see `#setups`, `#live-trades`, `#closed-trades`, `#system` and `#backtests` (same as Orbi)

**Me:** the Brix backtest command (`python -m app backtest --strategy bar …`) already exists; with the token in `.env` it posts as Brix instead of Uri.

## M2. Shadow mode
**Me (the bulk of the work):**
1. **One engine for backtest and live.** Turn `run_session` into a step-by-step engine fed one bar at a time, so live and the backtest make exactly the same decisions (the rule we follow for Orbi)
2. **A futures runner:** the NY AM window on its own schedule (Pacific time, Mon–Fri, CME holidays), warm-up from earlier bars, a bar feed (Yahoo delayed now, Tradovate later)
3. **Futures in the shared code**, which today assumes long-only stocks with shares and Alpaca:
   - trades with a **side** (long/short), **contracts** and **$2 a point** in the trade log, cards and P&L
   - stops only ever move **toward profit**: up for a long, **down for a short**
   - no Alpaca keys needed for a futures bot
   - the middle-band target moves every bar, so the bot manages its own exit instead of a fixed bracket order
4. **A simulated broker** (fills at the bar's close or level, the same costs as the backtest), everything marked 👻 shadow
5. **Uri's roll calls** ([head-session-hours.md](head-session-hours.md)). Brix trades NY AM, so Uri's current watch hours already cover him; per-bot hours matter only for a night bot later.
6. Tests, plus the usual checks that **Orbi behaves exactly as before**

**You (~5 min):** a new Railway service in the same project (same repo), a volume at `/data`, and these variables:
```
STRATEGY=mrs
DISCORD_BOT_TOKEN=<Brix's token>
DATABASE_URL=${{Postgres.DATABASE_URL}}
DISCORD_GUILD_ID / DISCORD_OWNER_ID / DISCORD_CHANNEL_* = same as the ORB service
```
No Alpaca keys.

## M3. Demo trading
**You:** a Tradovate account with **API access** and a **demo** account; the CME market data for the API (check the current prices and terms). Keys only in Railway.

**Me:** a Tradovate broker (place, cancel, close, positions, fills) and live data feed in place of Yahoo; orders on demo only (the same paper-only lock as Alpaca until Step 5); `/flatten` and Uri's `/flatten-all` close Brix's demo positions.

## Decisions for you
1. **Shadow mode (M2) first?** It's free and tests every Discord piece before paying for Tradovate, but runs about 10 minutes behind. *(My recommendation: yes)*
2. **The same channels as Orbi**, or a separate `#futures` set? *(Recommendation: the same; each bot posts under its own name, as planned for the fleet)*
3. **Buttons on its live card:** Close now and Break-even only, or Move stop and Move target as well?
