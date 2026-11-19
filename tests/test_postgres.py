"""Step 2b.3: the shared Postgres trade log. Runs only when TRADELOG_TEST_PG_URL points at a
throwaway Postgres (e.g. a local Docker one); never at the live database."""

import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from app import tradelog

URL = os.environ.get("TRADELOG_TEST_PG_URL")
REPLAYS = Path(__file__).resolve().parent.parent / "data" / "replays.db"


@unittest.skipUnless(URL, "set TRADELOG_TEST_PG_URL to a throwaway Postgres")
class PostgresTest(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.schema = "m_" + uuid.uuid4().hex[:12]
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
        self.pg = tradelog.TradeLog(url=URL, schema=self.schema)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        import psycopg
        self.pg.close()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")
        self.tmp.cleanup()

    def test_fleet_tables(self):
        self.pg.beat("orb", "running")
        self.pg.beat("orb", "still running")
        rows = self.pg.heartbeats()
        self.assertEqual([(r["bot"], r["note"]) for r in rows], [("orb", "still running")])
        self.assertFalse(self.pg.global_pause())
        self.pg.set_fleet("global_pause", "on")
        self.assertTrue(self.pg.global_pause())

    def test_orders_are_kept_apart_by_bot(self):
        for strat in ("orb", "demo"):
            run = self.pg.start_run(strat, "live", {}, date_from="2026-11-19", date_to="2026-11-19")
            self.pg.db.execute("INSERT INTO signals (run_id, strategy, source, date, symbol, status, created_at)"
                               " VALUES (?, ?, 'live', '2026-11-19', 'TSLA', 'pass', 'x')", (run, strat))
            sid = self.pg.db.lastrowid
            self.pg.add_order(sid, f"{strat}-2026-11-19-{sid}", "TSLA", 1, 1.0, 0.5, 2.0)
        self.assertEqual([r["client_order_id"].split("-")[0] for r in self.pg.open_orders(strategy="orb")], ["orb"])
        self.assertEqual(len(self.pg.open_orders()), 2)

    @unittest.skipUnless(REPLAYS.exists(), "needs a local replay log to copy")
    def test_one_time_copy_keeps_every_row_and_id(self):
        src = Path(self.tmp.name) / "tradelog.db"
        shutil.copy(REPLAYS, src)
        before = {t: sqlite3.connect(src).execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("runs", "signals", "alerts", "responses", "outcomes")}
        max_sig = sqlite3.connect(src).execute("SELECT MAX(id) FROM signals").fetchone()[0]
        copied = tradelog.migrate_sqlite_to_postgres(src, self.pg)
        for t, n in before.items():
            self.assertEqual(copied[t], n, t)
            self.assertEqual(self.pg.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], n, t)
        self.assertFalse(src.exists())                                  # kept as a backup, renamed
        self.assertTrue(src.with_name("tradelog.db.moved-to-postgres").exists())
        a = self.pg.signals(run_id=1)
        self.assertTrue(a and a[0]["symbol"])
        run = self.pg.start_run("orb", "live", {})                     # new ids continue after the copied ones
        self.pg.db.execute("INSERT INTO signals (run_id, strategy, source, date, symbol, status, created_at)"
                           " VALUES (?, 'orb', 'live', '2026-11-19', 'ZZZ', 'pass', 'x')", (run,))
        self.assertGreater(self.pg.db.lastrowid, max_sig)
        self.assertIsNone(tradelog.migrate_sqlite_to_postgres(src, self.pg))   # never twice


if __name__ == "__main__":
    unittest.main()
