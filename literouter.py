"""Literouter (OpenAI-compatible API): gọi chat/completions và tự quản lý danh sách model.

- Danh sách model lấy từ `GET {base_url}/models`, KHÔNG hardcode.
- Làm mới định kỳ (mặc định 6 giờ) và lưu cache ra file; khi API tạm ngừng thì dùng cache.
- API Key chỉ đọc từ biến môi trường (config.LITEROUTER_API_KEY), không bao giờ ghi log.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any, Iterable, Sequence

import aiohttp

import config

log = logging.getLogger("discord-ai-bot.literouter")

# Khi làm mới thất bại (API sập), thử lại sau tối đa chừng này giây thay vì chờ cả chu kỳ.
RETRY_AFTER_FAIL_SECONDS = 900


class LiterouterError(Exception):
    """Lỗi khi gọi Literouter. `temporary=True` = đáng thử model/provider khác (429, 5xx, timeout, mất kết nối)."""

    def __init__(self, message: str, *, status: int | None = None, temporary: bool = False):
        super().__init__(message)
        self.status = status
        self.temporary = temporary


def parse_models(payload: Any) -> list[str]:
    """Rút danh sách id model từ phản hồi `/models` (chuẩn OpenAI: {"data": [{"id": ...}]}).

    Chấp nhận thêm vài biến thể: khóa "models", list thuần, phần tử là chuỗi.
    Giữ nguyên thứ tự, bỏ trùng và giá trị rỗng.
    """
    items: Any = payload
    if isinstance(payload, dict):
        items = payload.get("data", payload.get("models"))
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name")
        else:
            model_id = None
        if not isinstance(model_id, str):
            continue
        model_id = model_id.strip()
        if model_id and model_id not in seen:
            seen.add(model_id)
            result.append(model_id)
    return result


def build_messages(
    system: str,
    history: Iterable[tuple[str, str]],
    user_text: str,
    images: Sequence[tuple[str, bytes]] = (),
) -> list[dict]:
    """Đổi system prompt + lịch sử + tin nhắn hiện tại (+ ảnh) sang định dạng OpenAI chat.

    `history`: (role, text) với role kiểu Gemini ("user" / "model").
    `images`: (mime_type, bytes) — gửi dưới dạng data URL trong content part `image_url`.
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    for role, text in history:
        messages.append({"role": "assistant" if role == "model" else "user", "content": text})
    if images:
        content: Any = [{"type": "text", "text": user_text}]
        for mime, data in images:
            b64 = base64.b64encode(data).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    else:
        content = user_text
    messages.append({"role": "user", "content": content})
    return messages


def _error_detail(text: str) -> str:
    """Rút thông điệp lỗi ngắn gọn từ body phản hồi (không bao giờ chứa header/API key)."""
    try:
        data = json.loads(text)
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            err = err.get("message")
        if isinstance(err, str) and err.strip():
            return err.strip()[:200]
    except ValueError:
        pass
    return text.strip()[:200]


def _extract_content(data: Any) -> tuple[str, bool]:
    """Trả về (text, bị_cắt_do_max_tokens) từ phản hồi chat/completions."""
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError):
        return "", False
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # một số gateway trả content dạng list các part
        content = "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)
        )
    text = content.strip() if isinstance(content, str) else ""
    return text, choice.get("finish_reason") == "length"


