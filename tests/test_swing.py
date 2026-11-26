import tempfile
import unittest
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app import head, swing_live as L
from app.market import Session
from app.strategies.swing import BARS, Machine, context, update_fvg

NY = ZoneInfo("America/New_York")
S = L.load_settings()
DAY = date(2026, 11, 23)


def ctx(sigma=.002):
    return {"prev": 100.0, "vol": .01, "weight": 1.0, "sigma": [sigma] * BARS, "candles": [], "lo": None, "hi": None}


def path(points):
    """Piecewise-flat closes: {first bar: price}."""
    c = np.zeros(BARS); now = 100.0
    for b in range(BARS):
        now = points.get(b, now); c[b] = now
    o = np.r_[100.0, c[:-1]]
    return o, np.maximum(o, c) + .01, np.minimum(o, c) - .01, c


def run(points, fvg=True, ct=None):
    O, H, L_, C = path(points); m = Machine.start(ct or ctx(), 100.0, fvg); seen = []
    for b in range(BARS):
        if m.step(b, O, H, L_, C):
            seen.append((b, m.side))
    return m, seen


class Rules(unittest.TestCase):
    def test_long_at_a_30m_check_only(self):
        _, seen = run({3: 101.0})
        self.assertEqual(seen[0], (5, 1))

    def test_inside_band_exits_at_next_check(self):
        _, seen = run({3: 101.0, 7: 100.0})
        self.assertEqual(seen[:2], [(5, 1), (11, 0)])

    def test_flip_at_opposite_band(self):
        _, seen = run({3: 101.0, 7: 99.0})
        self.assertEqual(seen[:2], [(5, 1), (11, -1)])

    def test_always_flat_at_close(self):
        m, seen = run({3: 101.0})
        self.assertEqual((m.side, m.held, seen[-1]), (0, 0, (77, 0)))

    def test_fvg_detection_and_no_broken_gap(self):
        c, lo, hi = update_fvg([[10, 9], [11, 10]], None, None, 13, 12, 12.5)
        self.assertEqual((lo, hi, len(c)), (10, None, 3))
        _, lo, hi = update_fvg([[10, 9], [8, 7]], None, None, 6, 5, 5.5)
        self.assertEqual((lo, hi), (None, 9))

    def test_fvg_exit_beats_the_30m_check_and_blocks_same_side(self):
        cx = {**ctx(), "lo": 100.9}
        _, seen = run({0: 100.6, 3: 101.0, 7: 100.5, 12: 101.0}, ct=cx)   # the pullback forms no newer gap
        self.assertEqual(seen[:2], [(5, 1), (8, 0)])     # 15m close at bar 8, before the bar 11 check
        self.assertNotIn((11, 1), seen)

    def test_v1_ignores_fvg(self):
        _, seen = run({0: 100.6, 3: 101.0, 7: 100.5}, fvg=False, ct={**ctx(), "lo": 100.9})
        self.assertEqual(seen[:2], [(5, 1), (77, 0)])    # still above the band, so v1 holds to the close

    def test_changing_future_bars_never_changes_past_decisions(self):
        O, H, L_, C = path({3: 101.0}); a = Machine.start(ctx(), 100.0, True); b = Machine.start(ctx(), 100.0, True)
        O2, H2, L2, C2 = (x.copy() for x in (O, H, L_, C)); C2[30:] = 50; O2[30:] = 50; H2[30:] = 50; L2[30:] = 50
        for k in range(30):
            a.step(k, O, H, L_, C); b.step(k, O2, H2, L2, C2)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_context_uses_prior_sessions(self):
        r = np.random.default_rng(1); C = 100 + r.normal(0, .1, (30, BARS)).cumsum(axis=1); O = C - .01; x = context(O, C + .1, C - .1, C)
        self.assertEqual(x["prev"], C[-1, -1])
        self.assertLessEqual(x["weight"], 2.0)


class Cal:
    def __init__(self, close=dtime(16, 0)):
        self.close = close

    def session(self, d):
        return Session(d, dtime(9, 30), self.close) if d.weekday() < 5 else None


