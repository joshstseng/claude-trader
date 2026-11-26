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


def unzip(data):
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(data))
    return {n: read(z.read(n)) for n in z.namelist()}


class Journal(unittest.TestCase):
    def test_all_bots_one_section_each_and_one_zip(self):
        data, text = journal.build(PAIRS)
        files = unzip(data)
        self.assertEqual(sorted(files), ["bumi-fills.csv", "bumi-trades.csv", "swing-fills.csv", "swing-trades.csv"])
        t = files["swing-trades.csv"][0]
        self.assertEqual((t["symbol"], t["side"], t["held"], t["model_day_pnl_usd"]), ("QQQ", "short", "30m", "3.0"))
        self.assertEqual(files["bumi-trades.csv"][0]["held"], "8 days")
        self.assertEqual(files["bumi-fills.csv"][0]["slippage_bp"], "-4.63")
        self.assertLess(text.index("**Swing**"), text.index("**Bumi**"))
        self.assertIn("1 closed trade · 1 won · **+$11.07**", text)
        self.assertIn("Model +$3.00 · fills 0.7 bp worse than the model", text)
        self.assertIn("**+$80.00**", text)

    def test_one_bot_and_no_trades_yet(self):
        only = [p for p in PAIRS if not p[0].startswith("daily:bumi")]
        data, text = journal.build(only, bot="bumi")
        self.assertIn("**Bumi**", text); self.assertNotIn("Swing", text)
        self.assertIn("No daily records yet", text)
        self.assertEqual(sorted(unzip(data)), ["bumi-fills.csv", "bumi-trades.csv"])
        quiet = [("daily:swing:2026-11-23", json.dumps({"day": "2026-11-23", "trades": [], "fills": []}))]
        self.assertIn("No closed trades yet (since Nov 23, 1 market day)", journal.build(quiet, bot="swing")[1])

    def test_recent_five_then_a_note(self):
        recs = [{"day": f"2026-12-{d:02d}", "symbol": "QQQ", "model_pnl": 0.0, "fills": [],
                 "trades": [{"side": 1, "qty": 10, "entry": 100.0, "exit": 101.0 if d % 2 else 99.0, "pnl": 10.0 if d % 2 else -10.0,
                             "time_in": "10:00:00", "time_out": "11:15:00", "why": "back inside the band"}]} for d in range(1, 9)]
        _, text = journal.build([(f"daily:swing:{r['day']}", json.dumps(r)) for r in recs], bot="swing")
        lines = text.splitlines()
        rows = [l for l in lines if l.startswith(("✅", "❌"))]
        self.assertEqual(len(rows), 5)
        self.assertTrue(rows[0].startswith("❌ `Dec 8` long QQQ · **−$10.00** · 1h 15m · back inside the band"))
        self.assertIn("-# + 3 older trades in the spreadsheet", text)
        _, one = journal.build(PAIRS, bot="swing")
        self.assertNotIn("older trade", one)

    def test_unknown_bot_and_date_filter(self):
        data, text = journal.build(PAIRS, bot="zed")
        self.assertEqual(data, b""); self.assertIn("No bot called **zed**", text); self.assertIn("Swing, Bumi", text)
        data, text = journal.build(PAIRS, start="2026-12-01")
        self.assertIn("from Dec 1", text)
        self.assertEqual(unzip(data)["swing-trades.csv"], [])


if __name__ == "__main__":
    unittest.main()
