"""Test các cải tiến hiệu suất: lọc Auto-Chat, retry Gemini, cooldown, thinking config."""
import asyncio
import os
import tempfile
import time
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")

from google.genai.errors import ClientError  # noqa: E402

import bot  # noqa: E402
import config  # noqa: E402
from db import Database  # noqa: E402
from utils import is_trivial_message  # noqa: E402


class TrivialMessageTests(unittest.TestCase):
    def test_trivial(self):
        for text in ["", "   ", "👍", "😂😂😂", "https://example.com/a?b=1", "<:kek:123456789>",
                     "<a:dance:987654321> https://x.y", "!!!", "..."]:
            self.assertTrue(is_trivial_message(text), text)

    def test_not_trivial(self):
        for text in ["alo", "k", "hello bot", "123", "xin chào 👋", "ê", "link https://a.b nè"]:
            self.assertFalse(is_trivial_message(text), text)


class _Resp:
    text = "ok"
    candidates: list = []


class _FakeModels:
    def __init__(self, script):
        self.script = list(script)  # mỗi phần tử: "ok" hoặc "429"
        self.calls = 0

    async def generate_content(self, **kwargs):
        self.calls += 1
        step = self.script.pop(0) if self.script else "ok"
        if step == "429":
            raise ClientError(429, {"error": {"message": "rate"}})
        await asyncio.sleep(0.01)
        return _Resp()


class _FakeClient:
    def __init__(self, script):
        self.aio = type("A", (), {})()
        self.aio.models = _FakeModels(script)


class AskGeminiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        bot.db = Database(os.path.join(self.tmp.name, "t.db"))
        await bot.db.init()
        bot.history_cache.clear()
        self._orig = (bot.gemini_client, bot.gemini_sem, config.GEMINI_429_RETRY_SECONDS)

    async def asyncTearDown(self):
        bot.gemini_client, bot.gemini_sem, config.GEMINI_429_RETRY_SECONDS = self._orig
        await bot.db.close()
        self.tmp.cleanup()

    async def test_429_retries_once_then_succeeds(self):
        config.GEMINI_429_RETRY_SECONDS = 0.05
        bot.gemini_client = _FakeClient(["429", "ok"])
        bot.gemini_sem = asyncio.Semaphore(1)
        self.assertEqual(await bot.ask_gemini((1, 1), "hi"), "ok")
        self.assertEqual(bot.gemini_client.aio.models.calls, 2)

    async def test_429_twice_returns_rate_limit_message(self):
        config.GEMINI_429_RETRY_SECONDS = 0.01
        bot.gemini_client = _FakeClient(["429", "429"])
        bot.gemini_sem = asyncio.Semaphore(1)
        self.assertEqual(await bot.ask_gemini((1, 2), "hi"), bot.MSG_RATE_LIMIT)

    async def test_slot_released_while_waiting_to_retry(self):
        """Với 1 slot: request B phải xong trong lúc A đang chờ retry (trước đây bị kẹt)."""
        config.GEMINI_429_RETRY_SECONDS = 0.5
        bot.gemini_client = _FakeClient(["429"])  # chỉ lần gọi đầu bị 429
        bot.gemini_sem = asyncio.Semaphore(1)
        t0 = time.monotonic()
        a = asyncio.create_task(bot.ask_gemini((1, 3), "A"))
        await asyncio.sleep(0.05)  # để A nhận 429 và vào trạng thái chờ
        b_reply = await bot.ask_gemini((1, 4), "B")
        b_elapsed = time.monotonic() - t0
        self.assertEqual(b_reply, "ok")
        self.assertLess(b_elapsed, 0.4, "B bị chặn bởi slot của A")
        self.assertEqual(await a, "ok")


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(config.GEMINI_MODEL, "gemini-3.5-flash-lite")
        self.assertEqual(config.GEMINI_TIMEOUT, 30)

    def test_thinking_level_config(self):
        orig = (config.THINKING_LEVEL, config.THINKING_BUDGET)
        try:
            config.THINKING_LEVEL, config.THINKING_BUDGET = "low", 100
            cfg = bot._build_thinking_config()
            self.assertIsNotNone(cfg)
            self.assertEqual(str(cfg.thinking_level.value).lower(), "low")
            self.assertIsNone(cfg.thinking_budget)  # không gửi cả hai
            config.THINKING_LEVEL, config.THINKING_BUDGET = None, None
            self.assertIsNone(bot._build_thinking_config())
        finally:
            config.THINKING_LEVEL, config.THINKING_BUDGET = orig


class CooldownTests(unittest.TestCase):
    def test_cooldown(self):
        orig = config.AUTO_CHAT_COOLDOWN_SECONDS
        try:
            bot._auto_last.clear()
            config.AUTO_CHAT_COOLDOWN_SECONDS = 60
            self.assertFalse(bot._auto_chat_on_cooldown(1, 1))
            self.assertTrue(bot._auto_chat_on_cooldown(1, 1))
            self.assertFalse(bot._auto_chat_on_cooldown(1, 2))  # người khác
            self.assertFalse(bot._auto_chat_on_cooldown(2, 1))  # kênh khác
            config.AUTO_CHAT_COOLDOWN_SECONDS = 0
            self.assertFalse(bot._auto_chat_on_cooldown(1, 1))
        finally:
            config.AUTO_CHAT_COOLDOWN_SECONDS = orig


class PurgeReminderTests(unittest.IsolatedAsyncioTestCase):
    async def test_purge_inactive_reminders(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Database(os.path.join(tmp, "r.db"))
            await d.init()
            old = "2020-01-01T00:00:00+00:00"
            future = "2999-01-01T00:00:00+00:00"
            kw = dict(guild_id=1, channel_id=1, message="m", repeat="once", hour=1, minute=1, created_by=1)
            old_id = await d.add_reminder(next_run_iso=old, **kw)
            act_old = await d.add_reminder(next_run_iso=old, **kw)
            fut_id = await d.add_reminder(next_run_iso=future, **kw)
            await d.deactivate_reminder(old_id)
            await d.deactivate_reminder(fut_id)
            self.assertEqual(await d.purge_inactive_reminders(30), 1)  # chỉ cái tắt + cũ
            self.assertIsNone(await d.get_reminder(old_id))
            self.assertIsNotNone(await d.get_reminder(act_old))  # đang bật: giữ
            self.assertIsNotNone(await d.get_reminder(fut_id))   # tắt nhưng giờ chạy ở tương lai: giữ
            await d.close()


if __name__ == "__main__":
    unittest.main()
