"""Web dashboard (aiohttp) chạy chung tiến trình với bot."""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import platform
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import discord
import psutil
from aiohttp import web

import config
import dashboard_views as v
from db import Database
from utils import get_dir_size, get_memory_limit_bytes


log = logging.getLogger("discord-ai-bot.dashboard")

COOKIE = "gd_session"
START_TIME = datetime.now(timezone.utc)

# Các đường dẫn KHÔNG cần đăng nhập
PUBLIC_PATHS = frozenset({
    "/login",
    "/dashboard.css",
    "/static/login.js",
    "/bg.jpg",
})


# ---------------------------------------------------------------------------
# LOG BUFFER
# ---------------------------------------------------------------------------

class LogBuffer(logging.Handler):
    """Giữ N dòng log gần nhất để xem trên dashboard."""

    def __init__(self, maxlen: int = 500):
        super().__init__()
        self.lines: deque[str] = deque(maxlen=maxlen)
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] "
                "%(name)s: %(message)s"
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)

            for secret in (
                config.DISCORD_TOKEN,
                config.GEMINI_API_KEY,
                config.DASHBOARD_PASSWORD,
            ):
                if secret:
                    text = text.replace(secret, "***")

            self.lines.append(text)
        except Exception:
            pass


log_buffer = LogBuffer()


def install_log_buffer() -> None:
    root = logging.getLogger()

    if log_buffer not in root.handlers:
        root.addHandler(log_buffer)


# ---------------------------------------------------------------------------
# CONTEXT
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    bot: Any
    db: Database
    auto_chat_channels: set
    history_cache: dict


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _msg(request: web.Request) -> str:
    return request.query.get("msg", "")[:200]


def _redirect(path: str, msg: str):
    return web.HTTPFound(
        f"{path}?msg={quote(msg)}"
    )


async def _form(request: web.Request) -> dict:
    """
    Đọc form POST và kiểm tra CSRF token.

    Session là object, không phải dict.
    Vì vậy phải dùng request["session"].csrf.
    """
    data = await request.post()

    session = request["session"]
    expected = str(session.csrf)
    given = str(data.get("csrf", ""))

    if not hmac.compare_digest(given, expected):
        raise web.HTTPForbidden(
            text="CSRF token không hợp lệ"
        )

    return {
        k: str(val)
        for k, val in data.items()
        if k != "csrf"
    }


def _int(
    form: dict,
    key: str,
    lo: int = 0,
    hi: int = 2**63 - 1,
) -> int:
    try:
        n = int(form.get(key, "").strip())
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(
            text=f"{key} không hợp lệ"
        )

    if not lo <= n <= hi:
        raise web.HTTPBadRequest(
            text=f"{key} ngoài phạm vi"
        )

    return n


def _render(
    request: web.Request,
    title: str,
    body: str,
    active: str,
) -> web.Response:
    """
    Render dashboard page.

    FIX QUAN TRỌNG:
    request["session"] là Session object.
    Không được dùng:
        request["session"]["csrf"]

    Phải dùng:
        request["session"].csrf
    """
    session = request["session"]

    page = v.layout(
        title=title,
        body=body,
        csrf=session.csrf,
        active=active,
        msg=_msg(request),
    )

    return web.Response(
        text=page,
        content_type="text/html",
    )


def _guild_label(bot, guild_id: int) -> str:
    guild = (
        bot.get_guild(guild_id)
        if guild_id
        else None
    )

    if guild:
        return guild.name

    if guild_id:
        return f"(id {guild_id})"

    return "?"


def _channel_label(bot, channel_id: int) -> str:
    channel = bot.get_channel(channel_id)

    if (
        channel is not None
        and hasattr(channel, "name")
    ):
        return f"#{channel.name}"

    return f"(kênh {channel_id})"


# ---------------------------------------------------------------------------
# SECURITY MIDDLEWARE
# ---------------------------------------------------------------------------

@web.middleware
async def security_middleware(request, handler):
    try:
        if request.path not in PUBLIC_PATHS:
            session_token = request.cookies.get(COOKIE)

            session = request.app["sessions"].get(
                session_token
            )

            if session is None:
                # Có cookie nhưng phiên không còn hợp lệ -> báo hết hạn
                raise web.HTTPFound(
                    "/login?expired=1" if session_token else "/login"
                )

            # Session object được gắn vào request.
            request["session"] = session

        response = await handler(request)

    except web.HTTPException as ex:
        response = ex

    # Handler nào tự đặt Cache-Control (vd. ảnh nền) thì giữ nguyên
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    if request.path == "/dashboard.css":
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "style-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'none'"
        )
    elif request.path == "/login":
        # Trang đăng nhập cần chạy /static/login.js và favicon dạng data:
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'none'"
        )

    return response


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