class LiterouterClient:
    def __init__(self) -> None:
        self.models: list[str] = []
        self.fetched_at: float | None = None  # epoch của lần lấy danh sách thành công gần nhất
        self._session: aiohttp.ClientSession | None = None
        self._task: asyncio.Task | None = None
        self._warned_missing_model = False

    # ------------------------------------------------------------------
    # Trạng thái
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return bool(config.LITEROUTER_ENABLED and config.LITEROUTER_API_KEY)

    def resolve_model(self) -> str | None:
        """Model dùng để chat: LITEROUTER_MODEL nếu có; nếu để trống thì model đầu tiên trong danh sách."""
        configured = config.LITEROUTER_MODEL
        if configured:
            if self.models and configured not in self.models and not self._warned_missing_model:
                self._warned_missing_model = True
                log.warning(
                    "LITEROUTER_MODEL=%r không có trong danh sách /models hiện tại — vẫn thử dùng theo cấu hình.",
                    configured,
                )
            return configured
        return self.models[0] if self.models else None

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if config.LITEROUTER_API_KEY:
            headers["Authorization"] = f"Bearer {config.LITEROUTER_API_KEY}"
        return headers

    async def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        url = f"{config.LITEROUTER_BASE_URL}{path}"
        try:
            async with self._get_session().request(
                method,
                url,
                json=payload,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=config.LITEROUTER_TIMEOUT),
            ) as resp:
                status = resp.status
                text = await resp.text()
        except asyncio.TimeoutError as e:
            raise LiterouterError("timeout", temporary=True) from e
        except aiohttp.ClientError as e:
            raise LiterouterError(f"lỗi kết nối ({type(e).__name__})", temporary=True) from e

        if status != 200:
            raise LiterouterError(
                f"HTTP {status}: {_error_detail(text)}",
                status=status,
                temporary=status in (408, 425, 429) or status >= 500,
            )
        try:
            return json.loads(text)
        except ValueError as e:
            raise LiterouterError("phản hồi không phải JSON", status=status, temporary=True) from e

    async def chat(self, messages: list[dict], *, model: str) -> tuple[str, bool]:
        """Gọi /chat/completions. Trả về (text, bị_cắt_do_max_tokens)."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": config.MAX_OUTPUT_TOKENS,
        }
        if config.GEMINI_TEMPERATURE is not None:
            payload["temperature"] = config.GEMINI_TEMPERATURE
        data = await self._request("POST", "/chat/completions", payload)
        return _extract_content(data)

    # ------------------------------------------------------------------
    # Danh sách model + cache
    # ------------------------------------------------------------------
    def load_cache(self) -> bool:
        path = config.LITEROUTER_CACHE_PATH
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            models = parse_models(data.get("models"))
            fetched_at = data.get("fetched_at")
            fetched_at = float(fetched_at) if isinstance(fetched_at, (int, float)) else None
        except FileNotFoundError:
            return False
        except (OSError, ValueError, AttributeError) as e:
            log.warning("Không đọc được cache model Literouter (%s): %s", path, type(e).__name__)
            return False
        if not models:
            return False
        self.models = models
        self.fetched_at = fetched_at
        log.info("Literouter: nạp %d model từ cache", len(models))
        return True

    def _save_cache(self) -> None:
        path = config.LITEROUTER_CACHE_PATH
        tmp = f"{path}.tmp"
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"fetched_at": self.fetched_at, "models": self.models}, f, ensure_ascii=False)
            os.replace(tmp, path)  # ghi nguyên tử, tránh file cache dở dang
        except OSError as e:
            log.warning("Không ghi được cache model Literouter (%s): %s", path, type(e).__name__)

    async def refresh(self) -> bool:
        """Lấy lại danh sách model. Thất bại thì giữ nguyên danh sách/cache hiện có."""
        try:
            models = parse_models(await self._request("GET", "/models"))
        except LiterouterError as e:
            log.warning("Literouter: không lấy được /models (%s) — dùng %d model đang có", e, len(self.models))
            return False
        if not models:
            log.warning("Literouter: /models trả về danh sách rỗng — giữ nguyên %d model đang có", len(self.models))
            return False
        self.models = models
        self.fetched_at = time.time()
        await asyncio.to_thread(self._save_cache)
        log.info("Literouter: đã cập nhật %d model", len(models))
        return True

    async def _refresh_loop(self) -> None:
        interval = max(1, config.LITEROUTER_MODELS_REFRESH_HOURS) * 3600
        delay = 0.0
        if self.models and self.fetched_at:
            # Cache còn mới thì chưa cần gọi API ngay.
            delay = max(0.0, interval - (time.time() - self.fetched_at))
        while True:
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                ok = await self.refresh()
            except Exception:
                log.exception("Literouter: lỗi không mong đợi khi làm mới model")
                ok = False
            delay = interval if ok else min(interval, RETRY_AFTER_FAIL_SECONDS)

    def start(self) -> None:
        """Nạp cache rồi chạy tác vụ nền làm mới danh sách model. Gọi trong event loop."""
        if self._task is not None and not self._task.done():
            return
        self.load_cache()
        self._task = asyncio.create_task(self._refresh_loop(), name="literouter-refresh")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None


client = LiterouterClient()
