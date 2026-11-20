# Snap on paper: plan

How Snap ([snap-strategy.md](snap-strategy.md)) becomes a paper-trading bot next to Orbi, Uri and Brix. Written 2026-11-20. **This is a plan only; nothing has been built or turned on.**

> Keys and tokens go into Railway's Variables page and your local `.env`, never into a chat.

## The key choice: decide after the close, trade at the open
The backtest fills at the close, which live would need a market-on-close order sent minutes before the bell, using a price that isn't final yet. Instead:

1. **After the close** (about 4:15 PM ET), Snap reads the day's final bars and decides what to buy and sell.
2. **Before the next open,** it sends **market-on-open orders**. Alpaca supports these (`time_in_force=opg`).

This variant passes the same bar on its own:

| | Profit factor | Total |
|---|---|---|
| 2021–2023 | 1.65 | +$8.0k |
| **2024–2026** | **2.02** | **+$11.9k** |
| 2016–2020 | 1.41 | +$8.7k |

The worst drawdown is −$1.9k. It's slightly less profit than filling at the close, but the decisions are made on final data, with no race against the bell. The backtest switches to this variant, so live and backtest stay identical.

## What's different from Orbi (shared code to extend)
Orbi is a day trader: one check window, a 3:55 PM sell, every trade closed the same day. Snap holds for days, so the shared plumbing needs a **swing mode**. This is new code paths, switched on only for Snap:

| Area | Orbi today | Snap needs |
|---|---|---|
| Schedule | pre-market scan plus intraday checks | one run after the close (about 4:15 PM ET) on NYSE days |
| Orders | bracket orders, filled intraday | market-on-open entry plus a resting GTC stop; market-on-open exit |
| 3:55 PM sell | always | **off** for Snap (it holds overnight) |
| Trade log, cards | open and close the same day | positions stay open across days; the live card shows days held |
| Daily summary | Orbi's day | Snap's line shows open positions, plus any trades closed that day |
| Restart safety | flat every night | on restart, re-reads its open positions and stops from Alpaca |

Orbi's code paths stay as they are. The usual regression checks apply: full tests, an exact baseline rerun, a live smoke test and a clean deploy.

## Stages
| Stage | What Snap does | Gate to the next stage |
|---|---|---|
| **P1. Join Discord** | its own Discord bot, **Snap**; its backtests post under its name | — |
| **P2. Shadow** | runs every evening on Railway and posts what it *would* do (👻 shadow), with simulated fills at the next open | 2 clean weeks; the shadow trades match a backtest of the same days |
| **P3. Paper** | its own **Alpaca paper margin account**, real paper orders | a month clean, then review |

## You (when we get there)
1. **Create the Discord bot "Snap"** (about 5 minutes, same steps as [add-a-bot.md](add-a-bot.md)), then put `DISCORD_BOT_TOKEN_SNAP` in `.env`.
2. **Create a new Alpaca paper account** with **margin** (all 4 ETFs at once can use about $103k of buying power).
3. **Create a new Railway service** with the same repo, a `/data` volume and `STRATEGY=snap`.

## Decided (2026-11-20)
1. **Trade at the next open.** The user said "whichever is better". The two are about even on paper, but this version is what Snap can actually do live, so it's now Snap's default (baseline **run #75**: 721 trades, +$29.0k, a profit factor of 1.67).
2. **1% risk a trade** for now; it can change later.
3. **No Discord bot yet:** the user isn't at a computer. P1 waits until they are.
