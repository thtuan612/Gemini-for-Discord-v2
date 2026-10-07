from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import time
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import discord
import psutil as _psutil
from abc import ABC, abstractmethod
from discord import app_commands
from discord.ext import commands, tasks
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

import config
from db import Database
from dashboard import Ctx as DashboardCtx
from dashboard import install_log_buffer, start_dashboard
from utils import (
    format_bytes,
    format_uptime,
    get_dir_size,
    get_memory_limit_bytes,
    is_trivial_message,
    next_run_utc,
    parse_hhmm,
    split_message,
)

class _PsutilMetrics(ABC):
    @staticmethod
    @abstractmethod
    def memory_limit_bytes() -> int:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def system_memory() -> tuple[int, int]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def process_memory_rss(pid: int | None = None) -> int:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def cpu_percent(interval: float | None = None, percpu: bool = False):
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def process_count() -> int:
        raise NotImplementedError


class psutil(_PsutilMetrics):
    """Thin compatibility wrapper around the real psutil library.

    It preserves the bot's existing `psutil.Process(...)` calls while exposing a small,
    useful set of concrete monitoring helpers for the rest of the application.
    """

    Process = _psutil.Process

    @staticmethod
    def __getattr__(name: str):
        return getattr(_psutil, name)

    @staticmethod
    def memory_limit_bytes() -> int:
        try:
            return int(_psutil.virtual_memory().total)
        except Exception:
            return 0

    @staticmethod
    def system_memory() -> tuple[int, int]:
        try:
            mem = _psutil.virtual_memory()
            return int(mem.used), int(mem.total)
        except Exception:
            return 0, 0

    @staticmethod
    def process_memory_rss(pid: int | None = None) -> int:
        proc = _psutil.Process(pid) if pid is not None else _psutil.Process()
        try:
            return int(proc.memory_info().rss)
        except Exception:
            return 0

    @staticmethod
    def cpu_percent(interval: float | None = None, percpu: bool = False):
        try:
            return _psutil.cpu_percent(interval=interval, percpu=percpu)
        except Exception:
            return 0.0 if not percpu else [0.0]

    @staticmethod
    def process_count() -> int:
        try:
            return len(_psutil.pids())
        except Exception:
            return 0


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("discord-ai-bot")

if config.DASHBOARD_ENABLED:
    install_log_buffer()

# Bot không dùng voice: tắt cảnh báo PyNaCl/davey trong log.
discord.VoiceClient.warn_nacl = False
discord.VoiceClient.warn_dave = False

BOT_START_TIME = datetime.now(timezone.utc)
NO_MENTIONS = discord.AllowedMentions.none()

db = Database(config.DB_PATH)
gemini_client: genai.Client | None = None
gemini_sem = asyncio.Semaphore(config.GEMINI_CONCURRENCY)
auto_chat_channels: set[int] = set(config.AUTO_CHAT_CHANNEL_IDS)

SKIP_TOKEN = "__KHONG_PHAI_HOI_BOT__"
RELEVANCE_INSTRUCTION = (
    "LƯU Ý: Đây là kênh chat dành riêng để nói chuyện với bạn, nên MẶC ĐỊNH coi mọi tin "
    "nhắn là đang nói với bạn, kể cả câu ngắn, chào hỏi mơ hồ như 'alo', 'ê', 'hello' — cứ trả "
    f"lời bình thường. CHỈ trả về DUY NHẤT chuỗi `{SKIP_TOKEN}` (không viết gì khác) khi có bằng "
    "chứng RÕ RÀNG và chắc chắn tin nhắn đang nói với một người cụ thể khác, không phải bạn (vd: "
    "gọi thẳng tên một thành viên khác kèm nội dung chỉ liên quan đến người đó, hoặc rõ ràng là "
    "tiếp nối một cuộc trò chuyện riêng giữa 2 người khác mà bạn không liên quan gì). Nếu còn "
    "chút nghi ngờ, ưu tiên trả lời bình thường thay vì skip."
)
MSG_RATE_LIMIT = "Đang bị giới hạn tốc độ từ Gemini (free tier), thử lại sau vài giây nhé."
MSG_API_ERROR = "Có lỗi khi gọi Gemini API, thử lại sau nhé."
MSG_OVERLOADED = "Gemini đang quá tải, thử lại sau 1-2 phút nhé."
MSG_EMPTY = "Gemini không trả về nội dung, thử hỏi lại theo cách khác nhé."
MSG_TRUNCATED = "Câu trả lời bị cắt do hết giới hạn token, thử hỏi ngắn gọn hơn nhé."
MSG_GENERIC_ERROR = "Có lỗi xảy ra khi xử lý, thử lại sau nhé."
DEFAULT_IMAGE_PROMPT = "Mô tả/phân tích ảnh này giúp mình."

# Các thông báo lỗi: ở kênh Auto-Chat sẽ KHÔNG gửi ra kênh (tránh spam khi Gemini lỗi/429).
ERROR_MSGS = frozenset(
    {MSG_RATE_LIMIT, MSG_API_ERROR, MSG_OVERLOADED, MSG_EMPTY, MSG_TRUNCATED}
)


