# Head bot: per-bot hours and session roll calls

For Uri (the head bot), needed before a bot that trades outside US stock hours (Mr. S, [mrs-strategy.md](mrs-strategy.md)). **Plan only, not built yet.**

## Why
Today Uri assumes every bot keeps NYSE hours:
- the **watchdog** only watches from 9:00 AM ET to 20 minutes after the close, so a bot trading 7 PM–1 AM ET would go unwatched
- the **daily summary** waits for reports after 4:15 PM ET, but Mr. S's "day" ends at 10:00 PM PT (1 AM ET)

## 1. Each bot says its hours
Each bot puts its sessions in its heartbeat (new column `sessions`, like `name` and `status`), from its config:
```
Orbi:  NYAM 9:30 AM–4:00 PM ET, Mon–Fri on NYSE days
Mr. S: Asia 4:00–10:00 PM PT, Sun–Thu on CME days
```
Uri reads them, so a new bot needs no change to Uri. A bot that doesn't send hours is treated as NYSE hours (the ORB bot until it's updated).

## 2. The watchdog per bot
A bot is watched from 30 minutes before its session to 20 minutes after it, with the same rules as now (3 minutes silent → @mention once, "✅ back" when it returns). Outside its hours, a silent bot is only shown in `/status`.

## 3. Roll calls at each session start and end
At each session's start, Uri checks each bot of that session (heartbeat under 2 minutes old, not paused, no errors) and posts one line to `#system`:

> ☀️ **Good morning! NYAM session.** Orbi, A, B and C are awake and trading.

> 🌏 **Asia session start.** Mr. S and Y are up and actively trading.

A problem is named, with an @mention:

> 🌏 **Asia session start.** Mr. S is up and trading · ⚠️ **Y** hasn't checked in for 6 min

> ☀️ **NYAM session.** Orbi is up but **paused** (its own /pause)

At the end, a short line with that session's numbers:

> 🌙 **Asia session done.** Mr. S: 2 trades · +1.6R · +$410 · all flat

Like the "No live trades" lines, the opening wording can vary a little each day.

## 4. The daily summary
Uri posts when every bot whose **day has ended** has reported. Mr. S's night (e.g. Thursday 4–10 PM PT) counts toward **Friday**'s summary, since it ends after the Thursday summary has posted. Each bot's day is labelled with its session (e.g. "Mr. S · Asia, Thu night").

## 5. Tests
- The watchdog doesn't ping for a bot outside its hours and does inside them
- One roll call per session (a restart doesn't repeat it, remembered in the database), with the right bots named
- The summary waits for a night bot's report and counts it on the right day

**Done when:** with a fake Asia bot's heartbeats, Uri posts the Asia roll calls, watches it only in its hours, and the ORB bot's behaviour is unchanged (the usual [regression checks](step-2b-bot-fleet.md)).
