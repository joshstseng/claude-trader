# Step 2b: Bot fleet

Part of [ROADMAP.md](../ROADMAP.md). Status: ⬜ Planned (2026-11-18) · runs in parallel with the Step 2 strategy work, before Step 3

**Goal:** turn the one-bot app into a fleet: **one bot per strategy**, each with its own brain, Discord identity and Alpaca paper account; a **head bot** that watches them all; one **market data service**; one **shared database**. The ORB bot keeps running, unchanged in behavior, the whole time.

**Diagram:** [Trading Bot Fleet](https://claude.ai/artifact/CWdoipSXSR7AKbiqwQJhup) (private to you): the components, their arrows, what happens when each one fails, and the build order.

```
                ┌────────────── HEAD BOT ───────────────┐
                │ summary · watchdog · global limits    │
                │ /flatten all · later: Claude review   │
                └───────┬───────────────────────────────┘
                        │ reads all bots, sets global pause
   MARKET DATA ──bars──►  ORB BOT · BOT B · BOT C  ──orders⇄fills──►  own Alpaca paper account each
   (fetches once)        │ each: own Discord bot, own brain
                        ▼
                 SHARED DATABASE (Postgres): signals, orders, events, heartbeats, runs, pause
   all bots + head post to the same channels: #setups #live-trades #closed-trades #system #daily-summary #backtests
```

---

## Decisions (2026-11-18)

| Decision | Choice |
|---|---|
| Bots | **One bot per strategy**: same codebase, many deployments (`STRATEGY=orb`, …). Each has its own strategy module ("brain"); the plumbing (orders, cards, 3:55 sell, restart safety, backtest engine) is shared |
| Discord | Each bot is its **own Discord bot** (own name in the channels); all post to the **same channels**, tagged `[ORB]`, `[…]` |
| Accounts | **One Alpaca paper account per bot**: no collisions in the same stock, the 3:55 sell touches only that bot, P&L per bot for free. (Real money later: several live accounts may be harder; fallback is per-bot tracking in one account) |
| Head bot | Supervisor only: combined daily summary, watchdog (heartbeats), global limits, `/flatten all`; later the home of the Step 3 Claude filter. **Trading never waits on it** |
| Market data | Its **own service, not a Discord bot**: fetches once, serves every bot; kept apart from the head so the traders never depend on the head |
| Database | **Railway Postgres**, shared; every row tagged with its bot. Replaces the per-bot log file (other services can't read a Railway volume) |
| Safety rule | **Every trading bot stays safe on its own.** If the head, the data service or the database fails, open trades stay protected at Alpaca and are still sold by 3:55 |
| When bot #2 | **Only once a second strategy shows an edge in the backtest.** The plumbing that helps with one bot comes first |

---

## Sub-steps

### 2b.1 Strategy interface
The ORB bot's brain becomes **one strategy module behind a common contract**; everything else talks to the contract.
- The contract: the strategy's id and tag; its schedule (pre-market time, check times, exit policy: flat by 3:55); how it builds its watchlist; how it **decides** at a check (no trigger / an entry with stop and target); how it generates signals over history for the backtest
- `app/strategies/orb.py` holds today's ORB logic (focus list, `engine.decide`); the day routine, pipeline, backtest runner and Discord text become strategy-agnostic (`[ORB]` comes from the strategy's tag)
- `python -m app backtest --strategy orb …`; `python -m app run` picks the strategy from `STRATEGY` (default `orb`)

**Done when:** every existing test passes unchanged (the 16/16 Oct 19 match, the live = backtest test), **baseline run #1 reproduces exactly** (683 trades, −0.038R), and a small demo strategy can be backtested with `--strategy demo` without touching ORB code.

### 2b.2 One codebase, many deployments
- Per-bot settings from environment: `STRATEGY`, its own `DISCORD_BOT_TOKEN`, its own `ALPACA_*` keys; the shared channel ids stay the same
- Storage and log paths, card ids and button ids namespaced by bot, so two bots never touch each other's state
- A setup guide for adding a bot: Discord app, Alpaca paper account, Railway service (~20 minutes of clicking)

**Done when:** the ORB bot on Railway runs exactly as before with `STRATEGY=orb`, and a second local config (demo strategy, another Discord bot, another paper account) runs side by side in a test.

### 2b.3 Shared database
- Railway Postgres; the trade log works on Postgres (and still on SQLite for local tests and backtests)
- Move the ORB bot's existing live history from its Railway volume into Postgres
- New: a **heartbeat** row per bot every minute; a **global pause** flag every bot reads before an entry; a **commands** table (e.g. "flatten") that bots poll, so the head never needs anyone's broker keys

**Done when:** the ORB bot runs on Postgres with its history moved, and the heartbeat, pause and commands work in tests.

### 2b.4 Head bot v1
- Its own Discord bot and Railway service; reads the shared database
- **Combined daily summary** across all bots (each bot's own summary can stay or be retired)
- **Watchdog:** a bot's heartbeat older than ~3 minutes during market hours → @mention in `#system`; the trading bots watch the head's heartbeat in turn
- **Global controls:** `/pause all`, `/resume all`, `/flatten all` (via the commands table; each bot flattens its own account); total money at risk across bots shown in `/status` (global limits enforced later)

**Done when:** stopping a bot on Railway gets you pinged within ~3 minutes, the combined summary posts after the close, and `/flatten all` closes a test position through the bot.

### 2b.5 Market data service *(right before bot #2)*
- Fetches bars, prices, the calendar and focus lists once; serves them over Railway's private network; caches
- Bots use it, falling back to fetching for themselves if it's down

**Done when:** the ORB bot gets all its market data from the service, and a stopped service makes it fall back without missing a check.

### 2b.6 Bot #2 *(when a second strategy earns it)*
- Pick it from backtests of candidate strategies run through the 2b.1 interface (candidates to explore in Step 2: e.g. VWAP reclaim, gap-and-go, opening-drive pullback)
- Its own Discord bot, Alpaca paper account and Railway service; then its own 1a/1b-style live gates

**Done when:** bot #2 has run a clean week of alerts next to the ORB bot.

---

## Order and timing
1. **2b.1 → 2b.2 → 2b.3 → 2b.4** now, alongside the Step 2 strategy work (2b.1 also lets the backtester test new strategies)
2. **2b.5 → 2b.6** once a second strategy backtests well
3. **Step 3** (Claude filter) is then built into the head bot

Changes to the live ORB bot deploy **outside market hours**, and each sub-step proves the ORB bot behaves exactly as before.