async def dashboard_css(request: web.Request) -> web.Response:
    """Phục vụ static/dashboard.css."""

    css = v.get_css()

    if not css:
        return web.Response(
            text=(
                "/* dashboard.css chưa được tạo "
                "ở static/dashboard.css */"
            ),
            content_type="text/css",
            status=404,
        )

    # Gắn mã phiên bản vào URL ảnh nền: đổi bg.jpg là trình duyệt tải lại ngay
    css = css.replace(
        "url(/bg.jpg)",
        f"url(/bg.jpg?v={v.get_bg_version()})",
    )

    return web.Response(
        text=css,
        content_type="text/css",
        charset="utf-8",
        headers={
            "Cache-Control": "no-store, must-revalidate",
        },
    )


async def background_image(request: web.Request) -> web.Response:
    """Phục vụ ảnh nền static/bg.jpg (công khai, được cache)."""

    data = v.get_bg_image()

    if not data:
        raise web.HTTPNotFound()

    return web.Response(
        body=data,
        content_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


async def login_js(request: web.Request) -> web.Response:
    """Phục vụ static/login.js (công khai, dùng cho trang đăng nhập)."""

    js = v.get_login_js()

    if not js:
        return web.Response(
            text="/* static/login.js chưa được tạo */",
            content_type="application/javascript",
            status=404,
        )

    return web.Response(
        text=js,
        content_type="application/javascript",
        charset="utf-8",
        headers={
            "Cache-Control": "no-store, must-revalidate",
        },
    )


# ---------------------------------------------------------------------------
# LOGIN
# ---------------------------------------------------------------------------

async def login_get(request: web.Request):
    return web.Response(
        text=v.login_page(),
        content_type="text/html",
    )


async def login_post(request: web.Request):
    app = request.app
    ip = request.remote or "?"

    limiter: v.LoginLimiter = app["limiter"]

    if limiter.blocked(ip):
        return web.Response(
            text=v.login_page(
                "Sai quá nhiều lần, thử lại sau 10 phút."
            ),
            content_type="text/html",
            charset="utf-8",
            status=429,
            headers={"Retry-After": "600"},
        )

    data = await request.post()

    given = str(
        data.get("password", "")
    ).encode()

    expected = str(
        app["password"] or ""
    ).encode()

    if not hmac.compare_digest(
        given,
        expected,
    ):
        limiter.fail(ip)

        log.warning(
            "Đăng nhập dashboard thất bại từ %s",
            ip,
        )

        await asyncio.sleep(1)

        return web.Response(
            text=v.login_page("Sai mật khẩu."),
            content_type="text/html",
            charset="utf-8",
            status=401,
        )

    limiter.reset(ip)

    token, _session = app["sessions"].create()

    response = web.HTTPFound("/")

    response.set_cookie(
        COOKIE,
        token,
        max_age=app["sessions"].ttl,
        httponly=True,
        samesite="Strict",
        secure=config.DASHBOARD_SECURE_COOKIE,
        path="/",
    )

    log.info(
        "Đăng nhập dashboard thành công từ %s",
        ip,
    )

    raise response


async def logout_post(request: web.Request):
    await _form(request)

    request.app["sessions"].delete(
        request.cookies.get(COOKIE)
    )

    response = web.HTTPFound("/login?logout=1")

    response.del_cookie(
        COOKIE,
        path="/",
    )

    raise response


# ---------------------------------------------------------------------------
# OVERVIEW
# ---------------------------------------------------------------------------

async def overview(request: web.Request):
    ctx: Ctx = request.app["ctx"]
    bot = ctx.bot

    cache = request.app["disk_cache"]

    if time.time() - cache["at"] > 120:
        cache["value"] = await asyncio.to_thread(
            get_dir_size,
            str(config.BASE_DIR),
        )

        cache["at"] = time.time()

    reminders = (
        await ctx.db.list_all_active_reminders()
    )

    per_guild: dict[int, int] = {}

    for reminder in reminders:
        guild_id = reminder["guild_id"]

        per_guild[guild_id] = (
            per_guild.get(guild_id, 0) + 1
        )

    guilds = []

    for guild in bot.guilds:
        channel_ids = {
            channel.id
            for channel in guild.text_channels
        }

        guilds.append({
            "name": guild.name,
            "id": guild.id,
            "members": guild.member_count or 0,
            "autochat": len(
                channel_ids & ctx.auto_chat_channels
            ),
            "reminders": per_guild.get(
                guild.id,
                0,
            ),
        })

    latency = bot.latency

    stats = {
        "ping_ms": (
            round(latency * 1000)
            if latency == latency
            else 0
        ),
        "uptime": (
            datetime.now(timezone.utc)
            - START_TIME
        ),
        "guild_count": len(bot.guilds),
        "members": sum(
            guild["members"]
            for guild in guilds
        ),
        "ram": psutil.Process(
            os.getpid()
        ).memory_info().rss,
        "ram_limit": get_memory_limit_bytes(),
        "disk": cache["value"],
        "db_size": (
            os.path.getsize(config.DB_PATH)
            if os.path.exists(config.DB_PATH)
            else 0
        ),
        "reminders": len(reminders),
        "autochat": len(
            ctx.auto_chat_channels
        ),
        "model": config.GEMINI_MODEL,
        "python": platform.python_version(),
        "dpy": discord.__version__,
    }

    return _render(
        request,
        "Tổng quan",
        v.overview_body(
            stats,
            guilds,
        ),
        "/",
    )


# ---------------------------------------------------------------------------
# REMINDERS
# ---------------------------------------------------------------------------

async def reminders_get(request: web.Request):
    ctx: Ctx = request.app["ctx"]

    rows = []

    reminders = (
        await ctx.db.list_all_active_reminders()
    )

    for reminder in reminders:
        next_run = datetime.fromisoformat(
            reminder["next_run_utc"]
        ).astimezone(config.VN_TZ)

        message = reminder["message"]

        if len(message) > 150:
            message = message[:147] + "..."

        rows.append({
            "id": reminder["id"],
            "guild": _guild_label(
                ctx.bot,
                reminder["guild_id"],
            ),
            "channel": _channel_label(
                ctx.bot,
                reminder["channel_id"],
            ),
            "repeat": reminder["repeat"],
            "hhmm": (
                f"{reminder['hour']:02d}:"
                f"{reminder['minute']:02d}"
            ),
            "next_run": next_run.strftime(
                "%H:%M %d/%m/%Y"
            ),
            "creator": reminder["created_by"],
            "message": message,
        })

    return _render(
        request,
        "Reminder",
        v.reminders_body(
            rows,
            request["session"].csrf,
        ),
        "/reminders",
    )


async def reminders_cancel(request: web.Request):
    form = await _form(request)

    reminder_id = _int(
        form,
        "id",
        1,
    )

    ok = await request.app["ctx"].db.deactivate_reminder(
        reminder_id
    )

    log.info(
        "Dashboard hủy reminder #%s (%s)",
        reminder_id,
        ok,
    )

    raise _redirect(
        "/reminders",
        (
            f"Đã hủy #{reminder_id}"
            if ok
            else f"Không tìm thấy #{reminder_id}"
        ),
    )


# ---------------------------------------------------------------------------
# AUTOCHAT
# ---------------------------------------------------------------------------

def _allowed_guilds(bot):
    return [
        guild
        for guild in bot.guilds
        if (
            not config.ALLOWED_GUILD_IDS
            or guild.id in config.ALLOWED_GUILD_IDS
        )
    ]


async def autochat_get(request: web.Request):
    ctx: Ctx = request.app["ctx"]

    entries = []
    choices = []

    for guild in _allowed_guilds(ctx.bot):
        for channel in guild.text_channels:
            if channel.id in ctx.auto_chat_channels:
                entries.append({
                    "guild": guild.name,
                    "channel": channel.name,
                    "channel_id": channel.id,
                })

        usable = [
            (
                channel.id,
                channel.name,
            )
            for channel in guild.text_channels
            if (
                channel.permissions_for(
                    guild.me
                ).view_channel
                and channel.permissions_for(
                    guild.me
                ).send_messages
                and channel.id
                not in ctx.auto_chat_channels
            )
        ]

        if usable:
            choices.append(
                (
                    guild.name,
                    usable,
                )
            )

    return _render(
        request,
        "Auto-Chat",
        v.autochat_body(
            entries,
            choices,
            request["session"].csrf,
        ),
        "/autochat",
    )


async def autochat_add(request: web.Request):
    ctx: Ctx = request.app["ctx"]

    form = await _form(request)

    channel = ctx.bot.get_channel(
        _int(
            form,
            "channel_id",
            1,
        )
    )

    if (
        not isinstance(
            channel,
            discord.TextChannel,
        )
        or channel.guild
        not in _allowed_guilds(ctx.bot)
    ):
        raise _redirect(
            "/autochat",
            "Kênh không hợp lệ",
        )

    await ctx.db.add_auto_chat_channel(
        channel.id,
        channel.guild.id,
        0,
    )

    ctx.auto_chat_channels.add(
        channel.id
    )

    log.info(
        "Dashboard bật auto-chat ở #%s (%s)",
        channel.name,
        channel.id,
    )

    raise _redirect(
        "/autochat",
        f"Đã bật auto-chat ở #{channel.name}",
    )


async def autochat_remove(request: web.Request):
    ctx: Ctx = request.app["ctx"]

    form = await _form(request)

    channel_id = _int(
        form,
        "channel_id",
        1,
    )

    await ctx.db.remove_auto_chat_channel(
        channel_id
    )

    ctx.auto_chat_channels.discard(
        channel_id
    )

    log.info(
        "Dashboard tắt auto-chat ở kênh %s",
        channel_id,
    )

    raise _redirect(
        "/autochat",
        "Đã tắt auto-chat",
    )


# ---------------------------------------------------------------------------
# HISTORY
# ---------------------------------------------------------------------------

async def history_get(request: web.Request):
    ctx: Ctx = request.app["ctx"]

    body = v.history_body(
        await ctx.db.count_history(),
        len(ctx.history_cache),
        config.HISTORY_RETENTION_DAYS,
        request["session"].csrf,
    )

    return _render(
        request,
        "Lịch sử hội thoại",
        body,
        "/history",
    )


async def history_purge(request: web.Request):
    ctx: Ctx = request.app["ctx"]

    form = await _form(request)

    days = _int(
        form,
        "days",
        1,
        3650,
    )

    count = await ctx.db.purge_old_history(
        days
    )

    ctx.history_cache.clear()

    raise _redirect(
        "/history",
        f"Đã xóa {count} hội thoại cũ hơn {days} ngày",
    )


async def history_delete_user(request: web.Request):
    ctx: Ctx = request.app["ctx"]

    form = await _form(request)

    guild_id = _int(
        form,
        "guild_id",
        1,
    )

    user_id = _int(
        form,
        "user_id",
        1,
    )

    await ctx.db.delete_history(
        guild_id,
        user_id,
    )

    ctx.history_cache.pop(
        (guild_id, user_id),
        None,
    )

    raise _redirect(
        "/history",
        f"Đã xóa lịch sử của user {user_id}",
    )


async def history_delete_all(request: web.Request):
    ctx: Ctx = request.app["ctx"]

    form = await _form(request)

    if form.get("confirm") != "yes":
        raise _redirect(
            "/history",
            "Chưa tick ô xác nhận",
        )

    count = await ctx.db.delete_all_history()

    ctx.history_cache.clear()

    log.warning(
        "Dashboard xóa toàn bộ lịch sử (%d)",
        count,
    )

    raise _redirect(
        "/history",
        f"Đã xóa toàn bộ ({count}) hội thoại",
    )


async def history_clear_cache(request: web.Request):
    await _form(request)

    request.app["ctx"].history_cache.clear()

    raise _redirect(
        "/history",
        "Đã làm trống cache",
    )


# ---------------------------------------------------------------------------
# LOGS
# ---------------------------------------------------------------------------

async def logs_get(request: web.Request):
    return _render(
        request,
        "Log",
        v.logs_body(
            list(log_buffer.lines)[-300:]
        ),
        "/logs",
    )


# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------

async def settings_get(request: web.Request):
    items = [
        (
            "GEMINI_MODEL",
            config.GEMINI_MODEL,
        ),
        (
            "MAX_OUTPUT_TOKENS",
            config.MAX_OUTPUT_TOKENS,
        ),
        (
            "THINKING_BUDGET",
            config.THINKING_BUDGET,
        ),
        (
            "GEMINI_TIMEOUT",
            config.GEMINI_TIMEOUT,
        ),
        (
            "GEMINI_CONCURRENCY",
            config.GEMINI_CONCURRENCY,
        ),
        (
            "MAX_HISTORY_TURNS",
            config.MAX_HISTORY_TURNS,
        ),
        (
            "HISTORY_RETENTION_DAYS",
            config.HISTORY_RETENTION_DAYS,
        ),
        (
            "MAX_IMAGES",
            config.MAX_IMAGES,
        ),
        (
            "MAX_IMAGE_MB",
            config.MAX_IMAGE_BYTES
            // (1024 * 1024),
        ),
        (
            "STATUS",
            f"{config.STATUS_TYPE}: "
            f"{config.STATUS_TEXT}",
        ),
        (
            "ALLOWED_GUILD_IDS",
            ", ".join(
                map(
                    str,
                    sorted(
                        config.ALLOWED_GUILD_IDS
                    ),
                )
            )
            or "(không giới hạn)",
        ),
        (
            "ADMIN_ROLE_IDS",
            ", ".join(
                map(
                    str,
                    sorted(
                        config.ADMIN_ROLE_IDS
                    ),
                )
            )
            or "(trống)",
        ),
        (
            "MEMBERS_INTENT",
            config.MEMBERS_INTENT,
        ),
        (
            "MAX_REMINDERS_PER_USER",
            config.MAX_REMINDERS_PER_USER,
        ),
        (
            "REMINDER_GRACE_MINUTES",
            config.REMINDER_GRACE_MINUTES,
        ),
        (
            "DB_PATH",
            config.DB_PATH,
        ),
        (
            "DASHBOARD",
            f"{config.DASHBOARD_HOST}:"
            f"{config.DASHBOARD_PORT}",
        ),
    ]

    return _render(
        request,
        "Cấu hình (chỉ xem)",
        v.settings_body(
            items,
            config.SYSTEM_PROMPT,
        ),
        "/settings",
    )


# ---------------------------------------------------------------------------
# CREATE APP
# ---------------------------------------------------------------------------

def create_app(
    ctx: Ctx,
    password: str | None = None,
) -> web.Application:

    app = web.Application(
        middlewares=[
            security_middleware
        ],
        client_max_size=64 * 1024,
    )

    app["ctx"] = ctx

    app["password"] = (
        password
        if password is not None
        else config.DASHBOARD_PASSWORD
    )

    app["sessions"] = v.SessionStore()
    app["limiter"] = v.LoginLimiter()

    app["disk_cache"] = {
        "at": 0.0,
        "value": 0,
    }

    app.add_routes([
        # Static
        web.get(
            "/dashboard.css",
            dashboard_css,
        ),
        web.get(
            "/static/login.js",
            login_js,
        ),
        web.get(
            "/bg.jpg",
            background_image,
        ),

        # Authentication
        web.get(
            "/login",
            login_get,
        ),
        web.post(
            "/login",
            login_post,
        ),
        web.post(
            "/logout",
            logout_post,
        ),

        # Dashboard
        web.get(
            "/",
            overview,
        ),

        # Reminders
        web.get(
            "/reminders",
            reminders_get,
        ),
        web.post(
            "/reminders/cancel",
            reminders_cancel,
        ),

        # Auto chat
        web.get(
            "/autochat",
            autochat_get,
        ),
        web.post(
            "/autochat/add",
            autochat_add,
        ),
        web.post(
            "/autochat/remove",
            autochat_remove,
        ),

        # History
        web.get(
            "/history",
            history_get,
        ),
        web.post(
            "/history/purge",
            history_purge,
        ),
        web.post(
            "/history/delete_user",
            history_delete_user,
        ),
        web.post(
            "/history/delete_all",
            history_delete_all,
        ),
        web.post(
            "/history/clear_cache",
            history_clear_cache,
        ),

        # Logs
        web.get(
            "/logs",
            logs_get,
        ),

        # Settings
        web.get(
            "/settings",
            settings_get,
        ),
    ])

    return app


# ---------------------------------------------------------------------------
# START DASHBOARD
# ---------------------------------------------------------------------------

async def start_dashboard(
    ctx: Ctx,
) -> web.AppRunner:

    if len(config.DASHBOARD_PASSWORD) < 12:
        raise RuntimeError(
            "DASHBOARD_PASSWORD phải có ít nhất 12 ký tự"
        )

    runner = web.AppRunner(
        create_app(ctx),
        access_log=None,
    )

    await runner.setup()

    await web.TCPSite(
        runner,
        config.DASHBOARD_HOST,
        config.DASHBOARD_PORT,
    ).start()

    log.info(
        "Dashboard chạy tại http://%s:%s",
        config.DASHBOARD_HOST,
        config.DASHBOARD_PORT,
    )

    if config.DASHBOARD_HOST not in (
        "127.0.0.1",
        "localhost",
        "::1",
    ):
        log.warning(
            "Dashboard đang mở ra ngoài localhost "
            "qua HTTP thường — mật khẩu đi không mã hóa. "
            "Hãy đặt sau reverse proxy HTTPS "
            "(và bật DASHBOARD_SECURE_COOKIE=true) "
            "hoặc dùng SSH tunnel."
        )

    return runner
