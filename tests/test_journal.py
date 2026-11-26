"""/journal: every bot's daily records become two CSV files."""
import csv
import io
import json
import unittest

from app import journal

SWING = {"day": "2026-11-25", "symbol": "QQQ", "model_pnl": 3.0,
         "trades": [{"side": -1, "qty": 51, "entry": 610.66, "exit": 610.44, "pnl": 11.07, "time_in": "10:30:04",
                     "time_out": "11:00:05", "why": "back inside the band"}],
         "fills": [{"day": "2026-11-25", "time": "10:30:04", "side": "sell", "qty": 51, "price": 610.66, "model_px": 610.70, "slip_bp": 0.66},
                   {"day": "2026-11-25", "time": "11:00:05", "side": "buy", "qty": 51, "price": 610.44, "model_px": 610.40, "slip_bp": 0.66}]}
BUMI = {"day": "2026-12-09", "trades": [{"sym": "QLD", "qty": 10, "entry": 100.0, "exit": 108.0, "pnl": 80.0, "day_in": "2026-12-01",
                                         "day_out": "2026-12-09", "kind": "dip", "why": "QQQ stop or time exit"}],
        "fills": [{"sym": "QLD", "side": "sell", "qty": 10, "price": 108.0, "open": 107.95, "slip_bp": -4.63, "why": "QQQ stop or time exit"}]}
PAIRS = [("daily:swing:2026-11-25", json.dumps(SWING)), ("daily:bumi:2026-12-09", json.dumps(BUMI)), ("weekly:2026-12-04", "posted"),
         ("daily:swing:bad", "not json")]


def read(b):
    return list(csv.DictReader(io.StringIO(b.decode())))


class Journal(unittest.TestCase):
    def test_all_bots(self):
        trades, fills, summary = journal.build(PAIRS)
        t = read(trades)
        self.assertEqual([r["bot"] for r in t], ["swing", "bumi"])
        self.assertEqual((t[0]["symbol"], t[0]["side"], t[0]["held"], t[0]["model_day_pnl_usd"]), ("QQQ", "short", "30m", "3.0"))
        self.assertEqual(t[0]["pnl_pct"], str(round((610.44 / 610.66 - 1) * -100, 3)))
        self.assertEqual((t[1]["symbol"], t[1]["side"], t[1]["held"], t[1]["entry_date"]), ("QLD", "long", "8 days", "2026-12-01"))
        f = read(fills)
        self.assertEqual(len(f), 3)
        self.assertEqual((f[2]["model_price"], f[2]["slippage_bp"]), ("107.95", "-4.63"))
        self.assertIn("2 closed trades", summary); self.assertIn("3 fills", summary); self.assertIn("+$91.07", summary)
        self.assertEqual(list(t[0].keys()), journal.TRADE_COLS)

    def test_filters(self):
        t, f, s = journal.build(PAIRS, bot="bumi")
        self.assertEqual([r["bot"] for r in read(t)], ["bumi"])
        t, f, s = journal.build(PAIRS, start="2026-12-01")
        self.assertEqual([r["bot"] for r in read(t)], ["bumi"])
        t, f, s = journal.build([], None, None)
        self.assertEqual(read(t), []); self.assertIn("no bots yet", s)


if __name__ == "__main__":
    unittest.main()
