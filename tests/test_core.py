import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import VN_TZ  # noqa: E402
from db import Database  # noqa: E402
from utils import next_run_utc, parse_hhmm, split_message  # noqa: E402


class UtilsTests(unittest.TestCase):
    def test_parse_hhmm(self):
        self.assertEqual(parse_hhmm("06:00"), (6, 0))
        self.assertEqual(parse_hhmm(" 18:30 "), (18, 30))
        for bad in ("24:00", "12:60", "abc", "1230", "", "12:"):
            self.assertIsNone(parse_hhmm(bad))

    def test_next_run_rolls_to_tomorrow(self):
        after = datetime(2026, 10, 6, 12, 0, tzinfo=VN_TZ).astimezone(timezone.utc)
        same_day = next_run_utc(18, 30, after).astimezone(VN_TZ)
        self.assertEqual((same_day.day, same_day.hour, same_day.minute), (6, 18, 30))
        next_day = next_run_utc(7, 0, after).astimezone(VN_TZ)
        self.assertEqual((next_day.day, next_day.hour), (7, 7))

    def test_split_message_limits(self):
        text = ("xin chào " * 500).strip()
        chunks = split_message(text, 100)
        self.assertTrue(all(0 < len(c) <= 100 for c in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_split_message_leading_newline_no_infinite_loop(self):
        chunks = split_message("\n" + "a" * 250, 100)
        self.assertEqual("".join(chunks), "a" * 250)

    def test_split_message_no_whitespace(self):
        chunks = split_message("a" * 250, 100)
        self.assertEqual([len(c) for c in chunks], [100, 100, 50])


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "t.db"))
        await self.db.init()

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def test_history_is_per_guild_and_user(self):
        await self.db.save_history_raw(1, 10, "A")
        await self.db.save_history_raw(2, 10, "B")
        self.assertEqual(await self.db.load_history_raw(1, 10), "A")
        self.assertEqual(await self.db.load_history_raw(2, 10), "B")
        await self.db.delete_history(1, 10)
        self.assertIsNone(await self.db.load_history_raw(1, 10))
        self.assertEqual(await self.db.load_history_raw(2, 10), "B")

    async def test_purge_old_history(self):
        await self.db.save_history_raw(1, 1, "old")
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        await self.db._q("UPDATE chat_history SET updated_at = ?", (old,))
        await self.db.save_history_raw(1, 2, "new")
        self.assertEqual(await self.db.purge_old_history(30), 1)
        self.assertIsNone(await self.db.load_history_raw(1, 1))
        self.assertEqual(await self.db.load_history_raw(1, 2), "new")

    async def test_reminder_lifecycle_and_guild_scope(self):
        run = datetime.now(timezone.utc) - timedelta(minutes=1)
        rid = await self.db.add_reminder(
            guild_id=5, channel_id=9, message="hi", repeat="once",
            hour=1, minute=2, next_run_iso=run.isoformat(), created_by=7,
        )
        self.assertEqual(len(await self.db.list_reminders(5)), 1)
        self.assertEqual(len(await self.db.list_reminders(6)), 0)
        self.assertEqual(await self.db.count_active_reminders(7, 5), 1)
        due = await self.db.get_due_reminders(datetime.now(timezone.utc).isoformat())
        self.assertEqual([r["id"] for r in due], [rid])
        self.assertTrue(await self.db.deactivate_reminder(rid))
        self.assertFalse(await self.db.deactivate_reminder(rid))
        self.assertEqual(await self.db.get_due_reminders(datetime.now(timezone.utc).isoformat()), [])

    async def test_auto_chat_channels(self):
        self.assertTrue(await self.db.add_auto_chat_channel(100, 1, 2))
        self.assertFalse(await self.db.add_auto_chat_channel(100, 1, 2))
        self.assertEqual(await self.db.list_auto_chat_channels(1), [100])
        self.assertTrue(await self.db.remove_auto_chat_channel(100))
        self.assertFalse(await self.db.remove_auto_chat_channel(100))

    async def test_concurrent_access(self):
        await asyncio.gather(*(self.db.save_history_raw(1, i, str(i)) for i in range(50)))
        self.assertEqual(await self.db.load_history_raw(1, 49), "49")

    async def test_migrates_old_reminders_table(self):
        path = os.path.join(self.tmp.name, "old.db")
        import sqlite3
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER NOT NULL,
              message TEXT NOT NULL, repeat TEXT NOT NULL, hour INTEGER NOT NULL, minute INTEGER NOT NULL,
              next_run_utc TEXT NOT NULL, created_by INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
            INSERT INTO reminders (channel_id, message, repeat, hour, minute, next_run_utc, created_by)
              VALUES (1, 'x', 'daily', 7, 0, '2026-01-01T00:00:00+00:00', 3);
            CREATE TABLE conversations (user_id INTEGER PRIMARY KEY, history TEXT NOT NULL);
            """
        )
        conn.commit()
        conn.close()
        old = Database(path)
        await old.init()
        missing = await old.reminders_missing_guild()
        self.assertEqual(len(missing), 1)
        await old.set_reminder_guild(missing[0]["id"], 42)
        self.assertEqual(len(await old.list_reminders(42)), 1)
        await old.close()



# ---------------------------------------------------------------- dashboard
import time  # noqa: E402

import dashboard_views as dv  # noqa: E402


class DashboardViewTests(unittest.TestCase):
    def test_everything_user_controlled_is_escaped(self):
        evil = '<script>alert(1)</script>"\'&'
        pages = [
            dv.reminders_body([{"id": 1, "guild": evil, "channel": evil, "repeat": "daily", "hhmm": "07:00",
                                "next_run": "x", "creator": evil, "message": evil}], "tok"),
            dv.autochat_body([{"guild": evil, "channel": evil, "channel_id": 1}], [(evil, [(2, evil)])], "tok"),
            dv.logs_body([evil]),
            dv.settings_body([(evil, evil)], evil),
            dv.layout(title=evil, body="", csrf=evil, active="/", msg=evil),
            dv.login_page(evil),
        ]
        for page in pages:
            self.assertNotIn("<script>alert(1)</script>", page)

    def test_state_changing_forms_carry_csrf(self):
        html = dv.reminders_body([{"id": 1, "guild": "g", "channel": "c", "repeat": "once", "hhmm": "01:00",
                                   "next_run": "x", "creator": 1, "message": "m"}], "CSRF123")
        self.assertIn('name="csrf" value="CSRF123"', html)
        self.assertIn('method="post"', html)

    def test_session_store(self):
        store = dv.SessionStore(ttl=1)
        token, session = store.create()
        self.assertTrue(session.csrf)
        self.assertIs(store.get(token), session)
        self.assertIsNone(store.get("nope"))
        self.assertIsNone(store.get(None))
        store.delete(token)
        self.assertIsNone(store.get(token))
        token2, _ = store.create()
        store._sessions[token2].created_at = time.time() - 10  # quá TTL (1 giây)
        self.assertIsNone(store.get(token2))

    def test_login_limiter(self):
        lim = dv.LoginLimiter(max_failures=3, block_seconds=100)
        for _ in range(3):
            self.assertFalse(lim.blocked("1.2.3.4"))
            lim.fail("1.2.3.4")
        self.assertTrue(lim.blocked("1.2.3.4"))
        self.assertFalse(lim.blocked("5.6.7.8"))  # IP khác không bị ảnh hưởng
        lim._data["1.2.3.4"] = (3, time.time() - 200)  # hết thời gian chặn
        self.assertFalse(lim.blocked("1.2.3.4"))
        lim.fail("5.6.7.8")
        lim.reset("5.6.7.8")
        self.assertFalse(lim.blocked("5.6.7.8"))


class DashboardDbTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "d.db"))
            await db.init()
            await db.save_history_raw(1, 1, "a")
            await db.save_history_raw(1, 2, "b")
            self.assertEqual(await db.count_history(), 2)
            self.assertEqual(await db.delete_all_history(), 2)
            self.assertEqual(await db.count_history(), 0)
            await db.add_auto_chat_channel(10, 1, 0)
            self.assertEqual([tuple(r) for r in await db.list_all_auto_chat()], [(10, 1)])
            run = datetime.now(timezone.utc).isoformat()
            await db.add_reminder(guild_id=1, channel_id=2, message="m", repeat="once", hour=1, minute=1,
                                  next_run_iso=run, created_by=3)
            self.assertEqual(len(await db.list_all_active_reminders()), 1)
            await db.close()


if __name__ == "__main__":
    unittest.main()
