from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import time
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

import config
import literouter
from channel_context import ChannelContext, REFERENCE_UNSET
import botinfo
from botinfo import BotInfoMainView, build_botinfo_embed
from db import Database
from prompt_security import PROMPT_SECURITY_INSTRUCTION, build_untrusted_payload
from utils import (
    is_trivial_message,
    split_message,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("discord-ai-bot")

# Bot không dùng voice: tắt cảnh báo PyNaCl/davey trong log.
discord.VoiceClient.warn_nacl = False
discord.VoiceClient.warn_dave = False

BOT_START_TIME = datetime.now(timezone.utc)
NO_MENTIONS = discord.AllowedMentions.none()

db = Database(config.DB_PATH)
gemini_client: genai.Client | None = None
gemini_sem = asyncio.Semaphore(config.GEMINI_CONCURRENCY)
auto_chat_channels: set[int] = set(config.AUTO_CHAT_CHANNEL_IDS)
allowed_guild_ids: set[int] = set(config.ALLOWED_GUILD_IDS)

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

MSG_RATE_LIMIT = "Đang bị giới hạn tốc độ từ AI, thử lại sau vài giây nhé."
MSG_API_ERROR = "Có lỗi khi gọi AI API, thử lại sau nhé."
MSG_OVERLOADED = "AI đang quá tải, thử lại sau 1-2 phút nhé."
MSG_EMPTY = "AI không trả về nội dung, thử hỏi lại theo cách khác nhé."
MSG_NO_PROVIDER = "Chưa có nhà cung cấp AI nào sẵn sàng, nhờ admin kiểm tra cấu hình nhé."
MSG_TRUNCATED = "Câu trả lời bị cắt do hết giới hạn token, thử hỏi ngắn gọn hơn nhé."
MSG_GENERIC_ERROR = "Có lỗi xảy ra khi xử lý, thử lại sau nhé."
DEFAULT_IMAGE_PROMPT = "Mô tả/phân tích ảnh này giúp mình."


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
    """Chặn mọi slash command ngoài server, hoặc ở server không nằm trong allowed_guild_ids."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            await interaction.response.send_message("Bot này chỉ dùng trong server.", ephemeral=True)
            return False
        if allowed_guild_ids and interaction.guild_id not in allowed_guild_ids:
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
    async def setup_hook(self) -> None:
        await db.init()
        db_channels = await db.load_auto_chat_channels()
        auto_chat_channels.update(db_channels)
        log.info(
            "Auto-chat: %d kênh từ DB (%s) + %d kênh từ .env → tổng %d kênh",
            len(db_channels), os.path.abspath(config.DB_PATH), len(config.AUTO_CHAT_CHANNEL_IDS),
            len(auto_chat_channels),
        )
        allowed_guild_ids.update(await db.load_allowed_guilds())
        if config.SYNC_ON_START:
            try:
                synced = await self.tree.sync()
                log.info("Synced %d slash command(s)", len(synced))
            except Exception:
                log.exception("Không sync được slash commands")
        if config.HISTORY_RETENTION_DAYS > 0:
            history_purge_loop.start()
        if literouter.client.available:
            literouter.client.start()  # nạp cache + làm mới danh sách model định kỳ

    async def close(self) -> None:
        await super().close()
        await literouter.client.stop()
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
    # Chỉ lưu các turn thuần text (loại bỏ turn có ảnh) — ảnh không serialize được và
    # khi reload sẽ thiếu context ảnh, nhưng còn hơn để role là MagicMock crash JSON.
    serializable = [
        {"role": c.role, "text": c.parts[0].text}
        for c in history
        if c.parts and getattr(c.parts[0], "text", None) is not None
    ]
    raw = json.dumps(serializable, ensure_ascii=False)
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
    # Đọc và tăng _waiting trước khi acquire lock — không có await ở đủy nên
    # không bị interrupt bởi asyncio (single-threaded).
    waiting = _waiting.get(key, 0)
    limit = 1 + MAX_QUEUED_PER_USER if allow_queue else 1
    if waiting >= limit:
        raise Busy
    _waiting[key] = waiting + 1
    # setdefault an toàn vì không có await — luôn trả về cùng một Lock cho cùng một key.
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            yield
    finally:
        _waiting[key] -= 1
        if _waiting[key] <= 0:
            # Chỉ dọn khi không còn ai đang chờ — tránh xóa lock mà coroutine khác
            # đã lấy về biến cục bộ đang chờ acquire.
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


def build_server_context(member: discord.abc.User | None, guild: discord.Guild | None) -> str:
    if guild is None:
        return ""
    total = guild.member_count or 0
    lines = [
        "Dữ liệu thực tế của server Discord hiện tại — dùng đúng các số liệu này khi được hỏi, "
        "không tự bịa số khác:",
        f"- Tên server: {guild.name}",
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
        role_names = [r.name for r in roles[:MAX_CONTEXT_ROLES]]
        if role_names:
            roles_text = ", ".join(role_names)
            if len(roles) > len(role_names):
                roles_text += f" (và {len(roles) - len(role_names)} role khác)"
        else:
            roles_text = "không có role nào ngoài mặc định"
        lines.append(f"- Người đang hỏi: {member.display_name}, role hiện có: {roles_text}")
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


class _ProviderFailure(Exception):
    """Một model/provider thất bại.

    kind: "rate"  = quota / 429
          "temp"  = lỗi tạm thời (5xx, timeout, mất kết nối)
          "fatal" = lỗi không nên thử model khác (vd: 400) — trả lỗi ngay
    """

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.message = message
        self.kind = kind


def _build_candidates() -> list[tuple[str, str]]:
    """Danh sách (provider, model) theo thứ tự thử: model chính trước, các model dự phòng sau."""
    candidates: list[tuple[str, str]] = []
    for provider in config.AI_PROVIDER_ORDER:
        if provider == "gemini":
            if config.GEMINI_ENABLED and gemini_client is not None:
                candidates.extend(("gemini", m) for m in config.GEMINI_MODELS)
        elif provider == "literouter":
            if literouter.client.available:
                model = literouter.client.resolve_model()
                if model:
                    candidates.append(("literouter", model))
    return candidates


def describe_ai_providers() -> str:
    """Mô tả ngắn các provider/model đang dùng (hiển thị ở /botinfo). Không chứa API key."""
    parts: list[str] = []
    for provider in config.AI_PROVIDER_ORDER:
        if provider == "gemini":
            if not config.GEMINI_ENABLED:
                parts.append("Gemini: tắt")
            else:
                parts.append("Gemini: " + " → ".join(config.GEMINI_MODELS))
        elif provider == "literouter":
            if not config.LITEROUTER_ENABLED:
                parts.append("Literouter: tắt")
            elif not config.LITEROUTER_API_KEY:
                parts.append("Literouter: thiếu API key")
            else:
                model = literouter.client.resolve_model() or "chưa có model"
                parts.append(f"Literouter: {model} ({len(literouter.client.models)} model khả dụng)")
    return " | ".join(parts)


async def _call_gemini(model: str, contents: list, gen_config) -> tuple[str, bool]:
    try:
        response = await asyncio.wait_for(
            gemini_client.aio.models.generate_content(model=model, contents=contents, config=gen_config),
            timeout=config.GEMINI_TIMEOUT,
        )
    except ClientError as e:
        if e.code == 429:
            log.warning("Gemini %s: 429 (quota/rate limit)", model)
            raise _ProviderFailure(MSG_RATE_LIMIT, "rate") from e
        if e.code == 408:
            log.warning("Gemini %s: 408 timeout từ phía server", model)
            raise _ProviderFailure(MSG_OVERLOADED, "temp") from e
        log.error("Gemini client error (%s): %s", model, e)
        raise _ProviderFailure(MSG_API_ERROR, "fatal") from e
    except (ServerError, asyncio.TimeoutError) as e:
        log.warning("Gemini %s lỗi tạm thời: %r", model, e)
        raise _ProviderFailure(MSG_OVERLOADED, "temp") from e
    except Exception as e:
        log.exception("Lỗi không xác định khi gọi Gemini (%s)", model)
        raise _ProviderFailure(MSG_API_ERROR, "fatal") from e
    return _extract_reply(response)


async def _call_literouter(
    model: str,
    system_text: str,
    history_pairs: list[tuple[str, str]],
    user_message: str,
    images: list[tuple[str, bytes]],
) -> tuple[str, bool]:
    messages = literouter.build_messages(system_text, history_pairs, user_message, images)
    try:
        return await literouter.client.chat(messages, model=model)
    except literouter.LiterouterError as e:
        if e.status == 429:
            log.warning("Literouter %s: 429 (quota/rate limit)", model)
            raise _ProviderFailure(MSG_RATE_LIMIT, "rate") from e
        if e.temporary:
            log.warning("Literouter %s lỗi tạm thời: %s", model, e)
            raise _ProviderFailure(MSG_OVERLOADED, "temp") from e
        log.error("Literouter client error (%s): %s", model, e)
        raise _ProviderFailure(MSG_API_ERROR, "fatal") from e
    except Exception as e:
        log.exception("Lỗi không xác định khi gọi Literouter (%s)", model)
        raise _ProviderFailure(MSG_API_ERROR, "fatal") from e


async def _attempt(call, *, can_fallback: bool) -> tuple[str, bool]:
    """Gọi một model kèm retry.

    Còn model dự phòng phía sau → không retry/ngủ, thất bại là chuyển model ngay cho nhanh.
    Là model cuối cùng → giữ logic retry cũ (429 thử lại 1 lần, lỗi tạm thời tối đa 3 lần).
    """
    max_attempts = 1 if can_fallback else 3
    rate_retried = False
    last: _ProviderFailure | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            # Chỉ giữ slot trong lúc gọi API; khi chờ retry thì nhả slot cho người khác.
            async with gemini_sem:
                return await call()
        except _ProviderFailure as e:
            last = e
            if e.kind == "rate":
                if not can_fallback and not rate_retried and config.GEMINI_429_RETRY_SECONDS > 0:
                    rate_retried = True
                    log.warning("429, thử lại sau %ds", config.GEMINI_429_RETRY_SECONDS)
                    await asyncio.sleep(config.GEMINI_429_RETRY_SECONDS)
                    continue
                raise
            if e.kind == "temp" and attempt < max_attempts:
                log.warning("Lỗi tạm thời (lần %d/%d)", attempt, max_attempts)
                await asyncio.sleep(2 * attempt)
                continue
            raise
    raise last or _ProviderFailure(MSG_API_ERROR, "fatal")  # chỉ tới đây khi hết lượt sau một lần retry 429


async def ask_gemini(
    key: HistoryKey,
    user_message: str,
    *,
    privileged: bool = False,
    server_context: str = "",
    channel_context: str = "",
    image_parts: list[types.Part] | None = None,
    auto_channel: bool = False,
) -> str | None:
    """Trả về câu trả lời, hoặc None nếu bot quyết định im lặng (chỉ ở auto-chat).

    Tên hàm giữ nguyên cho tương thích; thực tế thử lần lượt các model/provider đã cấu hình
    (Gemini chính → Gemini dự phòng → Literouter, theo AI_PROVIDER_ORDER).
    """
    candidates = _build_candidates()
    if not candidates:
        return MSG_NO_PROVIDER

    history = await load_history(key)

    system_parts = [config.SYSTEM_PROMPT, PROMPT_SECURITY_INSTRUCTION]
    if privileged:
        system_parts.append(config.PRIVILEGED_NOTE)
    if auto_channel:
        # Đây là chỉ thị điều khiển của ứng dụng, không phải dữ liệu Discord.
        system_parts.append(RELEVANCE_INSTRUCTION)

    system_text = "\n\n".join(system_parts)
    # Context Discord và nội dung người dùng luôn nằm ở user role, không được
    # ghép vào system_instruction vì chúng có thể chứa prompt injection.
    untrusted_user_payload = build_untrusted_payload(
        user_message=user_message,
        server_context=server_context,
        channel_context=channel_context,
    )

    contents = list(history)
    user_parts = [types.Part(text=untrusted_user_payload)]
    if image_parts:
        user_parts.extend(image_parts)
    contents.append(types.Content(role="user", parts=user_parts))
    cfg_kwargs: dict = {
        "system_instruction": system_text,
        "max_output_tokens": config.MAX_OUTPUT_TOKENS,
    }
    # Gemini 3.x: Google khuyến nghị không chỉnh temperature → chỉ gửi khi được cấu hình.
    if config.GEMINI_TEMPERATURE is not None:
        cfg_kwargs["temperature"] = config.GEMINI_TEMPERATURE
    if THINKING_CONFIG is not None:
        cfg_kwargs["thinking_config"] = THINKING_CONFIG
    gen_config = types.GenerateContentConfig(**cfg_kwargs)

    # Dữ liệu cho Literouter (OpenAI format): lịch sử thuần text + ảnh dạng (mime, bytes).
    history_pairs = [
        (c.role, c.parts[0].text) for c in history if c.parts and getattr(c.parts[0], "text", None)
    ]
    images = [
        (p.inline_data.mime_type, p.inline_data.data)
        for p in (image_parts or [])
        if getattr(p, "inline_data", None) and getattr(p.inline_data, "data", None)
    ]

    reply, truncated = "", False
    failure = MSG_API_ERROR
    for idx, (provider, model) in enumerate(candidates):
        can_fallback = idx < len(candidates) - 1
        if provider == "gemini":
            call = functools.partial(_call_gemini, model, contents, gen_config)
        else:
            call = functools.partial(
                _call_literouter, model, system_text, history_pairs, untrusted_user_payload, images
            )
        try:
            reply, truncated = await _attempt(call, can_fallback=can_fallback)
        except _ProviderFailure as e:
            failure = e.message
            if e.kind == "fatal":
                return failure
            if can_fallback:
                log.warning("%s/%s thất bại (%s) — chuyển sang model kế tiếp", provider, model, e.kind)
            continue
        if idx > 0:
            log.info("Đã trả lời bằng model dự phòng %s/%s", provider, model)
        break
    else:
        return failure  # mọi model đều thất bại; trả thông báo của model cuối cùng

    if not reply:
        return MSG_TRUNCATED if truncated else MSG_EMPTY
    if auto_channel and SKIP_TOKEN in reply:
        return None
    if truncated:
        reply += " …"

    history.append(types.Content(role="user", parts=[types.Part(text=user_message)]))
    history.append(types.Content(role="model", parts=[types.Part(text=reply)]))
    await save_history(key, history)
    return reply


@tasks.loop(hours=6)
async def history_purge_loop():
    try:
        deleted = await db.purge_old_history(config.HISTORY_RETENTION_DAYS)
        if deleted:
            history_cache.clear()  # mọi thay đổi đã nằm trong DB nên reload là an toàn
            log.info("Đã xóa %d lịch sử hội thoại quá %d ngày", deleted, config.HISTORY_RETENTION_DAYS)
    except Exception:
        log.exception("Lỗi trong history_purge_loop")


# ======================================================================
# Sự kiện
# ======================================================================
@bot.event
async def on_guild_join(guild: discord.Guild):
    if allowed_guild_ids and guild.id not in allowed_guild_ids:
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
    if allowed_guild_ids:
        for guild in list(bot.guilds):
            if guild.id not in allowed_guild_ids:
                log.warning("Đang ở server không được phép: %s (ID: %s) — tự rời.", guild.name, guild.id)
                await guild.leave()
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)


# Channel context được quản lý độc lập để bot.py chỉ điều phối luồng xử lý.
channel_context_manager = ChannelContext(bot, log)
# Giữ alias để tương thích với test và code nội bộ đang truy cập cache trực tiếp.
_channel_message_cache = channel_context_manager._messages


def record_channel_message(message: discord.Message | None) -> None:
    channel_context_manager.record_message(message)


async def get_referenced_message(message: discord.Message) -> discord.Message | None:
    return await channel_context_manager.get_reference(message)


async def build_channel_context(
    channel: discord.abc.Messageable | None,
    *,
    current_message: discord.Message | None = None,
    ref_msg: discord.Message | None = None,
    limit: int = config.CHANNEL_HISTORY_LIMIT,
) -> str:
    return await channel_context_manager.build(
        channel, current_message=current_message, ref_msg=ref_msg, limit=limit
    )


async def is_message_for_bot(
    message: discord.Message,
    *,
    ref_msg: object = REFERENCE_UNSET,
) -> bool:
    return await channel_context_manager.is_message_for_bot(message, ref_msg=ref_msg)


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
    ref_msg = await get_referenced_message(message)

    if not content and not message.attachments and not ref_msg:
        if not auto_channel:
            await message.reply("Bạn muốn hỏi gì nào?", mention_author=False)
        return

    if auto_channel and not mentioned:
        # Lọc rẻ trước khi tốn request Gemini: tin chỉ có emoji/link, hoặc gửi dồn dập.
        if not message.attachments and (not ref_msg or not getattr(ref_msg, "attachments", None)) and is_trivial_message(content):
            return
        if _auto_chat_on_cooldown(message.channel.id, message.author.id):
            return
        if not await is_message_for_bot(message, ref_msg=ref_msg):
            return

    key: HistoryKey = (message.guild.id, message.author.id)
    try:
        async with user_gate(key, allow_queue=True):
            image_parts = await build_image_parts(message.attachments)
            if not image_parts and ref_msg and getattr(ref_msg, "attachments", None):
                image_parts = await build_image_parts(ref_msg.attachments)

            final_content = content
            if not final_content and not image_parts:
                if ref_msg and (getattr(ref_msg, "clean_content", None) or getattr(ref_msg, "content", None)):
                    final_content = "Cho ý kiến hoặc giải thích tin nhắn này giúp mình."
                else:
                    if not auto_channel:
                        await message.reply("Mình chỉ đọc được ảnh (png/jpg/webp/heic).", mention_author=False)
                    return

            async with message.channel.typing():
                channel_context = await build_channel_context(
                    message.channel, current_message=message, ref_msg=ref_msg
                )
                reply = await ask_gemini(
                    key,
                    final_content or DEFAULT_IMAGE_PROMPT,
                    privileged=is_privileged(message.author),
                    server_context=build_server_context(message.author, message.guild),
                    channel_context=channel_context,
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
    try:
        chunks = split_message(reply, config.MAX_REPLY_CHARS)
        first_reply = await message.reply(chunks[0], mention_author=False)
        record_channel_message(first_reply)
        for chunk in chunks[1:]:
            extra_reply = await message.channel.send(chunk)
            record_channel_message(extra_reply)
    except discord.HTTPException as e:
        log.error("Gửi trả lời thất bại: %s", e)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    if allowed_guild_ids and message.guild.id not in allowed_guild_ids:
        return

    # Luôn ghi nhận tin nhắn vào cache RAM theo thời gian thực (đọc chat trước)
    record_channel_message(message)

    is_auto_channel = message.channel.id in auto_chat_channels
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
            channel_context = await build_channel_context(interaction.channel)
            reply = await ask_gemini(
                key,
                message,
                privileged=is_privileged(interaction.user),
                server_context=build_server_context(interaction.user, interaction.guild),
                channel_context=channel_context,
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
    if reply is None:
        return
    await _send_followup_chunks(interaction, reply)


@bot.tree.command(name="reset", description="Xóa lịch sử hội thoại của bạn với AI (ở server này)")
async def reset_command(interaction: discord.Interaction):
    await delete_history((interaction.guild_id, interaction.user.id))
    await interaction.response.send_message("Đã xóa lịch sử hội thoại của bạn.", ephemeral=True)


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


# Dashboard và giao diện Auto-Chat đã được chuyển sang botinfo.py.
@bot.tree.command(name="botinfo", description="[Admin/Owner] Bảng điều khiển xem & quản lý bot (Auto-Chat)")
async def botinfo_command(interaction: discord.Interaction):
    if not is_privileged(interaction.user):
        await interaction.response.send_message("Lệnh này chỉ Admin/Owner mới dùng được nhé.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True, ephemeral=True)
    embed = await build_botinfo_embed(interaction.guild)
    view = BotInfoMainView(interaction.guild)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


botinfo.setup(
    bot_instance=bot,
    database=db,
    channels=auto_chat_channels,
    privilege_check=is_privileged,
    provider_description=describe_ai_providers,
    start_time=BOT_START_TIME,
)


# ======================================================================
def main() -> None:
    global gemini_client
    if not config.DISCORD_TOKEN:
        raise RuntimeError("Thiếu DISCORD_TOKEN trong file .env")
    if config.GEMINI_ENABLED:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("Thiếu GEMINI_API_KEY trong file .env (hoặc đặt GEMINI_ENABLED=false)")
        gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    if config.LITEROUTER_ENABLED and not config.LITEROUTER_API_KEY:
        raise RuntimeError("Thiếu LITEROUTER_API_KEY trong file .env (hoặc đặt LITEROUTER_ENABLED=false)")
    if gemini_client is None and not literouter.client.available:
        raise RuntimeError("Chưa bật provider AI nào: đặt GEMINI_ENABLED=true hoặc LITEROUTER_ENABLED=true")
    bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
