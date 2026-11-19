# Adding a strategy bot

For Step 2b.6, once a strategy has earned its own bot in the backtest. Part of [step-2b-bot-fleet.md](step-2b-bot-fleet.md). About 20 minutes of setup, plus the strategy's code.

Every bot runs the **same code**. What makes it a different bot: its strategy (`STRATEGY`), its own Discord bot, its own Alpaca paper account, and its own Railway service. It posts to the **same channels** as the ORB bot, under its own name.

> Keys and tokens go into Railway's Variables page and your local `.env`, never into a chat.

---

## 1. The strategy (Claude does this)
- A brain in `app/strategies/<id>.py` (see [app/strategies/base.py](../app/strategies/base.py) for the contract and `orb.py` / `demo.py` for examples), listed in `BRAINS` in `app/strategies/__init__.py`
- Its settings in `config/strategies/<id>.json` (`"enabled": true` when it should run)
- Backtested with `python -m app backtest --strategy <id> …` until it passes its gate

## 2. A Discord bot for it (you, ~5 min)
Same steps as the ORB bot (see [setup-alpaca-discord.md](setup-alpaca-discord.md), part B3–B4):
1. **discord.com/developers/applications** → **New Application** → name it, e.g. `VWAP Bot`
2. **Bot** → **Reset Token** → copy it (it goes into Railway, step 4). Turn off "Public Bot"
3. **OAuth2 → URL Generator** → scopes **bot** + **applications.commands**; permissions **View Channels, Send Messages, Embed Links, Read Message History, Use Slash Commands** → open the link → add it to your `claude-trader` server
4. Optional, on your Mac: add `DISCORD_BOT_TOKEN_<ID>=<token>` to `.env` (e.g. `DISCORD_BOT_TOKEN_VWAP`), so its backtests post under its own name in `#backtests`

## 3. An Alpaca paper account for it (you, ~3 min)
1. **app.alpaca.markets** → account switcher (top left) → **create a new paper account**
2. Switch to it → **API Keys** → **Generate New Keys** → copy both (they go into Railway, step 4)

Its own account means its trades never mix with another bot's, and the 3:55 PM sell only touches its own positions.

## 4. A Railway service for it (you, ~10 min)
1. In your Railway project → **New** → **GitHub Repo** → the same `claude-trader` repo
2. **Attach a volume** at `/data` (each bot keeps its own disk)
3. **Variables** (Raw Editor): copy the ORB service's variables, then change these:
   ```
   STRATEGY=<id>                      # e.g. vwap
   DISCORD_BOT_TOKEN=<the new bot's token>
   ALPACA_API_KEY=<the new paper account's key>
   ALPACA_SECRET_KEY=<the new paper account's secret>
   ```
   Keep everything else the same: `ALPACA_PAPER=true`, the server id, your user id, and **the same channel ids** (all bots share the channels)
4. It deploys on its own. Check `#system` for its 🟢 online message, under the new bot's name

## 5. Then
- It runs its own 1a/1b-style live gates (a clean week of alerts, then paper trading)
- The head bot (2b.4) picks it up automatically from its first heartbeat: watchdog, fleet summary, `/fleet`, `/pause-all`, `/flatten-all`. Nothing to set up on the head

## What keeps bots apart (built in 2b.2)
| Thing | How it's kept separate |
|---|---|
| Trade log, pause setting, day account, live cards, logs, single-copy lock | Each bot's own folder (`/data` on its own volume; the ORB bot keeps the original layout, any other bot uses `bots/<id>/`) |
| Orders | Each bot's own Alpaca paper account; order ids start with the strategy id (`orb-…`, `vwap-…`) |
| Discord buttons and commands | Each Discord bot only receives taps and commands on its own messages |
| Shared on purpose | The channels, the market data cache and stock list, and backtest runs (tagged by strategy) |