class Broker:
    def __init__(self):
        self.pos, self.orders, self.sent, self.closed, self.fill = 0, {}, [], False, True
        self.px, self.stops, self.down = 101.0, {}, False

    def position(self):
        if self.down:
            raise ConnectionError("alpaca down")
        return self.pos, self.px

    def order(self, cid):
        return self.orders.get(cid) or self.stops.get(cid)

    def place_stop(self, side, qty, price, cid):
        self.stops[cid] = {"status": "new", "side": side, "qty": qty, "price": price, "filled_qty": 0, "filled_price": None}
        return "new"

    def cancel(self, cid):
        st = self.stops.get(cid)
        if st and st["status"] == "new":
            st["status"] = "canceled"
        return st["status"] if st else "missing"

    def live_stops(self):
        return [x for x in self.stops.values() if x["status"] == "new"]

    def fire_stop(self):
        st = self.live_stops()[0]
        st.update(status="filled", filled_qty=st["qty"], filled_price=st["price"])
        self.pos += st["qty"] if st["side"] == "buy" else -st["qty"]

    def submit(self, side, qty, cid):
        if cid in self.orders:
            raise ValueError("duplicate")
        self.sent.append((side, qty, cid))
        status = "filled" if self.fill else "new"
        self.orders[cid] = {"status": status, "filled_qty": qty if self.fill else 0, "filled_price": 101.0 if self.fill else None}
        if self.fill:
            self.pos += qty if side == "buy" else -qty
        return status

    def close_all(self):
        self.closed = True; self.pos = 0
        for x in self.live_stops():
            x["status"] = "canceled"


def rows_for(points, through):
    O, H, L_, C = path(points); start = datetime(DAY.year, DAY.month, DAY.day, 9, 30, tzinfo=NY)
    return [(start + timedelta(minutes=5 * b), O[b], H[b], L_[b], C[b]) for b in range(through + 1)]


