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


from unittest.mock import AsyncMock, MagicMock

import discord

# Mock google.genai nếu môi trường test chưa cài
if "google" not in sys.modules:
    sys.modules["google"] = MagicMock()
    sys.modules["google.genai"] = MagicMock()
    sys.modules["google.genai.types"] = MagicMock()
    sys.modules["google.genai.errors"] = MagicMock()

from bot import (  # noqa: E402
    bot,
    build_channel_context,
    get_referenced_message,
    is_message_for_bot,
)


class ChannelContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Mock bot._connection.user
        mock_user = MagicMock()
        mock_user.id = 9999
        mock_user.display_name = "GeminiBot"
        bot._connection.user = mock_user

    async def test_build_channel_context_none_or_zero(self):
        self.assertEqual(await build_channel_context(None), "")
        channel = MagicMock()
        self.assertEqual(await build_channel_context(channel, limit=0), "")

    async def test_build_channel_context_formats_messages(self):
        user1 = MagicMock()
        user1.id = 111
        user1.display_name = "UserA"

        user2 = MagicMock()
        user2.id = 222
        user2.display_name = "UserB"

        bot_user = MagicMock()
        bot_user.id = 9999
        bot_user.display_name = "GeminiBot"

        msg1 = MagicMock()
        msg1.id = 1
        msg1.author = user1
        msg1.clean_content = "Tối nay ăn gì?"
        msg1.content = "Tối nay ăn gì?"
        msg1.attachments = []
        msg1.reference = None

        msg2 = MagicMock()
        msg2.id = 2
        msg2.author = user2
        msg2.clean_content = "Đi ăn phở nhé"
        msg2.content = "Đi ăn phở nhé"
        msg2.attachments = []
        msg2.reference = MagicMock(message_id=1)

        msg3 = MagicMock()
        msg3.id = 3
        msg3.author = bot_user
        msg3.clean_content = "Phở Thìn ngon lắm đó"
        msg3.content = "Phở Thìn ngon lắm đó"
        msg3.attachments = []
        msg3.reference = None

        async def mock_history(limit=10, before=None):
            # Discord returns newest first: msg3, msg2, msg1
            for m in [msg3, msg2, msg1]:
                yield m

        channel = MagicMock()
        channel.history = mock_history

        result = await build_channel_context(channel, limit=10)
        self.assertIn("Lịch sử các tin nhắn gần nhất trong kênh chat", result)
        # Should be ordered chronologically: UserA first, then UserB, then Bot
        pos1 = result.find("UserA: Tối nay ăn gì?")
        pos2 = result.find("UserB (đang reply): Đi ăn phở nhé")
        pos3 = result.find("Bot (GeminiBot - chính bạn): Phở Thìn ngon lắm đó")

        self.assertTrue(pos1 != -1 and pos2 != -1 and pos3 != -1)
        self.assertTrue(pos1 < pos2 < pos3)

    async def test_build_channel_context_with_ref_msg(self):
        ref_user = MagicMock()
        ref_user.id = 555
        ref_user.display_name = "Sender"

        ref_msg = MagicMock()
        ref_msg.author = ref_user
        ref_msg.clean_content = "Đây là đề bài toán"
        ref_msg.content = "Đây là đề bài toán"
        ref_msg.attachments = []

        result = await build_channel_context(None, ref_msg=ref_msg, limit=10)
        # channel is None, but ref_msg is handled if channel is passed or when channel has messages
        channel = MagicMock()

        async def empty_history(limit=10, before=None):
            if False:
                yield None

        channel.history = empty_history
        result = await build_channel_context(channel, ref_msg=ref_msg, limit=10)
        self.assertIn("[Tin nhắn đang được người dùng trực tiếp reply / trích dẫn]:", result)
        self.assertIn("Sender: Đây là đề bài toán", result)

    async def test_get_referenced_message(self):
        msg_no_ref = MagicMock()
        msg_no_ref.reference = None
        self.assertIsNone(await get_referenced_message(msg_no_ref))

        resolved_msg = MagicMock(spec=MagicMock)
        resolved_msg.id = 123
        msg_resolved = MagicMock()
        import discord
        # We can mock resolved with a discord.Message instance or isinstance check
        msg_resolved.reference = MagicMock()
        msg_resolved.reference.resolved = MagicMock(spec=discord.Message)
        self.assertEqual(await get_referenced_message(msg_resolved), msg_resolved.reference.resolved)

    async def test_is_message_for_bot_mention(self):
        msg = MagicMock()
        msg.mentions = [bot.user]
        msg.reference = MagicMock()
        # Even if reference author is another human
        other_human = MagicMock()
        other_human.id = 8888
        msg.reference.resolved = MagicMock(spec=discord.Message, author=other_human)

        # Bot is mentioned -> must return True
        self.assertTrue(await is_message_for_bot(msg))


if __name__ == "__main__":
    unittest.main()
