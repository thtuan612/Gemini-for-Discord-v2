"""Test: fallback nhiều model Gemini, client Literouter (HTTP thật tới server giả cục bộ), cache danh sách model."""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestServer  # noqa: E402

import bot  # noqa: E402
import config  # noqa: E402
import literouter  # noqa: E402
from literouter import LiterouterClient, LiterouterError, build_messages, parse_models  # noqa: E402

TEST_KEY = "sk-test-secret-123"


class ParseAndBuildTests(unittest.TestCase):
    def test_parse_models_openai_format(self):
        payload = {"object": "list", "data": [{"id": "a"}, {"id": "b"}, {"id": "a"}, {"id": "  "}, {"x": 1}, 5]}
        self.assertEqual(parse_models(payload), ["a", "b"])

    def test_parse_models_variants(self):
        self.assertEqual(parse_models({"models": ["x", {"name": "y"}]}), ["x", "y"])
        self.assertEqual(parse_models(["p", "q"]), ["p", "q"])
        self.assertEqual(parse_models({"data": "oops"}), [])
        self.assertEqual(parse_models(None), [])

    def test_build_messages_roles_and_text(self):
        msgs = build_messages("SYS", [("user", "hi"), ("model", "hello")], "tiếp đi")
        self.assertEqual(
            msgs,
            [
                {"role": "system", "content": "SYS"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "tiếp đi"},
            ],
        )

    def test_build_messages_with_image(self):
        msgs = build_messages("", [], "nhìn này", [("image/png", b"\x89PNG")])
        self.assertEqual(msgs[0]["role"], "user")  # không có system rỗng
        parts = msgs[0]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "nhìn này"})
        self.assertEqual(parts[1]["type"], "image_url")
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))


class _FakeServer:
    """Server OpenAI-compatible giả, chạy thật trên localhost."""

    def __init__(self):
        self.models_payload = {"data": [{"id": "m-a"}, {"id": "m-b"}]}
        self.models_status = 200
        self.chat_status = 200
        self.chat_body = {"choices": [{"message": {"content": " xin chào "}, "finish_reason": "stop"}]}
        self.requests: list[tuple[str, dict, object]] = []
        app = web.Application()
        app.router.add_get("/api/v1/models", self._models)
        app.router.add_post("/api/v1/chat/completions", self._chat)
        self.server = TestServer(app)

    async def _models(self, request):
        self.requests.append(("models", dict(request.headers), None))
        return web.json_response(self.models_payload, status=self.models_status)

    async def _chat(self, request):
        body = await request.json()
        self.requests.append(("chat", dict(request.headers), body))
        return web.json_response(self.chat_body, status=self.chat_status)

    def count(self, kind: str) -> int:
        return sum(1 for k, _, _ in self.requests if k == kind)


class LiterouterClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = _FakeServer()
        await self.fake.server.start_server()
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.tmp.name, "sub", "models.json")
        base = f"http://127.0.0.1:{self.fake.server.port}/api/v1/"  # dấu "/" cuối phải được xử lý
        for name, value in {
            "LITEROUTER_ENABLED": True,
            "LITEROUTER_API_KEY": TEST_KEY,
            "LITEROUTER_BASE_URL": base.rstrip("/"),
            "LITEROUTER_MODEL": "",
            "LITEROUTER_TIMEOUT": 5,
            "LITEROUTER_MODELS_REFRESH_HOURS": 6,
            "LITEROUTER_CACHE_PATH": self.cache_path,
        }.items():
            p = patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = LiterouterClient()

    async def asyncTearDown(self):
        await self.client.stop()
        await self.fake.server.close()
        self.tmp.cleanup()

    def _write_cache(self, models, fetched_at):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": fetched_at, "models": models}, f)

    # ---- chat ----
    async def test_chat_success_sends_key_and_payload(self):
        text, truncated = await self.client.chat([{"role": "user", "content": "hi"}], model="m-a")
        self.assertEqual(text, "xin chào")
        self.assertFalse(truncated)
        _, headers, body = self.fake.requests[0]
        self.assertEqual(headers.get("Authorization"), f"Bearer {TEST_KEY}")
        self.assertEqual(body["model"], "m-a")
        self.assertEqual(body["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual(body["max_tokens"], config.MAX_OUTPUT_TOKENS)
        self.assertNotIn("temperature", body)

    async def test_chat_truncated_when_finish_length(self):
        self.fake.chat_body = {"choices": [{"message": {"content": "dở dang"}, "finish_reason": "length"}]}
        text, truncated = await self.client.chat([{"role": "user", "content": "hi"}], model="m-a")
        self.assertEqual(text, "dở dang")
        self.assertTrue(truncated)

    async def test_chat_content_list_parts(self):
        self.fake.chat_body = {"choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}]}
        text, _ = await self.client.chat([{"role": "user", "content": "hi"}], model="m-a")
        self.assertEqual(text, "ab")

    async def test_chat_429_is_temporary_and_hides_key(self):
        self.fake.chat_status = 429
        self.fake.chat_body = {"error": {"message": "slow down"}}
        with self.assertRaises(LiterouterError) as cm:
            await self.client.chat([{"role": "user", "content": "hi"}], model="m-a")
        self.assertEqual(cm.exception.status, 429)
        self.assertTrue(cm.exception.temporary)
        self.assertIn("slow down", str(cm.exception))
        self.assertNotIn(TEST_KEY, str(cm.exception))

    async def test_chat_5xx_temporary_but_400_not(self):
        self.fake.chat_status = 503
        self.fake.chat_body = {"error": "down"}
        with self.assertRaises(LiterouterError) as cm:
            await self.client.chat([{"role": "user", "content": "hi"}], model="m-a")
        self.assertTrue(cm.exception.temporary)

        self.fake.chat_status = 400
        with self.assertRaises(LiterouterError) as cm:
            await self.client.chat([{"role": "user", "content": "hi"}], model="m-a")
        self.assertFalse(cm.exception.temporary)

    async def test_chat_connection_error_is_temporary(self):
        with patch.object(config, "LITEROUTER_BASE_URL", "http://127.0.0.1:1/api/v1"):
            with self.assertRaises(LiterouterError) as cm:
                await self.client.chat([{"role": "user", "content": "hi"}], model="m-a")
        self.assertTrue(cm.exception.temporary)

    # ---- danh sách model + cache ----
    async def test_refresh_saves_cache_and_new_client_loads_it(self):
        self.assertTrue(await self.client.refresh())
        self.assertEqual(self.client.models, ["m-a", "m-b"])
        self.assertTrue(os.path.exists(self.cache_path))
        self.assertFalse(os.path.exists(self.cache_path + ".tmp"))

        other = LiterouterClient()
        self.assertTrue(other.load_cache())
        self.assertEqual(other.models, ["m-a", "m-b"])
        self.assertIsNotNone(other.fetched_at)

    async def test_refresh_failure_keeps_models_and_cache(self):
        await self.client.refresh()
        with open(self.cache_path, encoding="utf-8") as f:
            before = f.read()

        self.fake.models_status = 500
        self.assertFalse(await self.client.refresh())
        self.assertEqual(self.client.models, ["m-a", "m-b"])

        self.fake.models_status = 200
        self.fake.models_payload = {"data": []}
        self.assertFalse(await self.client.refresh())
        self.assertEqual(self.client.models, ["m-a", "m-b"])

        with open(self.cache_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    async def test_models_request_uses_key_when_available(self):
        await self.client.refresh()
        _, headers, _ = self.fake.requests[0]
        self.assertEqual(headers.get("Authorization"), f"Bearer {TEST_KEY}")

    async def test_corrupt_cache_is_ignored(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            f.write("{không phải json")
        self.assertFalse(self.client.load_cache())
        self.assertEqual(self.client.models, [])

    async def test_resolve_model(self):
        self.assertIsNone(self.client.resolve_model())  # chưa có danh sách, chưa cấu hình
        self.client.models = ["first", "second"]
        self.assertEqual(self.client.resolve_model(), "first")
        with patch.object(config, "LITEROUTER_MODEL", "second"):
            self.assertEqual(self.client.resolve_model(), "second")
        with patch.object(config, "LITEROUTER_MODEL", "tu-cau-hinh"):  # không có trong list vẫn tôn trọng .env
            self.assertEqual(self.client.resolve_model(), "tu-cau-hinh")
        self.client.models = []
        with patch.object(config, "LITEROUTER_MODEL", "tu-cau-hinh"):  # API sập + chưa có cache
            self.assertEqual(self.client.resolve_model(), "tu-cau-hinh")

    async def test_available_requires_enabled_and_key(self):
        self.assertTrue(self.client.available)
        with patch.object(config, "LITEROUTER_ENABLED", False):
            self.assertFalse(self.client.available)
        with patch.object(config, "LITEROUTER_API_KEY", None):
            self.assertFalse(self.client.available)

    async def test_start_skips_fetch_when_cache_fresh(self):
        self._write_cache(["cached"], time.time())
        self.client.start()
        await asyncio.sleep(0.2)
        self.assertEqual(self.client.models, ["cached"])
        self.assertEqual(self.fake.count("models"), 0)

    async def test_start_refreshes_when_cache_stale(self):
        self._write_cache(["cached"], time.time() - 7 * 3600)
        self.client.start()
        for _ in range(40):
            if self.client.models == ["m-a", "m-b"]:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(self.client.models, ["m-a", "m-b"])
        self.assertEqual(self.fake.count("models"), 1)

    async def test_start_uses_cache_when_api_down(self):
        self._write_cache(["cached"], time.time() - 7 * 3600)
        self.fake.models_status = 503
        self.client.start()
        await asyncio.sleep(0.3)
        self.assertEqual(self.client.models, ["cached"])
        self.assertEqual(self.client.resolve_model(), "cached")


class _FakeTypes:
    """Thay cho google.genai.types: test_core.py có thể đã mock cả package google khi chạy chung một phiên."""

    class Part:
        def __init__(self, text=None, inline_data=None):
            self.text = text
            self.inline_data = inline_data

        @classmethod
        def from_bytes(cls, data, mime_type):
            return cls(inline_data=SimpleNamespace(data=data, mime_type=mime_type))

    class Content:
        def __init__(self, role=None, parts=None):
            self.role = role
            self.parts = parts or []

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    """ask_gemini: nhiều model Gemini + Literouter làm dự phòng."""

    class _ClientError(Exception):
        def __init__(self, code=400):
            self.code = code
            super().__init__(f"ClientError {code}")

    class _ServerError(Exception):
        pass

    def _ok(self, text):
        resp = MagicMock()
        resp.text = text
        candidate = MagicMock()
        candidate.finish_reason.name = "STOP"
        resp.candidates = [candidate]
        return resp

    def _set(self, name, value):
        p = patch.object(config, name, value)
        p.start()
        self.addCleanup(p.stop)

    async def asyncSetUp(self):
        for patcher in (
            patch("bot.ClientError", self._ClientError),
            patch("bot.ServerError", self._ServerError),
            patch("bot.load_history", new_callable=AsyncMock, return_value=deque(maxlen=20)),
            patch("bot.save_history", new_callable=AsyncMock),
            patch.object(bot, "types", _FakeTypes),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sleep = patch("asyncio.sleep", new_callable=AsyncMock).start()
        self.addCleanup(patch.stopall)

        self._set("GEMINI_ENABLED", True)
        self._set("GEMINI_MODELS", ["g-main", "g-fb"])
        self._set("GEMINI_429_RETRY_SECONDS", 1)
        self._set("AI_PROVIDER_ORDER", ["gemini", "literouter"])
        self._set("LITEROUTER_ENABLED", False)
        self._set("LITEROUTER_API_KEY", None)
        self._set("LITEROUTER_MODEL", "")

        self.behaviors: dict[str, list] = {}
        self.calls: list[str] = []

        async def fake_generate(model, contents, config):
            self.calls.append(model)
            item = self.behaviors[model].pop(0)
            if isinstance(item, Exception):
                raise item
            return self._ok(item)

        self._orig_client = bot.gemini_client
        bot.gemini_client = MagicMock()
        bot.gemini_client.aio.models.generate_content = fake_generate
        self.addCleanup(setattr, bot, "gemini_client", self._orig_client)

    def _enable_literouter(self, chat):
        self._set("LITEROUTER_ENABLED", True)
        self._set("LITEROUTER_API_KEY", TEST_KEY)
        for p in (
            patch.object(literouter.client, "models", ["lr-model", "lr-other"]),
            patch.object(literouter.client, "chat", chat),
        ):
            p.start()
            self.addCleanup(p.stop)

    async def test_primary_success_no_fallback(self):
        self.behaviors = {"g-main": ["ok chính"], "g-fb": []}
        self.assertEqual(await bot.ask_gemini((1, 1), "hi"), "ok chính")
        self.assertEqual(self.calls, ["g-main"])

    async def test_429_falls_back_immediately_without_sleep(self):
        self.behaviors = {"g-main": [self._ClientError(429)], "g-fb": ["từ dự phòng"]}
        self.assertEqual(await bot.ask_gemini((1, 2), "hi"), "từ dự phòng")
        self.assertEqual(self.calls, ["g-main", "g-fb"])
        self.sleep.assert_not_called()

    async def test_server_error_falls_back(self):
        self.behaviors = {"g-main": [self._ServerError("503")], "g-fb": ["ok dự phòng"]}
        self.assertEqual(await bot.ask_gemini((1, 3), "hi"), "ok dự phòng")
        self.assertEqual(self.calls, ["g-main", "g-fb"])

    async def test_timeout_falls_back(self):
        self.behaviors = {"g-main": [asyncio.TimeoutError()], "g-fb": ["ok sau timeout"]}
        self.assertEqual(await bot.ask_gemini((1, 4), "hi"), "ok sau timeout")

    async def test_all_gemini_models_rate_limited(self):
        # model cuối giữ retry 429 một lần → 1 (main) + 2 (fb) = 3 lần gọi
        self.behaviors = {
            "g-main": [self._ClientError(429)],
            "g-fb": [self._ClientError(429), self._ClientError(429)],
        }
        self.assertEqual(await bot.ask_gemini((1, 5), "hi"), bot.MSG_RATE_LIMIT)
        self.assertEqual(self.calls, ["g-main", "g-fb", "g-fb"])

    async def test_non_retryable_error_does_not_fall_back(self):
        self.behaviors = {"g-main": [self._ClientError(400)], "g-fb": ["không được gọi"]}
        self.assertEqual(await bot.ask_gemini((1, 6), "hi"), bot.MSG_API_ERROR)
        self.assertEqual(self.calls, ["g-main"])

    async def test_fallback_reply_is_saved_to_history(self):
        self.behaviors = {"g-main": [self._ClientError(429)], "g-fb": ["trả lời dự phòng"]}
        await bot.ask_gemini((1, 7), "câu hỏi")
        saved = bot.save_history.call_args.args[1]
        self.assertEqual([c.role for c in saved], ["user", "model"])
        self.assertEqual(saved[1].parts[0].text, "trả lời dự phòng")

    async def test_literouter_is_last_resort_after_gemini(self):
        chat = AsyncMock(return_value=("từ literouter", False))
        self._enable_literouter(chat)
        self.behaviors = {"g-main": [self._ClientError(429)], "g-fb": [self._ServerError("x")]}
        self.assertEqual(await bot.ask_gemini((1, 8), "hello", privileged=True), "từ literouter")
        self.assertEqual(self.calls, ["g-main", "g-fb"])
        chat.assert_awaited_once()
        messages = chat.call_args.args[0]
        self.assertEqual(chat.call_args.kwargs["model"], "lr-model")  # model đầu tiên trong danh sách /models
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn(config.PRIVILEGED_NOTE, messages[0]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "hello"})

    async def test_literouter_gets_history_and_image(self):
        chat = AsyncMock(return_value=("thấy ảnh rồi", False))
        self._enable_literouter(chat)
        self._set("GEMINI_ENABLED", False)
        history = deque(maxlen=20)
        history.append(bot.types.Content(role="user", parts=[bot.types.Part(text="trước đó")]))
        history.append(bot.types.Content(role="model", parts=[bot.types.Part(text="đã trả lời")]))
        bot.load_history.return_value = history
        img = bot.types.Part.from_bytes(data=b"\x89PNGdata", mime_type="image/png")

        self.assertEqual(await bot.ask_gemini((1, 9), "ảnh gì đây", image_parts=[img]), "thấy ảnh rồi")
        self.assertEqual(self.calls, [])  # Gemini tắt: không gọi
        messages = chat.call_args.args[0]
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user"])
        self.assertEqual(messages[1]["content"], "trước đó")
        self.assertEqual(messages[2]["content"], "đã trả lời")
        last = messages[-1]["content"]
        self.assertEqual(last[0], {"type": "text", "text": "ảnh gì đây"})
        self.assertTrue(last[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    async def test_literouter_429_retries_once_when_last(self):
        chat = AsyncMock(side_effect=LiterouterError("HTTP 429", status=429, temporary=True))
        self._enable_literouter(chat)
        self._set("GEMINI_ENABLED", False)
        self.assertEqual(await bot.ask_gemini((1, 10), "hi"), bot.MSG_RATE_LIMIT)
        self.assertEqual(chat.await_count, 2)

    async def test_literouter_fatal_error(self):
        chat = AsyncMock(side_effect=LiterouterError("HTTP 400", status=400, temporary=False))
        self._enable_literouter(chat)
        self._set("GEMINI_ENABLED", False)
        self.assertEqual(await bot.ask_gemini((1, 11), "hi"), bot.MSG_API_ERROR)
        self.assertEqual(chat.await_count, 1)

    async def test_provider_order_literouter_first(self):
        chat = AsyncMock(return_value=("literouter trước", False))
        self._enable_literouter(chat)
        self._set("AI_PROVIDER_ORDER", ["literouter", "gemini"])
        self.behaviors = {"g-main": ["không được gọi"], "g-fb": []}
        self.assertEqual(await bot.ask_gemini((1, 12), "hi"), "literouter trước")
        self.assertEqual(self.calls, [])

    async def test_literouter_enabled_without_key_is_skipped(self):
        self._set("LITEROUTER_ENABLED", True)  # key vẫn None
        self.behaviors = {"g-main": [self._ClientError(429)], "g-fb": [self._ClientError(429), self._ClientError(429)]}
        self.assertEqual(await bot.ask_gemini((1, 13), "hi"), bot.MSG_RATE_LIMIT)

    async def test_no_provider_available(self):
        self._set("GEMINI_ENABLED", False)
        self.assertEqual(await bot.ask_gemini((1, 14), "hi"), bot.MSG_NO_PROVIDER)

    async def test_describe_ai_providers_has_no_secret(self):
        self._enable_literouter(AsyncMock())
        text = bot.describe_ai_providers()
        self.assertIn("g-main → g-fb", text)
        self.assertIn("lr-model", text)
        self.assertNotIn(TEST_KEY, text)


class ConfigTests(unittest.TestCase):
    def test_defaults_and_order(self):
        self.assertTrue(config.GEMINI_ENABLED)
        self.assertEqual(config.GEMINI_MODELS[0], config.GEMINI_MODEL)
        self.assertEqual(sorted(config.AI_PROVIDER_ORDER), ["gemini", "literouter"])
        self.assertFalse(config.LITEROUTER_ENABLED)
        self.assertEqual(config.LITEROUTER_BASE_URL, "https://literouter.fun/api/v1")

    def test_gemini_model_accepts_comma_list(self):
        # Trường hợp thực tế: người dùng điền cả danh sách vào GEMINI_MODEL.
        import subprocess

        env = {**os.environ, "GEMINI_MODEL": "m1, m2 ,m3", "GEMINI_FALLBACK_MODELS": "m3,m4"}
        code = "import json, config as c; print(json.dumps([c.GEMINI_MODEL, c.GEMINI_MODELS]))"
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, check=True)
        main, models = json.loads(out.stdout)
        self.assertEqual(main, "m1")
        self.assertEqual(models, ["m1", "m2", "m3", "m4"])

        env["GEMINI_MODEL"] = ""
        out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, check=True)
        main, models = json.loads(out.stdout)
        self.assertEqual(main, "gemini-3.5-flash-lite")  # trống → dùng mặc định

    def test_env_parsing(self):
        # Chạy trong process riêng để không đụng vào module config đang dùng bởi các test khác.
        import subprocess

        env = {
            **os.environ,
            "GEMINI_ENABLED": "false",
            "GEMINI_MODEL": "main",
            "GEMINI_FALLBACK_MODELS": " a , main,b,a ",
            "AI_PROVIDER_ORDER": "LiteRouter",
            "LITEROUTER_ENABLED": "true",
            "LITEROUTER_BASE_URL": "https://x.example/v1/",
            "LITEROUTER_MODELS_REFRESH_HOURS": "0",
            "DB_PATH": "/data/conversations.db",
        }
        code = (
            "import json, config as c;"
            "print(json.dumps([c.GEMINI_ENABLED, c.GEMINI_MODELS, c.AI_PROVIDER_ORDER, c.LITEROUTER_ENABLED,"
            "c.LITEROUTER_BASE_URL, c.LITEROUTER_MODELS_REFRESH_HOURS, c.LITEROUTER_CACHE_PATH]))"
        )
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, check=True)
        enabled, models, order, lr_enabled, base, hours, cache = json.loads(out.stdout)
        self.assertFalse(enabled)
        self.assertEqual(models, ["main", "a", "b"])
        self.assertEqual(order, ["literouter", "gemini"])
        self.assertTrue(lr_enabled)
        self.assertEqual(base, "https://x.example/v1")
        self.assertEqual(hours, 1)
        self.assertEqual(cache, os.path.join("/data", "literouter_models.json"))


class AutoChatPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_channels_survive_restart_even_if_only_db_file_is_kept(self):
        import shutil

        from db import Database

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "conversations.db")
            db = Database(path)
            await db.init()
            await db.add_auto_chat_channel(111, 1, 9)
            await db.add_auto_chat_channel(222, 1, 9)
            await db.remove_auto_chat_channel(222)
            # Mô phỏng tắt đột ngột (không close) và chỉ giữ lại file .db chính, không có -wal/-shm.
            copy = os.path.join(tmp, "copied.db")
            shutil.copyfile(path, copy)
            db2 = Database(copy)
            await db2.init()
            self.assertEqual(await db2.load_auto_chat_channels(), [111])
            await db2.close()
            await db.close()

    async def test_channels_survive_normal_reopen(self):
        from db import Database

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "conversations.db")
            db = Database(path)
            await db.init()
            await db.add_auto_chat_channel(333, 1, 9)
            await db.close()
            db2 = Database(path)
            await db2.init()
            self.assertEqual(await db2.load_auto_chat_channels(), [333])
            await db2.close()

    def test_botinfo_has_no_allowed_guild_controls(self):
        import inspect

        source = inspect.getsource(bot)
        for name in ("AllowedGuildsManageView", "AddGuildModal", "RemoveGuildModal", "go_allowed_guilds"):
            self.assertNotIn(name, source)
        self.assertNotIn("Giới hạn server", source)


if __name__ == "__main__":
    unittest.main()
