# Setting up the head bot (Step 2b.4)

Part of [step-2b-bot-fleet.md](step-2b-bot-fleet.md). About 10 minutes. The head bot runs the **same code** as the trading bots, started with `BOT_ROLE=head`. It has **no Alpaca keys** and **no volume**: everything it knows comes from the shared Postgres.

> Keys and tokens go into Railway's Variables page and your local `.env`, never into a chat.

## 1. Its Discord bot ✅ (done 2026-11-19)
A separate Discord application ("Uri"), added to the server with **bot** + **applications.commands** and View Channels, Send Messages, Embed Links, Read Message History, Use Slash Commands. Its token is `DISCORD_BOT_TOKEN_HEAD` (also in your Mac's `.env`).

## 2. Its Railway service (you, ~5 min, after the code is pushed)
1. Your **existing** Railway project (the one with the ORB service and Postgres; not a new project) → **New** → **GitHub Repo** → the same `claude-trader` repo
2. **No volume** (skip it)
3. **Variables** → **Raw Editor**, paste and fill in:
   ```
   BOT_ROLE=head
   DISCORD_BOT_TOKEN_HEAD=<the head bot's token>
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   DISCORD_GUILD_ID=<same as the ORB service>
   DISCORD_OWNER_ID=<same as the ORB service>
   DISCORD_CHANNEL_SYSTEM=<same as the ORB service>
   DISCORD_CHANNEL_DAILY_SUMMARY=<same as the ORB service>
   ```
   (`${{Postgres.DATABASE_URL}}` links the existing database; if your database service has another name, use that name. **Don't** add Alpaca keys or the ORB bot's `DISCORD_BOT_TOKEN`)
4. Optional: **Settings** → rename the service to `head-bot`
5. It deploys on its own. `#system` shows **🧭 Uri (head bot) online · watching: Orbi** (messages use each bot's Discord name)

**Deploys:** the head has no volume, so Railway starts the new copy before stopping the old one: you see "online" first, then a small grey "🔄 Uri rebooted with the new deploy" line (not a 🔴 stopped). A real stop still shows 🔴

## What it does
| | |
|---|---|
| Watchdog | Each bot writes a heartbeat every minute. A bot silent **3+ minutes** between 9:00 AM ET and 20 min after the close → @mention in `#system`; "✅ back" when it returns. The trading bots watch the head too (5 min, market hours, no effect on trading) |
| Daily summary | **The only poster in `#daily-summary`** (since 2026-11-20). Each bot hands its full 4:15 summary to the shared database instead of posting it; once every bot has reported (or at 5:00 PM ET, naming any that didn't) the head posts **one message**: one line per bot plus a fleet total once there are 2+ bots, and a **thread** under it with each bot's full summary (every signal, paper trades, costs, data check). Missed while the head was down → posted when it's back. If a bot can't reach the database, it posts its own summary so it's never lost. Needs the head's role to have **Create Public Threads** and **Send Messages in Threads** |
| `/status [bot]` | `all` (the default): every bot alive, paused, today's numbers, open trades and **money at risk across bots**. A bot's Discord name (autocompletes, e.g. `/status Orbi`, `/status Uri`): that bot's own status, as it last reported it (≤1 min old), or what the head itself is doing. Only you see the answer |
| `/pause-all` · `/resume-all` | The shared global pause: no alerts or orders from any bot. A bot's own `/pause` is separate and stays as it was |
| `/flatten-all confirm:yes` | Global pause on, then every live bot closes its own account with its own keys (within ~5 s) and answers; the head lists who did what. A bot that doesn't answer in 60 s is named so you can use its own `/flatten` |

If the head is down, nothing about trading changes: trades stay protected at Alpaca and are still sold at 3:55; each bot's own `/pause` and `/flatten` keep working.

Where it goes from here (Claude filter, enforced global limits, automatic kill switch): [step-2b-bot-fleet.md → The head bot from here](step-2b-bot-fleet.md#the-head-bot-from-here).

## Test it
1. `/status` → ORB bot 🟢
2. Stop the ORB service on Railway (Deployments → ⋮ → Remove) in the watch window → ping within ~3–4 min → **Redeploy** → "✅ back". *(Outside the window, the head only notices; the ping test needs a market day before 4:20 PM ET)*
3. `/pause-all` → ORB's heartbeat note becomes "paused (global)" in `/status` → `/resume-all`
4. `/flatten-all confirm:yes` with nothing open → "✅ ORB bot: nothing was open"; then `/resume-all`
