# Setup: run the ORB bot on Railway

About 10 minutes. After this the bot runs in the cloud, so your Mac can be off.

> **Keys go into Railway's Variables page in your browser, never into a chat.** `.env` is not on GitHub, so Railway only gets your keys when you paste them in.

**What Railway runs:** the `Dockerfile` in this repo, i.e. `python -m app run` (the Discord bot plus the scheduler). It has no website and no public URL. Everything the app saves (trade log, pause setting, signal folders, logs) goes to a **volume** mounted at `/data`, so it survives redeploys.

---

## 1. Sign in (~1 min)
1. Go to **https://railway.com** and click **Login**, then **Continue with GitHub**.
2. You're on the free trial. It gives a small one-time credit; check the current trial limits on Railway's pricing page. This app uses very little (mostly sleeping), and Hobby ($5/month) is enough when the trial ends.

## 2. Create the project from GitHub (~2 min)
1. **New Project** → **Deploy from GitHub repo**.
2. If asked, **Configure GitHub App**: give Railway access to **only** `joshstseng/claude-trader`, not all repos.
3. Pick `claude-trader`. Railway finds `railway.json` and builds with the `Dockerfile`.
4. **The first deploy will crash.** That's expected: the keys aren't there yet. Keep going.

## 3. Add the volume (~1 min)
1. On the project canvas, **right-click the service** (the `claude-trader` box) → **Attach Volume**. If you don't see that, press **⌘K** and type "volume".
2. **Mount path: `/data`** (exactly that).
3. Don't change `TRADER_STORAGE`: the Dockerfile already sets it to `/data`.

## 4. Paste your variables (~2 min)
1. Click the service → **Variables** tab → **Raw Editor**.
2. Open your local `.env` in VS Code, copy **all** of it, and paste it into the Raw Editor. It should have these 12:
   `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER` (must be `true`), `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_OWNER_ID`, `DISCORD_CHANNEL_SETUPS`, `DISCORD_CHANNEL_CLOSED_TRADES`, `DISCORD_CHANNEL_LIVE_TRADES`, `DISCORD_CHANNEL_DAILY_SUMMARY`, `DISCORD_CHANNEL_SYSTEM`, `SEC_USER_AGENT`
3. Remove the comment lines (starting with `#`) if Railway complains about them.
4. Click **Update Variables**. Railway redeploys on its own.

## 5. Check it's running (~2 min)
1. Service → **Deployments** → the newest one → **View Logs**. Within a minute you should see:
   ```
   INFO    Discord: logged in as ORB Bot#1611
   ```
   Times in Railway's logs are UTC (5 hours ahead of New York, 8 ahead of you).
2. Discord `#system` should show **🟢 ORB bot online**.
3. Try `/today` in Discord (`/status Orbi` once the head bot is set up).

**Don't** generate a public domain (Settings → Networking). The bot doesn't need one.

---

## Day-to-day

| You want to… | Do this |
|---|---|
| Deploy new code | `git push` to `main`. Railway rebuilds and restarts automatically. **Push outside 9:45–11:35 AM ET** (6:45–8:35 AM your time) so a restart doesn't land mid-scan. If one does, the bot resumes the day: no double alerts, the daily cap carries over |
| Stop alerts but keep it running | `/pause` in Discord (`/resume` to turn back on) |
| Stop the bot completely | Railway → service → Deployments → newest → **⋮** → **Remove**. `#system` shows 🔴 stopped. **Redeploy** to start again |
| See what it did | Railway → View Logs, or `/status Orbi` (head bot) and `/today` in Discord |
| Change a setting (e.g. target 1R) | Edit `config/strategies/orb.json` or `config/risk.json`, commit, push |
| See every bot at once | `/status` (head bot); the daily summary in `#daily-summary` comes from the head, each bot's detail in its thread. The head is a second service in the same project ([setup-head-bot.md](setup-head-bot.md)); a push redeploys both |
| Pause or close everything, every bot | `/pause-all` · `/resume-all` · `/flatten-all confirm:yes` (head bot). A bot's own `/pause` and `/flatten` still work, even with the head down |

## If something's wrong
- **Crashes right away with "… is not set"** → a variable is missing or misspelled in step 4.
- **"ALPACA_PAPER must be true"** → set `ALPACA_PAPER=true`. Live trading is locked until Step 5 of the roadmap.
- **Errors fetching Yahoo data (429, timeouts)** in the morning → Yahoo may be limiting Railway's servers. The bot pings you in `#system`. Tell Claude: the fix is switching market data to Alpaca (planned for Step 1b, can move earlier).
- **Two 🟢 online messages and double alerts** → the bot is also running on your Mac. Stop the Mac copy.