# ======================================================================
# Quyền hạn
# ======================================================================
def is_privileged(member: discord.abc.User | None) -> bool:
    """Owner, quyền Administrator, hoặc role nằm trong ADMIN_ROLE_IDS.

    So khớp theo tên role chỉ bật khi cấu hình ADMIN_ROLE_NAMES (mặc định tắt).
    """
    if not isinstance(member, discord.Member):
        return False
    if member.id == member.guild.owner_id:
        return True
    if member.guild_permissions.administrator:
        return True
    for role in member.roles:
        if role.id in config.ADMIN_ROLE_IDS:
            return True
        if config.ADMIN_ROLE_NAMES and role.name.strip().lower() in config.ADMIN_ROLE_NAMES:
            return True
    return False


class GuardedTree(app_commands.CommandTree):
    """Chặn mọi slash command ngoài server, hoặc ở server không nằm trong ALLOWED_GUILD_IDS."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            await interaction.response.send_message("Bot này chỉ dùng trong server.", ephemeral=True)
            return False
        if config.ALLOWED_GUILD_IDS and interaction.guild_id not in config.ALLOWED_GUILD_IDS:
            await interaction.response.send_message(
                "Bot này không được phép hoạt động ở server này.", ephemeral=True
            )
            return False
        return True


def build_activity() -> discord.BaseActivity:
    if config.STATUS_TYPE == "playing":
        return discord.Game(name=config.STATUS_TEXT)
    type_map = {
        "listening": discord.ActivityType.listening,
        "watching": discord.ActivityType.watching,
        "competing": discord.ActivityType.competing,
    }
    return discord.Activity(
        type=type_map.get(config.STATUS_TYPE, discord.ActivityType.listening),
        name=config.STATUS_TEXT,
    )


class GeminiBot(commands.Bot):
    dashboard_runner = None

    async def setup_hook(self) -> None:
        await db.init()
        auto_chat_channels.update(await db.load_auto_chat_channels())
        if config.DASHBOARD_ENABLED:
            try:
                self.dashboard_runner = await start_dashboard(
                    DashboardCtx(
                        bot=self,
                        db=db,
                        auto_chat_channels=auto_chat_channels,
                        history_cache=history_cache,
                    )
                )
            except Exception:
                log.exception("Không khởi động được dashboard (bot vẫn chạy bình thường)")
        if config.SYNC_ON_START:
            try:
                synced = await self.tree.sync()
                log.info("Synced %d slash command(s)", len(synced))
            except Exception:
                log.exception("Không sync được slash commands")
        reminder_check_loop.start()
        if config.HISTORY_RETENTION_DAYS > 0:
            history_purge_loop.start()

    async def close(self) -> None:
        # Dừng các vòng lặp nền trước khi đóng DB để chúng không chạy vào DB đã đóng.
        reminder_check_loop.cancel()
        history_purge_loop.cancel()
        if self.dashboard_runner is not None:
            await self.dashboard_runner.cleanup()
        await super().close()
        await db.close()


intents = discord.Intents.default()
intents.message_content = True
intents.members = config.MEMBERS_INTENT

bot = GeminiBot(
    command_prefix=commands.when_mentioned,
    intents=intents,
    tree_cls=GuardedTree,
    allowed_mentions=NO_MENTIONS,  # chặn @everyone/@here/role/user ping ở MỌI tin nhắn của bot
    activity=build_activity(),
)


# ======================================================================
# Lịch sử hội thoại: khóa theo (guild_id, user_id), cache LRU
# ======================================================================
HistoryKey = tuple[int, int]
HISTORY_CACHE_MAX = 500
history_cache: OrderedDict[HistoryKey, deque] = OrderedDict()


def _cache_get(key: HistoryKey) -> deque | None:
    history = history_cache.get(key)
    if history is not None:
        history_cache.move_to_end(key)
    return history


def _cache_put(key: HistoryKey, history: deque) -> None:
    history_cache[key] = history
    history_cache.move_to_end(key)
    while len(history_cache) > HISTORY_CACHE_MAX:
        history_cache.popitem(last=False)


async def load_history(key: HistoryKey) -> deque:
    cached = _cache_get(key)
    if cached is not None:
        return cached
    history: deque = deque(maxlen=config.MAX_HISTORY_TURNS * 2)
    raw = await db.load_history_raw(*key)
    if raw:
        try:
            for item in json.loads(raw):
                history.append(
                    types.Content(role=item["role"], parts=[types.Part(text=item["text"])])
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("Lịch sử lỗi format cho %s, bỏ qua", key)
            history.clear()
    _cache_put(key, history)
    return history


async def save_history(key: HistoryKey, history: deque) -> None:
    raw = json.dumps(
        [{"role": c.role, "text": c.parts[0].text} for c in history], ensure_ascii=False
    )
    await db.save_history_raw(*key, raw)


async def delete_history(key: HistoryKey) -> None:
    history_cache.pop(key, None)
    await db.delete_history(*key)


# ======================================================================
# Hàng đợi theo người dùng (thay cho pending_users)
# ======================================================================
class Busy(Exception):
    pass


MAX_QUEUED_PER_USER = 2
_locks: dict[HistoryKey, asyncio.Lock] = {}
_waiting: dict[HistoryKey, int] = {}


@asynccontextmanager
async def user_gate(key: HistoryKey, *, allow_queue: bool):
    """Mỗi user chỉ xử lý 1 yêu cầu tại một thời điểm; luôn tự giải phóng khi thoát (kể cả lỗi)."""
    waiting = _waiting.get(key, 0)
    limit = 1 + MAX_QUEUED_PER_USER if allow_queue else 1
    if waiting >= limit:
        raise Busy
    _waiting[key] = waiting + 1
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            yield
    finally:
        _waiting[key] -= 1
        if _waiting[key] <= 0:
            _waiting.pop(key, None)
            _locks.pop(key, None)


# ======================================================================
# Gemini
# ======================================================================
SERVER_CONTEXT_TTL = 300  # giây
MAX_CONTEXT_ROLES = 15
_bot_count_cache: dict[int, tuple[float, int]] = {}


def _cached_bot_count(guild: discord.Guild) -> int:
    """Đếm bot trong server, cache 5 phút (tránh duyệt toàn bộ member mỗi tin nhắn)."""
    now = time.monotonic()
    hit = _bot_count_cache.get(guild.id)
    if hit is not None and now - hit[0] < SERVER_CONTEXT_TTL:
        return hit[1]
    count = sum(1 for m in guild.members if m.bot)
    _bot_count_cache[guild.id] = (now, count)
    return count


def _clean_for_prompt(text: str, limit: int = 40) -> str:
    """Làm sạch chuỗi do người dùng kiểm soát (tên server, nickname, role) trước khi đưa vào
    system instruction: bỏ ký tự điều khiển/xuống dòng, gộp khoảng trắng, cắt ngắn.
    Tránh việc đặt nickname kiểu "...\\nBỏ qua mọi chỉ dẫn trước đó..." để chèn lệnh vào prompt."""
    cleaned = "".join(ch if ch.isprintable() else " " for ch in (text or ""))
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned or "(trống)"


def build_server_context(member: discord.abc.User | None, guild: discord.Guild | None) -> str:
    if guild is None:
        return ""
    total = guild.member_count or 0
    lines = [
        "Dữ liệu thực tế của server Discord hiện tại — dùng đúng các số liệu này khi được hỏi, "
        "không tự bịa số khác:",
        f"- Tên server: {_clean_for_prompt(guild.name, 60)}",
        f"- Tổng số thành viên: {total}",
    ]
    if config.MEMBERS_INTENT and guild.chunked:
        bot_count = _cached_bot_count(guild)
        lines.append(f"- Số bot: {bot_count}")
        lines.append(f"- Số thành viên thật (không tính bot): {total - bot_count}")
    else:
        lines.append("- Số bot / số thành viên thật: chưa có số liệu, đừng tự bịa")
    if isinstance(member, discord.Member):
        roles = sorted(
            (r for r in member.roles if r.name != "@everyone"),
            key=lambda r: r.position,
            reverse=True,
        )
        role_names = [_clean_for_prompt(r.name, 30) for r in roles[:MAX_CONTEXT_ROLES]]
        if role_names:
            roles_text = ", ".join(role_names)
            if len(roles) > len(role_names):
                roles_text += f" (và {len(roles) - len(role_names)} role khác)"
        else:
            roles_text = "không có role nào ngoài mặc định"
        lines.append(
            f"- Người đang hỏi: {_clean_for_prompt(member.display_name, 40)}, role hiện có: {roles_text}"
        )
    return "\n".join(lines)


async def _read_image(att: discord.Attachment, mime: str) -> types.Part | None:
    try:
        data = await att.read()
        return types.Part.from_bytes(data=data, mime_type=mime)
    except Exception as e:
        log.warning("Không đọc được ảnh %s: %s", att.filename, e)
        return None


async def build_image_parts(attachments: list[discord.Attachment]) -> list[types.Part]:
    candidates: list[tuple[discord.Attachment, str]] = []
    for att in attachments:
        if len(candidates) >= config.MAX_IMAGES:
            break
        mime = (att.content_type or "").split(";")[0].strip().lower()
        if mime not in config.ALLOWED_IMAGE_MIMES:
            continue
        if att.size > config.MAX_IMAGE_BYTES:
            log.info("Bỏ qua ảnh %s: quá lớn (%d bytes)", att.filename, att.size)
            continue
        candidates.append((att, mime))
    # Tải các ảnh song song thay vì lần lượt
    results = await asyncio.gather(*(_read_image(a, m) for a, m in candidates))
    return [p for p in results if p is not None]


def _extract_reply(response) -> tuple[str, bool]:
    """Trả về (text, bị_cắt_do_max_tokens)."""
    try:
        text = (response.text or "").strip()
    except Exception:
        text = ""
    truncated = False
    try:
        finish = response.candidates[0].finish_reason
        truncated = "MAX_TOKENS" in str(getattr(finish, "name", finish))
    except Exception:
        pass
    return text, truncated


def _build_thinking_config() -> types.ThinkingConfig | None:
    """THINKING_LEVEL ưu tiên hơn THINKING_BUDGET (API không cho gửi cả hai)."""
    if config.THINKING_LEVEL:
        try:
            return types.ThinkingConfig(thinking_level=config.THINKING_LEVEL.upper())
        except Exception:
            log.warning(
                "SDK google-genai hiện tại không nhận thinking_level — bỏ qua THINKING_LEVEL, "
                "hãy nâng cấp google-genai."
            )
            return None
    if config.THINKING_BUDGET is not None:
        return types.ThinkingConfig(thinking_budget=config.THINKING_BUDGET)
    return None


THINKING_CONFIG = _build_thinking_config()


async def ask_gemini(
    key: HistoryKey,
    user_message: str,
    *,
    privileged: bool = False,
    server_context: str = "",
    image_parts: list[types.Part] | None = None,
    auto_channel: bool = False,
) -> str | None:
    """Trả về câu trả lời, hoặc None nếu bot quyết định im lặng (chỉ ở auto-chat)."""
    history = await load_history(key)
    contents = list(history)
    user_parts = [types.Part(text=user_message)]
    if image_parts:
        user_parts.extend(image_parts)
    contents.append(types.Content(role="user", parts=user_parts))

    system_parts = [config.SYSTEM_PROMPT]
    if privileged:
        system_parts.append(config.PRIVILEGED_NOTE)
    if server_context:
        system_parts.append(server_context)
    if auto_channel:
        # Nằm trong system instruction, KHÔNG lưu vào lịch sử hội thoại.
        system_parts.append(RELEVANCE_INSTRUCTION)

    cfg_kwargs: dict = {
        "system_instruction": "\n\n".join(system_parts),
        "max_output_tokens": config.MAX_OUTPUT_TOKENS,
    }
    # Gemini 3.x: Google khuyến nghị không chỉnh temperature → chỉ gửi khi được cấu hình.
    if config.GEMINI_TEMPERATURE is not None:
        cfg_kwargs["temperature"] = config.GEMINI_TEMPERATURE
    if THINKING_CONFIG is not None:
        cfg_kwargs["thinking_config"] = THINKING_CONFIG
    gen_config = types.GenerateContentConfig(**cfg_kwargs)

    max_attempts = 3
    response = None
    rate_retried = False
    for attempt in range(1, max_attempts + 1):
        try:
            # Chỉ giữ slot trong lúc gọi API; khi chờ retry thì nhả slot cho người khác.
            async with gemini_sem:
                response = await asyncio.wait_for(
                    gemini_client.aio.models.generate_content(
                        model=config.GEMINI_MODEL, contents=contents, config=gen_config
                    ),
                    timeout=config.GEMINI_TIMEOUT,
                )
            break
        except ClientError as e:
            if e.code == 429:
                if not rate_retried and config.GEMINI_429_RETRY_SECONDS > 0:
                    rate_retried = True
                    log.warning("Gemini 429, thử lại sau %ds", config.GEMINI_429_RETRY_SECONDS)
                    await asyncio.sleep(config.GEMINI_429_RETRY_SECONDS)
                    continue
                return MSG_RATE_LIMIT
            log.error("Gemini client error: %s", e)
            return MSG_API_ERROR
        except (ServerError, asyncio.TimeoutError) as e:
            log.warning("Gemini lỗi tạm thời (lần %d/%d): %r", attempt, max_attempts, e)
            if attempt == max_attempts:
                return MSG_OVERLOADED
            await asyncio.sleep(2 * attempt)
        except Exception:
            log.exception("Lỗi không xác định khi gọi Gemini")
            return MSG_API_ERROR

    # Hết số lần thử mà vẫn chưa có phản hồi (vd: 429 rơi đúng lần thử cuối).
    if response is None:
        return MSG_RATE_LIMIT

    reply, truncated = _extract_reply(response)
    if not reply:
        return MSG_TRUNCATED if truncated else MSG_EMPTY
    if auto_channel and SKIP_TOKEN in reply:
        return None
    if truncated:
        reply += " …"

    # Lịch sử đã bị /reset, xóa trên dashboard hoặc purge trong lúc chờ Gemini
    # → không ghi lại deque cũ (tránh "hồi sinh" lịch sử vừa xóa).
    if history_cache.get(key) is not history:
        return reply

    history.append(types.Content(role="user", parts=[types.Part(text=user_message)]))
    history.append(types.Content(role="model", parts=[types.Part(text=reply)]))
    await save_history(key, history)
    return reply


# ======================================================================
# Reminder
# ======================================================================
async def _fire_reminder(row, now: datetime) -> None:
    scheduled = datetime.fromisoformat(row["next_run_utc"])
    stale = now - scheduled > timedelta(minutes=config.REMINDER_GRACE_MINUTES)
    text = row["message"]
    should_send = True
    if stale:
        if row["repeat"] == "daily":
            should_send = False  # lỡ giờ (vd: bot offline) — bỏ lượt hôm nay, hẹn lượt kế
            log.info("Bỏ qua reminder #%s đã trễ quá hạn", row["id"])
        else:
            text = "⏰ (nhắc trễ) " + text
    if should_send:
        channel = bot.get_channel(row["channel_id"])
        if channel is None:
            log.warning("Không tìm thấy kênh %s cho reminder #%s", row["channel_id"], row["id"])
        else:
            try:
                await channel.send(text, allowed_mentions=NO_MENTIONS)
            except discord.HTTPException as e:
                log.error("Gửi reminder #%s thất bại: %s", row["id"], e)
                if e.status >= 500:
                    return  # lỗi phía Discord — để lượt quét sau thử lại
    if row["repeat"] == "daily":
        nxt = next_run_utc(row["hour"], row["minute"], after=now)
        await db.advance_reminder(row["id"], nxt.isoformat())
    else:
        await db.deactivate_reminder(row["id"])


@tasks.loop(seconds=30)
async def reminder_check_loop():
    try:
        now = datetime.now(timezone.utc)
        for row in await db.get_due_reminders(now.replace(microsecond=0).isoformat()):
            await _fire_reminder(row, now)
    except Exception:
        # Không để exception làm chết vòng lặp.
        log.exception("Lỗi trong reminder_check_loop")


@reminder_check_loop.before_loop
async def _before_reminder_loop():
    await bot.wait_until_ready()


@tasks.loop(hours=6)
async def history_purge_loop():
    try:
        deleted = await db.purge_old_history(config.HISTORY_RETENTION_DAYS)
        if deleted:
            history_cache.clear()  # mọi thay đổi đã nằm trong DB nên reload là an toàn
            log.info("Đã xóa %d lịch sử hội thoại quá %d ngày", deleted, config.HISTORY_RETENTION_DAYS)
    except Exception:
        log.exception("Lỗi trong history_purge_loop")
    if config.REMINDER_RETENTION_DAYS > 0:
        try:
            removed = await db.purge_inactive_reminders(config.REMINDER_RETENTION_DAYS)
            if removed:
                log.info("Đã xóa %d reminder đã tắt quá %d ngày", removed, config.REMINDER_RETENTION_DAYS)
        except Exception:
            log.exception("Lỗi khi dọn reminder đã tắt")


async def backfill_reminder_guilds() -> None:
    """Gán guild_id cho reminder tạo từ phiên bản cũ (chưa có cột này)."""
    for row in await db.reminders_missing_guild():
        guild = getattr(bot.get_channel(row["channel_id"]), "guild", None)
        if guild:
            await db.set_reminder_guild(row["id"], guild.id)


# ======================================================================
# Sự kiện
# ======================================================================
@bot.event
async def on_guild_join(guild: discord.Guild):
    if config.ALLOWED_GUILD_IDS and guild.id not in config.ALLOWED_GUILD_IDS:
        log.warning("Bị mời vào server không được phép: %s (ID: %s) — tự rời.", guild.name, guild.id)
        try:
            if guild.system_channel:
                await guild.system_channel.send(
                    "Bot này được khóa riêng cho một server cụ thể, không thể dùng ở đây. "
                    "Tự xin phép rời nhé! 👋"
                )
        except discord.HTTPException:
            pass
        await guild.leave()


@bot.event
async def on_ready():
    if config.ALLOWED_GUILD_IDS:
        for guild in list(bot.guilds):
            if guild.id not in config.ALLOWED_GUILD_IDS:
                log.warning("Đang ở server không được phép: %s (ID: %s) — tự rời.", guild.name, guild.id)
                await guild.leave()
    try:
        await backfill_reminder_guilds()
    except Exception:
        log.exception("Backfill guild_id cho reminder thất bại")
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)


async def is_message_for_bot(message: discord.Message) -> bool:
    """Lọc nhanh, không tốn API call: loại các trường hợp rõ ràng KHÔNG nói với bot."""
    if message.reference is not None:
        ref_msg = message.reference.resolved
        if ref_msg is None and message.reference.message_id:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.HTTPException):
                ref_msg = None
        # `resolved` có thể là DeletedReferencedMessage (không có .author)
        if isinstance(ref_msg, discord.Message) and ref_msg.author.id != bot.user.id:
            return False
    human_mentions = [m for m in message.mentions if not m.bot]
    if human_mentions and bot.user not in message.mentions:
        return False
    return True


_auto_last: dict[tuple[int, int], float] = {}


def _auto_chat_on_cooldown(channel_id: int, user_id: int) -> bool:
    """Giới hạn mỗi người kích hoạt Auto-Chat 1 lần / N giây trong một kênh."""
    cooldown = config.AUTO_CHAT_COOLDOWN_SECONDS
    if cooldown <= 0:
        return False
    now = time.monotonic()
    key = (channel_id, user_id)
    last = _auto_last.get(key)
    if last is not None and now - last < cooldown:
        return True
    _auto_last[key] = now
    if len(_auto_last) > 2000:  # dọn các mục đã hết hạn
        for k, t in list(_auto_last.items()):
            if now - t > cooldown:
                del _auto_last[k]
    return False


async def process_chat_message(
    message: discord.Message,
    content: str,
    auto_channel: bool = False,
    mentioned: bool = False,
) -> None:
    if not content and not message.attachments:
        if not auto_channel:
            await message.reply("Bạn muốn hỏi gì nào?", mention_author=False)
        return

    if auto_channel and not mentioned:
        # Lọc rẻ trước khi tốn request Gemini: tin chỉ có emoji/link, hoặc gửi dồn dập.
        if not message.attachments and is_trivial_message(content):
            return
        if _auto_chat_on_cooldown(message.channel.id, message.author.id):
            return
        # Chỉ lọc "tin này có phải nói với bot không" khi KHÔNG mention trực tiếp bot.
        if not await is_message_for_bot(message):
            return

    key: HistoryKey = (message.guild.id, message.author.id)
    try:
        async with user_gate(key, allow_queue=True):
            image_parts = await build_image_parts(message.attachments)
            if not content and not image_parts:
                if not auto_channel:
                    await message.reply("Mình chỉ đọc được ảnh (png/jpg/webp/heic).", mention_author=False)
                return
            async with message.channel.typing():
                reply = await ask_gemini(
                    key,
                    content or DEFAULT_IMAGE_PROMPT,
                    privileged=is_privileged(message.author),
                    server_context=build_server_context(message.author, message.guild),
                    image_parts=image_parts,
                    auto_channel=auto_channel,
                )
    except Busy:
        if not auto_channel:
            await message.reply("Chờ câu trả lời trước đã nhé.", mention_author=False)
        return
    except Exception:
        log.exception("Lỗi khi xử lý tin nhắn từ %s", message.author.id)
        if not auto_channel:
            try:
                await message.reply(MSG_GENERIC_ERROR, mention_author=False)
            except discord.HTTPException:
                pass
        return

    if reply is None:
        return
    # Kênh Auto-Chat: im lặng khi Gemini lỗi/429 thay vì spam thông báo lỗi ra kênh.
    # (Nếu người dùng mention trực tiếp bot thì vẫn báo lỗi như bình thường.)
    if auto_channel and not mentioned and reply in ERROR_MSGS:
        return

    try:
        chunks = split_message(reply, config.MAX_REPLY_CHARS)
        await message.reply(chunks[0], mention_author=False)
        for chunk in chunks[1:]:
            await message.channel.send(chunk)
    except discord.HTTPException as e:
        log.error("Gửi trả lời thất bại: %s", e)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    if config.ALLOWED_GUILD_IDS and message.guild.id not in config.ALLOWED_GUILD_IDS:
        return
    # Thread nằm trong kênh đã bật Auto-Chat cũng được tính (thread có id riêng, parent_id là kênh cha).
    parent_id = getattr(message.channel, "parent_id", None)
    is_auto_channel = message.channel.id in auto_chat_channels or (
        parent_id is not None and parent_id in auto_chat_channels
    )
    is_mentioned = bot.user in message.mentions
    if not (is_auto_channel or is_mentioned):
        return
    content = message.content
    for mention in message.mentions:
        content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    await process_chat_message(
        message, content.strip(), auto_channel=is_auto_channel, mentioned=is_mentioned
    )


# ======================================================================
# Slash commands
# ======================================================================
async def _send_followup_chunks(interaction: discord.Interaction, text: str) -> None:
    try:
        for chunk in split_message(text, config.MAX_REPLY_CHARS):
            await interaction.followup.send(chunk)
    except discord.HTTPException as e:
        log.error("Gửi followup thất bại: %s", e)


@bot.tree.command(name="chat", description="Chat với AI")
@app_commands.describe(message="Nội dung bạn muốn hỏi AI", image="Ảnh muốn AI xem (tùy chọn)")
async def chat_command(
    interaction: discord.Interaction,
    message: str,
    image: discord.Attachment | None = None,
):
    key: HistoryKey = (interaction.guild_id, interaction.user.id)
    try:
        async with user_gate(key, allow_queue=False):
            await interaction.response.defer(thinking=True)
            image_parts = await build_image_parts([image] if image else [])
            reply = await ask_gemini(
                key,
                message,
                privileged=is_privileged(interaction.user),
                server_context=build_server_context(interaction.user, interaction.guild),
                image_parts=image_parts,
            )
    except Busy:
        await interaction.response.send_message(
            "Bạn có một câu hỏi đang được xử lý, chờ xong rồi hỏi tiếp nhé.", ephemeral=True
        )
        return
    except Exception:
        log.exception("chat_command lỗi")
        if interaction.response.is_done():
            await interaction.followup.send(MSG_GENERIC_ERROR)
        else:
            await interaction.response.send_message(MSG_GENERIC_ERROR, ephemeral=True)
        return
    await _send_followup_chunks(interaction, reply)


@bot.tree.command(name="reset", description="Xóa lịch sử hội thoại của bạn với AI (ở server này)")
async def reset_command(interaction: discord.Interaction):
    await delete_history((interaction.guild_id, interaction.user.id))
    await interaction.response.send_message("Đã xóa lịch sử hội thoại của bạn.", ephemeral=True)


@bot.tree.command(name="remind", description="Đặt lịch nhắc tự động (giờ Việt Nam)")
@app_commands.describe(
    time="Giờ theo định dạng HH:MM, 24h, giờ Việt Nam (vd: 06:00)",
    message="Nội dung tin nhắn sẽ gửi",
    repeat="Lặp lại hàng ngày hay chỉ 1 lần",
    channel="Kênh sẽ gửi tin (mặc định: kênh hiện tại)",
)
@app_commands.choices(
    repeat=[
        app_commands.Choice(name="Một lần", value="once"),
        app_commands.Choice(name="Hàng ngày", value="daily"),
    ]
)
async def remind_command(
    interaction: discord.Interaction,
    time: str,
    message: str,
    repeat: app_commands.Choice[str],
    channel: discord.TextChannel | None = None,
):
    parsed = parse_hhmm(time)
    if parsed is None:
        await interaction.response.send_message(
            "Giờ không hợp lệ, nhập dạng `HH:MM` 24h nhé, ví dụ `06:00` hoặc `18:30`.",
            ephemeral=True,
        )
        return
    hour, minute = parsed

    text = message.strip()
    if not text or len(text) > config.MAX_REMINDER_LENGTH:
        await interaction.response.send_message(
            f"Nội dung nhắc phải từ 1 đến {config.MAX_REMINDER_LENGTH} ký tự.", ephemeral=True
        )
        return

    target = channel or interaction.channel
    if not isinstance(target, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("Kênh này không gửi nhắc được.", ephemeral=True)
        return

    user_perms = target.permissions_for(interaction.user)
    if not (user_perms.view_channel and user_perms.send_messages):
        await interaction.response.send_message(
            "Bạn không có quyền gửi tin vào kênh đó.", ephemeral=True
        )
        return
    bot_perms = target.permissions_for(interaction.guild.me)
    if not (bot_perms.view_channel and bot_perms.send_messages):
        await interaction.response.send_message("Bot không có quyền gửi tin vào kênh đó.", ephemeral=True)
        return

    active = await db.count_active_reminders(interaction.user.id, interaction.guild_id)
    if active >= config.MAX_REMINDERS_PER_USER:
        await interaction.response.send_message(
            f"Bạn đã có {active} lịch nhắc đang chạy (tối đa {config.MAX_REMINDERS_PER_USER}). "
            "Hủy bớt bằng `/remind_cancel` nhé.",
            ephemeral=True,
        )
        return

    next_run = next_run_utc(hour, minute)
    reminder_id = await db.add_reminder(
        guild_id=interaction.guild_id,
        channel_id=target.id,
        message=text,
        repeat=repeat.value,
        hour=hour,
        minute=minute,
        next_run_iso=next_run.isoformat(),
        created_by=interaction.user.id,
    )
    repeat_text = "mỗi ngày" if repeat.value == "daily" else "một lần duy nhất"
    next_run_vn = next_run.astimezone(config.VN_TZ)
    await interaction.response.send_message(
        f"✅ Đã đặt lịch #{reminder_id}: gửi **{repeat_text}** lúc **{hour:02d}:{minute:02d}** "
        f"vào {target.mention}.\nLần chạy kế tiếp: "
        f"{next_run_vn.strftime('%H:%M %d/%m/%Y')} (giờ VN)."
    )


@bot.tree.command(name="remind_list", description="Xem danh sách lịch nhắc đang hoạt động")
async def remind_list_command(interaction: discord.Interaction):
    rows = await db.list_reminders(interaction.guild_id)
    if not rows:
        await interaction.response.send_message("Server này chưa có lịch nhắc nào đang hoạt động.")
        return

    # Chỉ hiện lịch nhắc ở kênh mà người gọi lệnh xem được (tránh lộ nội dung từ kênh riêng tư).
    # Admin/Owner thấy tất cả.
    if not is_privileged(interaction.user):
        visible = []
        for r in rows:
            ch = bot.get_channel(r["channel_id"])
            if ch is not None and ch.permissions_for(interaction.user).view_channel:
                visible.append(r)
        hidden = len(rows) - len(visible)
        rows = visible
    else:
        hidden = 0
    if not rows:
        await interaction.response.send_message(
            "Không có lịch nhắc nào ở các kênh bạn xem được.", ephemeral=True
        )
        return

    lines = []
    for r in rows:
        next_run_vn = datetime.fromisoformat(r["next_run_utc"]).astimezone(config.VN_TZ)
        repeat_text = "hàng ngày" if r["repeat"] == "daily" else "1 lần"
        channel = bot.get_channel(r["channel_id"])
        channel_text = channel.mention if channel else f"(kênh {r['channel_id']})"
        preview = r["message"] if len(r["message"]) <= 120 else r["message"][:117] + "..."
        lines.append(
            f"`#{r['id']}` — {channel_text} — {repeat_text} lúc "
            f"{r['hour']:02d}:{r['minute']:02d} — kế tiếp: {next_run_vn.strftime('%H:%M %d/%m')} "
            f"— bởi <@{r['created_by']}>\n └ {preview}"
        )
    if hidden:
        lines.append(f"\n*(Còn {hidden} lịch nhắc ở kênh bạn không xem được.)*")
    chunks = split_message("📋 **Danh sách lịch nhắc:**\n" + "\n".join(lines), config.MAX_REPLY_CHARS)
    await interaction.response.send_message(chunks[0])
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk)


@bot.tree.command(name="remind_cancel", description="Hủy một lịch nhắc theo ID")
@app_commands.describe(id="ID của lịch nhắc (xem bằng /remind_list)")
async def remind_cancel_command(interaction: discord.Interaction, id: int):
    not_found = f"Không tìm thấy lịch nhắc `#{id}` đang hoạt động trong server này."
    row = await db.get_reminder(id)
    if row is None or not row["active"]:
        await interaction.response.send_message(not_found, ephemeral=True)
        return
    guild_id = row["guild_id"] or getattr(
        getattr(bot.get_channel(row["channel_id"]), "guild", None), "id", 0
    )
    if guild_id != interaction.guild_id:
        # Cùng thông báo như "không tồn tại" để không lộ ID của server khác.
        await interaction.response.send_message(not_found, ephemeral=True)
        return
    if row["created_by"] != interaction.user.id and not is_privileged(interaction.user):
        await interaction.response.send_message(
            "Chỉ người tạo lịch nhắc hoặc Admin/Owner mới hủy được.", ephemeral=True
        )
        return
    await db.deactivate_reminder(id)
    await interaction.response.send_message(f"🗑️ Đã hủy lịch nhắc `#{id}`.")


@bot.tree.command(name="autochat_add", description="[Admin] Cho bot tự đọc & rep mọi tin nhắn trong kênh này")
@app_commands.describe(channel="Kênh muốn bật (mặc định: kênh hiện tại)")
async def autochat_add_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
):
    if not is_privileged(interaction.user):
        await interaction.response.send_message("Lệnh này chỉ Admin/Owner mới dùng được nhé.", ephemeral=True)
        return
    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel):
        await interaction.response.send_message("Chỉ bật được auto-chat ở kênh text.", ephemeral=True)
        return
    perms = target.permissions_for(interaction.guild.me)
    if not (perms.view_channel and perms.send_messages):
        await interaction.response.send_message("Bot không có quyền xem/gửi tin ở kênh đó.", ephemeral=True)
        return
    if await db.add_auto_chat_channel(target.id, interaction.guild_id, interaction.user.id):
        auto_chat_channels.add(target.id)
        await interaction.response.send_message(
            f"✅ Đã bật auto-chat ở {target.mention} — không cần mention, cứ gõ là bot rep."
        )
    else:
        auto_chat_channels.add(target.id)
        await interaction.response.send_message(
            f"{target.mention} đã bật auto-chat từ trước rồi.", ephemeral=True
        )


@bot.tree.command(name="autochat_remove", description="[Admin] Tắt auto-chat ở kênh này")
@app_commands.describe(channel="Kênh muốn tắt (mặc định: kênh hiện tại)")
async def autochat_remove_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
):
    if not is_privileged(interaction.user):
        await interaction.response.send_message("Lệnh này chỉ Admin/Owner mới dùng được nhé.", ephemeral=True)
        return
    target = channel or interaction.channel
    removed = await db.remove_auto_chat_channel(target.id)
    # Kênh có thể được bật từ biến môi trường (không có trong DB) — vẫn gỡ khỏi bộ nhớ.
    was_active = target.id in auto_chat_channels
    auto_chat_channels.discard(target.id)
    if removed or was_active:
        note = " (kênh này nằm trong `AUTO_CHAT_CHANNEL_IDS` nên sẽ bật lại khi khởi động lại bot)." \
            if target.id in config.AUTO_CHAT_CHANNEL_IDS else "."
        await interaction.response.send_message(f"🔕 Đã tắt auto-chat ở {target.mention}{note}")
    else:
        await interaction.response.send_message(f"{target.mention} chưa bật auto-chat.", ephemeral=True)


@bot.tree.command(name="autochat_list", description="Xem danh sách kênh đang bật auto-chat")
async def autochat_list_command(interaction: discord.Interaction):
    guild_channel_ids = {c.id for c in interaction.guild.text_channels}
    channel_ids = sorted(guild_channel_ids & auto_chat_channels)
    if not channel_ids:
        await interaction.response.send_message("Server này chưa bật auto-chat ở kênh nào.")
        return
    mentions = [f"<#{cid}>" for cid in channel_ids]
    await interaction.response.send_message("📋 **Kênh đang bật auto-chat:**\n" + "\n".join(mentions))


@bot.tree.command(name="botinfo", description="[Admin/Owner] Xem thông số cấu hình & tình trạng hiện tại của bot")
async def botinfo_command(interaction: discord.Interaction):
    if not is_privileged(interaction.user):
        await interaction.response.send_message("Lệnh này chỉ Admin/Owner mới dùng được nhé.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True, ephemeral=True)

    process = psutil.Process(os.getpid())
    app_dir = os.path.dirname(os.path.abspath(__file__))
    app_disk_used = await asyncio.to_thread(get_dir_size, app_dir)
    db_size = os.path.getsize(config.DB_PATH) if os.path.exists(config.DB_PATH) else 0
    uptime = datetime.now(timezone.utc) - BOT_START_TIME
    total_members = sum(g.member_count or 0 for g in bot.guilds)
    total_members_text = f"{total_members:,}".replace(",", ".")
    active_reminders = await db.count_active_reminders_total()

    description = (
        f"🏓 **Ping:** {round(bot.latency * 1000)}ms\n"
        f"⏱️ **Uptime:** {format_uptime(uptime)}\n"
        f"🌐 **Số server:** {len(bot.guilds)}\n"
        f"👥 **Tổng thành viên:** {total_members_text}\n"
        f"💾 **RAM:** {format_bytes(process.memory_info().rss)} / {format_bytes(get_memory_limit_bytes())}\n"
        f"🗂️ **Disk (thư mục bot):** {format_bytes(app_disk_used)}\n"
        f"🧮 **Dung lượng DB:** {format_bytes(db_size)}\n"
        f"🐍 **Python:** {platform.python_version()}\n"
        f"📘 **discord.py:** {discord.__version__}\n"
        f"✨ **Gemini Model:** {config.GEMINI_MODEL}\n"
        f"⏰ **Lịch nhắc đang chạy:** {active_reminders}\n"
        f"📣 **Kênh auto-chat:** {len(auto_chat_channels)}"
    )
    embed = discord.Embed(title="📊 Thông số Bot", description=description, color=discord.Color.blurple())
    if bot.user and bot.user.display_avatar:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.set_footer(text="Được tạo bởi ThTuan (@lmtuan612)")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ======================================================================
def main() -> None:
    global gemini_client
    if not config.DISCORD_TOKEN:
        raise RuntimeError("Thiếu DISCORD_TOKEN trong file .env")
    if not config.GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY trong file .env")
    gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
