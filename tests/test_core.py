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

    async def test_allowed_guilds(self):
        self.assertTrue(await self.db.add_allowed_guild(123456, 999))
        self.assertFalse(await self.db.add_allowed_guild(123456, 999))
        self.assertEqual(await self.db.load_allowed_guilds(), [123456])
        details = await self.db.list_allowed_guilds_details()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["guild_id"], 123456)
        self.assertEqual(details[0]["added_by"], 999)
        self.assertTrue(await self.db.remove_allowed_guild(123456))
        self.assertFalse(await self.db.remove_allowed_guild(123456))
        self.assertEqual(await self.db.load_allowed_guilds(), [])
        await self.db.add_allowed_guild(111, 999)
        await self.db.add_allowed_guild(222, 999)
        self.assertEqual(len(await self.db.load_allowed_guilds()), 2)
        self.assertEqual(await self.db.clear_allowed_guilds(), 2)
        self.assertEqual(await self.db.load_allowed_guilds(), [])

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



class DatabaseExtraTests(unittest.IsolatedAsyncioTestCase):
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
