# Step 2b: Bot fleet

Part of [ROADMAP.md](../ROADMAP.md). Status: 🟨 In progress (2b.1 ✅ 2b.2 ✅ 2b.3 ✅ 2b.4 built, going live) · runs in parallel with the Step 2 strategy work, before Step 3

**Goal:** turn the one-bot app into a fleet: **one bot per strategy**, each with its own brain, Discord identity and Alpaca paper account; a **head bot** that watches them all; one **market data service**; one **shared database**. The ORB bot keeps running, unchanged in behavior, the whole time.

**Diagram:** [Trading Bot Fleet](https://claude.ai/artifact/CWdoipSXSR7AKbiqwQJhup) (private to you): the components, their arrows, what happens when each one fails, and the build order.

```
                ┌────────────── HEAD BOT ───────────────┐
                │ summary · watchdog · global limits    │
                │ /flatten-all · later: Claude review   │
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
| Discord | Each bot is its **own Discord bot** (own name in the channels); all post to the **same channels**. *(No `[ORB]` tag in messages since 2026-11-18: the bot's name says who posted)* |
| Accounts | **One Alpaca paper account per bot**: no collisions in the same stock, the 3:55 sell touches only that bot, P&L per bot for free. (Real money later: several live accounts may be harder; fallback is per-bot tracking in one account) |
| Head bot | Supervisor only: combined daily summary, watchdog (heartbeats), global limits, `/flatten-all`; later the home of the Step 3 Claude filter. **Trading never waits on it** |
| Market data | Its **own service, not a Discord bot**: fetches once, serves every bot; kept apart from the head so the traders never depend on the head |
| Database | **Railway Postgres**, shared; every row tagged with its bot. Replaces the per-bot log file (other services can't read a Railway volume) |
| Safety rule | **Every trading bot stays safe on its own.** If the head, the data service or the database fails, open trades stay protected at Alpaca and are still sold by 3:55 |
| When bot #2 | **Only once a second strategy shows an edge in the backtest.** The plumbing that helps with one bot comes first |

---

## Sub-steps

### 2b.1 Strategy interface ✅
The ORB bot's brain becomes **one strategy module behind a common contract**; everything else talks to the contract.
- The contract: the strategy's id and tag; its schedule (pre-market time, check times, exit policy: flat by 3:55); how it builds its watchlist; how it **decides** at a check (no trigger / an entry with stop and target); how it generates signals over history for the backtest
- `app/strategies/orb.py` holds today's ORB logic (focus list, `engine.decide`); the day routine, pipeline, backtest runner and Discord text become strategy-agnostic (`[ORB]` comes from the strategy's tag)
- `python -m app backtest --strategy orb …`; `python -m app run` picks the strategy from `STRATEGY` (default `orb`)

**Done when:** every existing test passes unchanged (the 16/16 Oct 19 match, the live = backtest test), **baseline run #1 reproduces exactly** (683 trades, −0.038R), and a small demo strategy can be backtested with `--strategy demo` without touching ORB code.

**As built (2026-11-18):**
- [app/strategies/base.py](../app/strategies/base.py): the `Brain` contract (schedule, live and historical watchlist, a pre-filter at each check, `decide`, the backtest's decision time)
- [app/strategies/orb.py](../app/strategies/orb.py): `OrbBrain` wraps the ORB bot's existing code unchanged (focus list, the skill's ORB scan, `engine.decide`, the 9:51–11:31 checks)
- [app/strategies/demo.py](../app/strategies/demo.py): a switched-off VWAP-reclaim demo brain that proves a second strategy plugs in
- The day routine (`BotDay`, with `OrbDay` kept as an alias), pipeline, scheduler and backtest call the brain; `python -m app run` picks the bot from `STRATEGY` (default `orb`); `backtest` and `replay` take `--strategy`; a backtest only compares with its own strategy's baseline
- Messages use the running bot's tag (`[ORB]` for ORB: identical text); log lines get the tag from the log format

**ORB regression checks (all passed):**
- Full test suite: 185 tests, including the 16/16 Oct 19 match and live = backtest
- Baseline rerun (run #6) vs run #1: **identical on every number of all three views**, and **all 20,690 signals identical** (date, stock, trigger, entry, stop, target, shares, outcome, R, alerted, taken)
- Live Yahoo path on today's data (TSLA, NVDA, AAPL): normal answers, ~0.2 s each
- The demo strategy backtested all 512 days through the shared plumbing (run #7, tagged DEMO) without touching ORB code

### 2b.2 One codebase, many deployments ✅ *(prepared without a second bot)*
- Per-bot settings from environment: `STRATEGY`, its own `DISCORD_BOT_TOKEN`, its own `ALPACA_*` keys; the shared channel ids stay the same
- Storage and log paths, card ids and button ids namespaced by bot, so two bots never touch each other's state
- A setup guide for adding a bot: Discord app, Alpaca paper account, Railway service (~20 minutes of clicking)

**Done when:** the ORB bot on Railway runs exactly as before with `STRATEGY=orb`, and tests prove a second bot's storage, orders and messages can't collide with the ORB bot's. *(Changed 2026-11-18: no second Discord bot or Alpaca account is needed yet; no strategy is ready. The real second bot is 2b.6, after the head bot.)*

**As built (2026-11-18):**
- Storage is per bot ([app/paths.py](../app/paths.py)): the ORB bot keeps its original layout (so nothing moves on Railway); any other bot gets `bots/<id>/data|runs|logs` (trade log, pause setting, day account, cards, logs, single-copy lock). Shared on purpose: the market data cache, the stock list, backtest runs and reports
- The bot identity (`STRATEGY`) drives storage, the tag in logs, and the strategy the app runs; order ids start with the strategy id (`orb-…`)
- [plans/add-a-bot.md](add-a-bot.md): the checklist for adding a bot (its brain, Discord bot, Alpaca paper account, Railway service)

**ORB regression checks (all passed):** 192 tests (new: the ORB bot's storage paths are exactly the ones it has always used on Railway; another bot's are separate; shared data is shared); baseline rerun run #8 = run #1 on all 20,690 signals; live Yahoo path normal

### 2b.3 Shared database ✅
- Railway Postgres; the trade log works on Postgres (and still on SQLite for local tests and backtests)
- Move the ORB bot's existing live history from its Railway volume into Postgres
- New: a **heartbeat** row per bot every minute; a **global pause** flag every bot reads before an entry; a **commands** table (e.g. "flatten") that bots poll, so the head never needs anyone's broker keys

**Done when:** the ORB bot runs on Postgres with its history moved, and the heartbeat, pause and commands work in tests.

**As built (2026-11-18):**
- The live trade log uses **Railway Postgres** when `DATABASE_URL` is set ([app/db.py](../app/db.py): the same small interface the trade log already used, translating its SQL). Replays, backtests and tests keep using SQLite files
- **One-time copy:** on its first start with Postgres, the bot copies its SQLite trade log in (every row, same ids; new ids continue after them) and keeps the old file as `tradelog.db.moved-to-postgres`. It never runs twice
- New shared tables: `heartbeats` (each bot writes one a minute) and `fleet_settings` (`global_pause`, which every bot now honors on top of its own `/pause`). Order queries are filtered by the running bot's strategy, since every bot's rows now sit in one database
- The commands table for `/flatten-all` moves to 2b.4 with the head bot, which is its only user

**ORB regression checks (all passed):** 195 tests on SQLite **and** the same suite with the trade log on a throwaway local Postgres (Docker); new Postgres tests for the copy, heartbeats, global pause and per-bot orders; baseline rerun run #9 = run #1 on all 20,690 signals; the Docker image installs the Postgres driver and writes a heartbeat. Tests never touch the live database

### 2b.4 Head bot v1
- Its own Discord bot and Railway service; reads the shared database
- **Combined daily summary** across all bots (each bot's own summary can stay or be retired)
- **Watchdog:** a bot's heartbeat older than ~3 minutes during market hours → @mention in `#system`; the trading bots watch the head's heartbeat in turn
- **Global controls:** `/pause-all`, `/resume-all`, `/flatten-all` (via the commands table; each bot flattens its own account); total money at risk across bots shown in `/fleet` (global limits enforced later)

**Done when:** stopping a bot on Railway gets you pinged within ~3 minutes, the combined summary posts after the close, and `/flatten-all` closes a test position through the bot.

**As built (2026-11-19):** setup and tests in [setup-head-bot.md](setup-head-bot.md)
- [app/head.py](../app/head.py): the same code started with `BOT_ROLE=head` (its own folder `bots/head/`, `[HEAD]` in logs); its own Discord bot (`DISCORD_BOT_TOKEN_HEAD`, refused if it equals a trading bot's token); no broker keys; needs `DATABASE_URL`
- Watchdog: heartbeat older than 3 min, 9:00 AM ET to 20 min after the close → @mention once per outage, "back" when it returns; bots with no heartbeat for 3 days count as retired. The trading bots watch the head (5 min, market hours) and their heartbeat note now says `running` / `paused (own /pause)` / `paused (global)`
- Daily summary: *(changed 2026-11-20, your call: avoid a cluttered channel as bots are added)* the head is the **only poster in `#daily-summary`**. Each bot saves its full after-close summary in a `daily_reports` table; the head posts one message once every bot has reported (or at 5:00 PM ET, naming a missing one) with each bot's full summary in a thread under it. Catch-up for the previous market day; remembered in the database so a restart can't repeat it. A bot that can't reach the database posts its own summary
- Slash commands (Discord names can't have spaces): `/fleet`, `/pause-all`, `/resume-all`, `/flatten-all confirm:yes`
- Commands table: `fleet_commands` + `fleet_command_acks`. Each trading bot checks every 5 s, acts only on commands under 2 minutes old (a bot starting later never acts on an old one), runs the same flatten as its own `/flatten` (shared code), posts the result in `#system` and answers

**ORB regression checks (all passed):** 212 tests on SQLite and on a throwaway local Postgres (17 new); baseline rerun run #10 = run #1 on all 20,690 signals; live Yahoo path normal; the head bot logged into Discord and wrote its heartbeat (against the throwaway database). The ORB bot's changes are small and only additive: the heartbeat note, watching the head, and answering the head's commands

**Going live (2026-11-19):** pushed during market hours with nothing open (you OK'd it); the head runs as a second service in the **same Railway project** as the ORB bot and Postgres. Left to check: `/fleet`, `/pause-all` → `/resume-all`, `/flatten-all` with nothing open, and the watchdog ping (stop the ORB service on a market day inside the watch window, outside the 9:45–11:35 AM scan)

### The head bot from here
v1 only watches and relays. Where it grows, in order:
| When | What the head adds | How it stays safe |
|---|---|---|
| **Step 3** (Claude filter) | Every bot's setup goes to the head for a Claude review that can only say **no** (veto, with a one-line reason on the alert); backtested against the baseline first | A time limit on the review: if the head is down or slow, the bot carries on without the filter (exactly the baseline), so trading never waits on it |
| **Before Step 4** | **Global limits enforced**, not just shown: fleet-wide daily loss limit, total money at risk, open positions across bots, the same stock in two bots | Each bot checks the limits itself from the shared database before an entry, so they hold even with the head down; the head adds the global pause and pings |
| **Step 4** (hands-off) | Automatic kill switch: global pause (or flatten) on a breached limit, an error storm, a bot that keeps going silent, or the live data drifting from the backtest's; a weekly report per bot vs its backtest | Pausing is always safe; anything stronger (flatten) is a rule you approve in advance |
| **2b.5 / 2b.6** | Watches the market data service's heartbeat too; picks up bot #2 automatically (watchdog, summary, `/flatten-all`) | Bots fall back to fetching their own data |
| **Step 5** (real money) | How much money each bot gets, from its results | Hard limits stay in each bot's own risk check |

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