class Live(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.file = Path(t.name) / "s.json"; self.state = L.State(self.file); self.broker = Broker(); self.posts, self.reports = [], []
        self.pause = False; self.points = {3: 101.0}; self.now = None

    def routine(self, mode="paper", cal=None, state=None):
        r = np.random.default_rng(2); C = 100 + r.normal(0, .05, (30, BARS)).cumsum(axis=1); O = C - .01
        days = pd.bdate_range(end="2026-11-20", periods=30)

        def today(d):
            done = L.last_done_bar(self.now, Session(d, dtime(9, 30), dtime(16, 0)))
            return rows_for(self.points, done)
        return L.Routine(S, state or self.state, cal or Cal(), self.broker, lambda d: (days, O, C + .1, C - .1, C), today,
                         lambda w, x, p: self.posts.append(x), lambda d, x: self.reports.append(x), lambda: self.pause, mode)

    def at(self, r, h, m, s=5):
        self.now = datetime(DAY.year, DAY.month, DAY.day, h, m, s, tzinfo=NY).astimezone(timezone.utc); r.tick(self.now)

    def force(self, r):
        rec = self.state.day(DAY.isoformat())
        rec["context"] = {**rec["context"], "prev": 100.0, "sigma": [.002] * BARS, "lo": None, "hi": None, "candles": [], "weight": 1.0}
        self.state.save()

    def test_paper_enters_once_then_flat_by_the_close(self):
        r = self.routine(); self.at(r, 9, 1); self.force(r); self.at(r, 10, 0); self.at(r, 10, 0, 15); self.at(r, 10, 0, 25)
        self.assertEqual([x[0] for x in self.broker.sent], ["buy"])
        self.assertEqual(self.broker.sent[0][1], 990)    # $100k x 1.0 / $101, whole shares
        self.at(r, 15, 58, 50)
        self.assertEqual(self.broker.pos, 0)
        self.assertEqual(self.broker.sent[-1][0], "sell")
        self.at(r, 15, 58, 55)                           # fills are booked on the next tick
        self.assertEqual(len(self.state.ledger["closed"]), 1)

    def test_shadow_never_sends(self):
        r = self.routine("shadow"); self.at(r, 9, 1); self.force(r); self.at(r, 10, 0); self.at(r, 15, 59)
        self.assertEqual(self.broker.sent, [])

    def test_paused_skips_entry_but_exits_still_run(self):
        r = self.routine(); self.at(r, 9, 1); self.force(r); self.pause = True; self.at(r, 10, 0); self.assertEqual(self.broker.sent, [])
        self.pause = False; self.at(r, 10, 0, 30); self.assertEqual(self.broker.sent, [])
        self.broker.pos = 0
        r2 = self.routine(); self.state.day(DAY.isoformat())["missed"] = -1; self.state.day(DAY.isoformat())["done_bar"] = 5
        self.at(r2, 10, 1); self.assertEqual(len(self.broker.sent), 1); self.pause = True; self.at(r2, 15, 58, 50); self.assertEqual(self.broker.pos, 0)

    def test_stale_signal_is_not_entered_after_restart(self):
        r = self.routine("shadow"); self.at(r, 9, 1); self.force(r); self.at(r, 10, 0)
        self.at(r, 10, 30); r2 = self.routine("paper", state=L.State(self.file)); self.state = r2.state
        self.at(r2, 10, 30, 20)
        self.assertEqual(self.broker.sent, [])

    def test_restart_does_not_duplicate_a_pending_order(self):
        self.broker.fill = False; r = self.routine(); self.at(r, 9, 1); self.force(r); self.at(r, 10, 0)
        r2 = self.routine(state=L.State(self.file)); self.state = r2.state; self.at(r2, 10, 0, 15)
        self.assertEqual(len(self.broker.sent), 1)

    def test_early_close_is_a_day_off(self):
        r = self.routine(cal=Cal(dtime(13, 0))); self.at(r, 9, 1); self.at(r, 10, 0)
        self.assertEqual(self.broker.sent, [])
        self.assertTrue(any("shortened" in x for x in self.posts))

    def test_flatten_halts_the_day(self):
        r = self.routine(); self.at(r, 9, 1); self.force(r); self.at(r, 10, 0); r.flatten(DAY.isoformat()); n = len(self.broker.sent); self.at(r, 10, 30)
        self.assertTrue(self.broker.closed)
        self.assertEqual(len(self.broker.sent), n)

    def test_short_pnl_and_numbers(self):
        r = self.routine(); r.book("sell", 10, 100.0, "2026-11-23", datetime(2026, 11, 23, 15, tzinfo=NY), "x"); r.book("buy", 10, 99.0, "2026-11-23", datetime(2026, 11, 23, 15, 5, tzinfo=NY), "y")
        n = L.numbers(self.state)
        self.assertEqual((n["all_time"], n["all_trades"], n["open"]), (10.0, 1, 0))

    def test_summary_compares_paper_with_models(self):
        r = self.routine(); self.at(r, 9, 1); self.force(r); self.at(r, 10, 0); self.at(r, 15, 58, 50); self.at(r, 16, 6)
        self.assertIn("Model v1 baseline", self.reports[-1])


class Fleet(unittest.TestCase):
    def test_uri_treats_swing_as_intraday_and_keeps_bumi(self):
        class Log:
            def fleet(self, k):
                return '{"open": 1, "days": {}}'
        self.assertIn("swing", head.OWN_LEDGER_BOTS)
        self.assertIn("bumi", head.OWN_LEDGER_BOTS)
        self.assertFalse(head.own_ledger_numbers(Log(), "swing", "2026-11-23")["swing"])
        self.assertTrue(head.own_ledger_numbers(Log(), "bumi", "2026-11-23")["swing"])


class Morning(Live):
    def test_one_card_after_the_first_bar_and_it_never_blocks_trading(self):
        r = self.routine(); self.at(r, 9, 1); self.force(r); self.at(r, 9, 35); self.at(r, 9, 40)
        cards = [x for x in self.posts if "Swing's rundown" in x]
        self.assertEqual(len(cards), 1)
        self.assertIn("long above", cards[0]); self.assertIn("short below", cards[0]); self.assertIn("shares", cards[0])
        self.assertEqual(self.broker.sent, [])

    def test_a_failed_card_does_not_stop_the_day(self):
        r = self.routine(); self.at(r, 9, 1); self.force(r)
        good = r.post

        def flaky(where, text, ping):
            if where == "setups":
                raise RuntimeError("discord down")
            good(where, text, ping)
        r.post = flaky
        self.at(r, 9, 35); self.at(r, 10, 0); self.at(r, 10, 0, 15)
        self.assertEqual([x[0] for x in self.broker.sent], ["buy"])

    def test_no_late_card_after_a_restart_past_ten(self):
        r = self.routine(); self.at(r, 9, 1); self.force(r); self.at(r, 10, 5)
        self.assertFalse([x for x in self.posts if "Swing's rundown" in x])

    def test_preview_posts_saved_levels_and_sends_no_orders(self):
        r = self.routine(); self.assertEqual(r.morning_preview(DAY.isoformat()), f"no levels saved for {DAY.isoformat()}")
        self.at(r, 9, 1); self.force(r); self.at(r, 9, 35); self.posts.clear()
        self.assertEqual(r.morning_preview(DAY.isoformat()), "posted the morning card preview")
        self.assertIn("Preview of this morning's card", self.posts[0])
        self.assertEqual(self.broker.sent, [])

    def test_the_line_matches_the_open(self):
        m = {"up": [0] * 5 + [503.0], "down": [0] * 5 + [497.0], "weight": 1.0}
        self.assertIn("$503.00", L.morning_text("2026-11-24", "QQQ", 503.0, m, 498.0, 100000).split("short")[0])
        wild = L.morning_text("2026-11-24", "QQQ", 500.0, {**m, "weight": .5}, 500.0, 100000)
        self.assertTrue(any(x in wild for x in L.MORNING_LINES["wild"]))
        self.assertIn("**100 shares**", wild)


class Safety(Live):
    """The five safety nets (config "risk"). Entry: 990 sh at $101 (see test_paper_enters_once_then_flat_by_the_close)."""

    def entered(self):
        r = self.routine(); self.at(r, 9, 1); self.force(r); self.at(r, 10, 0); self.at(r, 10, 0, 10); self.at(r, 10, 0, 15)
        self.assertEqual(self.broker.pos, 990)
        return r

    def test_every_position_gets_one_emergency_stop_at_a_2_5_pct_account_loss(self):
        r = self.entered(); self.at(r, 10, 0, 20)
        stops = self.broker.live_stops()
        self.assertEqual(len(stops), 1)
        self.assertEqual((stops[0]["side"], stops[0]["qty"], stops[0]["price"]), ("sell", 990, round(101 - 2500 / 990, 2)))

    def test_the_stop_is_cancelled_before_the_normal_exit(self):
        r = self.entered(); self.at(r, 15, 58, 50); self.at(r, 15, 58, 55)
        self.assertEqual(self.broker.pos, 0)
        self.assertEqual(self.broker.live_stops(), [])
        self.assertIsNone(self.state.ledger.get("stop"))

    def test_a_filled_emergency_stop_is_booked_and_ends_the_day(self):
        r = self.entered(); self.broker.fire_stop(); self.at(r, 10, 5)
        self.assertEqual(self.state.ledger["closed"][-1]["why"], "emergency stop")
        self.assertTrue(self.state.day(DAY.isoformat())["halted"])
        n = len(self.broker.sent); self.at(r, 10, 30); self.at(r, 11, 0)
        self.assertEqual(len(self.broker.sent), n)                      # no new entries after it fired

    def test_daily_loss_limit_exits_and_stops_for_the_day(self):
        r = self.entered(); self.broker.px = 101 - 3001 / 990           # open loss just past -$3,000
        self.at(r, 10, 5); self.at(r, 10, 5, 10)
        self.assertIn("daily loss limit", self.state.day(DAY.isoformat())["halt_why"])
        self.assertEqual(self.broker.pos, 0)
        self.assertEqual(self.broker.live_stops(), [])

    def test_a_position_over_the_cap_is_closed_and_the_day_halted(self):
        r = self.entered(); self.broker.pos = 5000; self.at(r, 10, 5)
        self.assertTrue(self.broker.closed)
        self.assertIn("cap", self.state.day(DAY.isoformat())["halt_why"])

    def test_backup_close_out_at_3_59_30_if_the_exit_didnt_fill(self):
        r = self.entered(); self.broker.fill = False; self.at(r, 15, 58, 50)
        self.assertEqual(self.broker.pos, 990)                          # exit sent but not filled
        self.at(r, 15, 59, 31)
        self.assertTrue(self.broker.closed); self.assertEqual(self.broker.pos, 0)
        self.assertTrue(any("closed everything" in x for x in self.posts))
        self.at(r, 15, 59, 40)
        self.assertEqual(self.state.ledger["closed"][-1]["why"], "backup close-out (estimated price)")

    def test_three_minutes_blind_in_a_trade_exits_and_entries_wait_for_data(self):
        r = self.entered(); self.at(r, 10, 0, 20)

        def down(d):
            raise ConnectionError("feed down")
        good, r.today = r.today, down
        self.at(r, 10, 5, 5); self.assertEqual(self.broker.pos, 990)    # blind, but under 3 minutes
        self.at(r, 10, 8, 10); self.at(r, 10, 8, 15)
        self.assertEqual(self.broker.pos, 0)
        self.assertEqual(self.state.ledger["closed"][-1]["why"], "data outage")
        n = len(self.broker.sent); self.at(r, 10, 30, 5)
        self.assertEqual(len(self.broker.sent), n)                      # no entries while blind
        r.today = good; self.at(r, 10, 31)
        self.assertTrue(any("bars are loading again" in x for x in self.posts))
        self.assertFalse(self.state.day(DAY.isoformat()).get("blind_exit"))

    def test_three_outages_end_the_day(self):
        r = self.routine(); self.at(r, 9, 1); self.force(r)
        good = r.today

        def down(d):
            raise ConnectionError("feed down")
        for m in (35, 45, 55):
            r.today = down; self.at(r, 9, m, 5)
            r.today = good; self.at(r, 9, m + 1)
        self.assertIn("outages", self.state.day(DAY.isoformat())["halt_why"])

    def test_alpaca_down_warns_once_and_keeps_the_stop(self):
        r = self.entered(); self.at(r, 10, 0, 20); self.broker.down = True
        self.at(r, 10, 1); self.at(r, 10, 2, 5); self.at(r, 10, 3)
        self.assertEqual(sum("can't reach Alpaca" in x for x in self.posts), 1)
        self.assertEqual(len(self.broker.live_stops()), 1)
        self.broker.down = False; self.at(r, 10, 4)
        self.assertTrue(any("reachable again" in x for x in self.posts))


class FrozenFeed(Live):
    """The feed answers but stops sending bars: same disconnect rule, one @mention with Close now when in a trade."""

    def entered(self):
        r = self.routine(); self.alerts = []
        r.alert = lambda text, button, day: self.alerts.append((text, button, day))
        self.at(r, 9, 1); self.force(r); self.at(r, 10, 0); self.at(r, 10, 0, 10); self.at(r, 10, 0, 20)
        self.assertEqual(self.broker.pos, 990)
        return r

    def freeze(self, r, through):
        good = r.today
        r.today = lambda d: [x for x in good(d) if (x[0].astimezone(NY).hour * 60 + x[0].astimezone(NY).minute - 570) // 5 <= through]
        return good

    def test_frozen_bars_alert_then_close_after_three_minutes(self):
        r = self.entered(); good = self.freeze(r, 6)                     # last real bar closes 10:05
        self.at(r, 10, 10, 50)                                          # one bar late: filled in, no alert
        self.assertEqual(self.alerts, [])
        self.at(r, 10, 15, 50)                                          # two bars missing: frozen
        self.assertEqual(len(self.alerts), 1)
        text, button, day = self.alerts[0]
        self.assertIn("live price bars stopped loading", text); self.assertIn("still answering", text)
        self.assertIn("long 990 QQQ · **closing automatically in 3 minutes**", text)
        self.assertIn("emergency stop at $", text)
        self.assertTrue(button); self.assertEqual(day, DAY.isoformat())
        self.at(r, 10, 17, 0); self.assertEqual(self.broker.pos, 990)  # still inside the 3 minutes
        self.at(r, 10, 19, 0); self.at(r, 10, 19, 5)
        self.assertEqual(self.broker.pos, 0)
        self.assertEqual(self.state.ledger["closed"][-1]["why"], "data outage")
        self.assertEqual(len(self.alerts), 1)                           # one alert per outage
        r.today = good; self.at(r, 10, 31)
        self.assertTrue(any("bars are loading again" in x for x in self.posts))

    def test_close_now_exits_at_once(self):
        r = self.entered(); self.freeze(r, 6); self.at(r, 10, 15, 50)
        self.assertEqual(r.request_close(DAY.isoformat()), "Closing now. Swing will confirm in #system.")
        self.at(r, 10, 15, 55); self.at(r, 10, 16, 0)
        self.assertEqual(self.broker.pos, 0)
        self.assertEqual(self.state.ledger["closed"][-1]["why"], "data outage (closed by you)")
        self.assertIn("nothing to close", r.request_close(DAY.isoformat()))

    def test_close_now_after_bars_return_does_nothing(self):
        r = self.entered()
        self.assertIn("Nothing to do", r.request_close(DAY.isoformat()))

    def test_not_in_a_trade_no_button(self):
        r = self.routine(); self.alerts = []
        r.alert = lambda text, button, day: self.alerts.append((text, button, day))
        self.at(r, 9, 1); self.force(r)
        self.points = {}                                                # no breakout, so no trade
        self.freeze(r, 6); self.at(r, 10, 15, 50)
        text, button, _ = self.alerts[0]
        self.assertIn("Not in a trade, so there's nothing to close", text)
        self.assertFalse(button)

    def test_feed_errors_use_the_same_alert(self):
        r = self.entered()

        def down(d):
            raise ConnectionError("feed down")
        r.today = down; self.at(r, 10, 5, 5)
        text, button, _ = self.alerts[0]
        self.assertIn("live price bars aren't loading", text); self.assertIn("can't reach the live data feed (ConnectionError)", text)
        self.assertTrue(button)


class DailyRecord(Live):
    def test_record_compares_each_fill_with_the_models_price(self):
        got = []
        r = self.routine(); r.publish = lambda d, x: got.append((d, x))
        self.at(r, 9, 1); self.force(r); self.at(r, 10, 0); self.at(r, 10, 0, 10)
        self.at(r, 15, 58, 50); self.at(r, 15, 58, 55); self.at(r, 16, 6)
        self.assertEqual(len(got), 1)
        d, x = got[0]
        self.assertEqual(d, DAY.isoformat())
        self.assertEqual((x["paper_trades"], x["flat_after_close"], x["halt_why"]), (1, True, None))
        self.assertEqual([f["side"] for f in x["fills"]], ["buy", "sell"])
        self.assertTrue(all(f["model_px"] and f["slip_bp"] is not None for f in x["fills"]))
        self.assertEqual(len(x["trades"]), 1)
        self.assertEqual((x["symbol"], x["trades"][0]["side"]), ("QQQ", 1))

    def test_backfill_publishes_only_missing_finished_days(self):
        got = []
        r = self.routine(); self.at(r, 9, 1); self.force(r); self.at(r, 10, 0); self.at(r, 10, 0, 10)
        self.at(r, 15, 58, 50); self.at(r, 15, 58, 55); self.at(r, 16, 6)               # no publisher yet: nothing saved
        r.publish = lambda d, x: got.append(d)
        self.assertEqual(r.backfill(set()), 1)
        self.assertEqual(got, [DAY.isoformat()])
        self.assertEqual(r.backfill({DAY.isoformat()}), 1 - 1)

    def test_day_rows_keep_only_that_day(self):
        r = self.routine(); self.now = datetime(DAY.year, DAY.month, DAY.day, 16, 30, tzinfo=NY)
        later = [(t + timedelta(days=1), *x) for t, *x in rows_for(self.points, 77)]
        r.today = lambda d: rows_for(self.points, 77) + later
        self.assertEqual(len(r.day_rows(DAY.isoformat())), 78)

    def test_shortened_day_publishes_an_off_record(self):
        got = []
        r = self.routine(cal=Cal(dtime(13, 0))); r.publish = lambda d, x: got.append(x)
        self.at(r, 9, 1); self.at(r, 16, 6)
        self.assertEqual(got[0]["off"], "shortened session")


class Pings(unittest.TestCase):
    trade = {"day": "2026-11-23", "side": 1, "qty": 10, "entry": 100.0, "exit": 101.0, "pnl": 10.0,
             "time_in": "10:05:00", "time_out": "11:00:00", "why": "back inside the band"}

    def test_live_and_closed_cards_mention_the_owner(self):
        self.assertEqual(L.live_ping({"side": -1}, "QQQ", 7), "<@7> 🟢 **QQQ SHORT** · new trade")
        head_line, body, _ = L.closed_message(self.trade, "QQQ", 7)
        self.assertEqual(head_line, "<@7> ✅ **QQQ LONG** · **+$10.00** (+1.00%)")
        self.assertNotIn("<@", body)
        self.assertIn("Exit: back inside the band", body)
        self.assertIn("10:05 AM → 11:00 AM ET · held 55m", body)

    def test_live_card_shows_pnl_and_the_exit_levels(self):
        from datetime import datetime
        lot = {"side": 1, "qty": 120, "entry": 638.10, "time": "10:05:12", "why": "breakout above the band"}
        rec = {"done_bar": 13, "v11": {"side": 1, "up": [637.0] * 78, "down": [630.0] * 78, "lo": 635.5, "hi": None}}
        title, body, color = L.live_text(lot, "QQQ", 639.10, rec, datetime(2026, 11, 25, 11, 20, tzinfo=L.NY))
        self.assertEqual(title, "🟢 QQQ LONG · +$120.00 (+0.16%)")
        self.assertIn("**120 sh** · in **$638.10** at 10:05 AM · now **$639.10**", body)
        self.assertIn("Band exit  $637.00", body); self.assertIn("11:00 AM check", body)
        self.assertIn("FVG exit   $635.50", body); self.assertIn("Flat by    3:58 PM", body)
        self.assertEqual(color, 0x2ECC71)
        self.assertEqual(L.live_text(lot, "QQQ", None)[0], "⚪ QQQ LONG · price unavailable")

    def test_unping_only_edits_that_days_cards_and_is_repeatable(self):
        import asyncio
        from app.swing_run import unping_cards

        class Msg:
            def __init__(self, content):
                self.content, self.edits = content, 0

            async def edit(self, content):
                self.content, self.edits = content, self.edits + 1

        class Channel:
            def __init__(self):
                self.msgs = {1: Msg("<@7> ✅ today"), 2: Msg("<@7> ❌ yesterday")}

            async def fetch_message(self, i):
                return self.msgs[i]

        ch = Channel()
        trades = [{"day": "2026-11-23", "closed_card": "1"}, {"day": "2026-11-20", "closed_card": "2"},
                  {"day": "2026-11-23"}]
        self.assertEqual(asyncio.run(unping_cards(ch, trades, "2026-11-23")), 1)
        self.assertEqual(ch.msgs[1].content, "✅ today")
        self.assertEqual(ch.msgs[2].content, "<@7> ❌ yesterday")
        self.assertEqual(asyncio.run(unping_cards(ch, trades, "2026-11-23")), 0)
        self.assertEqual(ch.msgs[1].edits, 1)


if __name__ == "__main__":
    unittest.main()
