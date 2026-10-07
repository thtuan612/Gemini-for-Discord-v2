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


# ---------------------------------------------------------------- log buffer
class LogBuffer(logging.Handler):
    """Giữ N dòng log gần nhất để xem trên dashboard (đã che token / API key)."""

    def __init__(self, maxlen: int = 500):
        super().__init__()
        self.lines: deque[str] = deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
            for secret in (config.DISCORD_TOKEN, config.GEMINI_API_KEY, config.DASHBOARD_PASSWORD):
                if secret:
                    text = text.replace(secret, "***")
            self.lines.append(text)
        except Exception:
            pass


log_buffer = LogBuffer()


def install_log_buffer() -> None:
    logging.getLogger().addHandler(log_buffer)


# ---------------------------------------------------------------- context
@dataclass
class Ctx:
    bot: Any
    db: Database
    auto_chat_channels: set
    history_cache: dict


def _msg(request: web.Request) -> str:
    return request.query.get("msg", "")[:200]


def _redirect(path: str, msg: str):
    return web.HTTPFound(f"{path}?msg={quote(msg)}")


async def _form(request: web.Request) -> dict:
    """Đọc form POST và kiểm tra CSRF token của phiên."""
    data = await request.post()
    given = str(data.get("csrf", ""))
    # So sánh dạng bytes: compare_digest với str chứa ký tự non-ASCII sẽ ném TypeError (→ lỗi 500).
    if not hmac.compare_digest(given.encode("utf-8"), request["session"]["csrf"].encode("utf-8")):
        raise web.HTTPForbidden(text="CSRF token không hợp lệ")
    return {k: str(val) for k, val in data.items() if k != "csrf"}


def _int(form: dict, key: str, lo: int = 0, hi: int = 2**63 - 1) -> int:
    try:
        n = int(form.get(key, "").strip())
    except ValueError:
        raise web.HTTPBadRequest(text=f"{key} không hợp lệ")
    if not lo <= n <= hi:
        raise web.HTTPBadRequest(text=f"{key} ngoài phạm vi")
    return n


def _render(request: web.Request, title: str, body: str, active: str) -> web.Response:
    page = v.layout(title=title, body=body, csrf=request["session"]["csrf"], active=active, msg=_msg(request))
    return web.Response(text=page, content_type="text/html")


def _guild_label(bot, guild_id: int) -> str:
    g = bot.get_guild(guild_id) if guild_id else None
    return g.name if g else (f"(id {guild_id})" if guild_id else "?")


def _channel_label(bot, channel_id: int) -> str:
    ch = bot.get_channel(channel_id)
    return f"#{ch.name}" if ch is not None and hasattr(ch, "name") else f"(kênh {channel_id})"


# ---------------------------------------------------------------- middleware
@web.middleware
async def security_middleware(request: web.Request, handler):
    try:
        if request.path != "/login":
            session = request.app["sessions"].get(request.cookies.get(COOKIE))
            if session is None:
                raise web.HTTPFound("/login")
            request["session"] = session
        resp = await handler(request)
    except web.HTTPException as ex:
        resp = ex
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    )
    return resp


# ---------------------------------------------------------------- đăng nhập
# Chỉ bật khi dashboard thật sự nằm sau reverse proxy mình kiểm soát (nginx, Caddy, Cloudflare Tunnel...).
# Nếu bật mà KHÔNG có proxy, người ngoài có thể giả header X-Forwarded-For để né rate limit.
TRUST_PROXY = os.getenv("DASHBOARD_TRUST_PROXY", "false").strip().lower() in ("1", "true", "yes", "on")


def _client_ip(request: web.Request) -> str:
    """IP của client. Sau reverse proxy, request.remote là IP của proxy → mọi người dùng chung
    một bộ đếm rate limit. Khi DASHBOARD_TRUST_PROXY=true thì lấy IP do proxy ghi nhận."""
    if TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            # Lấy mục ngoài cùng bên phải: đó là IP proxy của mình thấy, phần bên trái do client tự khai.
            candidate = forwarded.split(",")[-1].strip()
            if candidate:
                return candidate
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
    return request.remote or "?"


async def login_get(request: web.Request):
    return web.Response(text=v.login_page(), content_type="text/html")


async def login_post(request: web.Request):
    app = request.app
    ip = _client_ip(request)
    limiter: v.LoginLimiter = app["limiter"]
    if limiter.blocked(ip):
        return web.Response(text=v.login_page("Sai quá nhiều lần, thử lại sau 10 phút."),
                            content_type="text/html", status=429)
    data = await request.post()
    given = str(data.get("password", "")).encode()
    if not hmac.compare_digest(given, app["password"].encode()):
        limiter.fail(ip)
        log.warning("Đăng nhập dashboard thất bại từ %s", ip)
        await asyncio.sleep(1)
        return web.Response(text=v.login_page("Sai mật khẩu."), content_type="text/html", status=401)
    limiter.reset(ip)
    token, _ = app["sessions"].create()
    resp = web.HTTPFound("/")
    resp.set_cookie(COOKIE, token, max_age=app["sessions"].ttl, httponly=True, samesite="Strict",
                    secure=config.DASHBOARD_SECURE_COOKIE, path="/")
    log.info("Đăng nhập dashboard thành công từ %s", ip)
    raise resp


async def logout_post(request: web.Request):
    await _form(request)
    request.app["sessions"].delete(request.cookies.get(COOKIE))
    resp = web.HTTPFound("/login")
    resp.del_cookie(COOKIE, path="/")
    raise resp


# ---------------------------------------------------------------- trang
async def overview(request: web.Request):
    ctx: Ctx = request.app["ctx"]
    bot = ctx.bot
    cache = request.app["disk_cache"]
    if time.time() - cache["at"] > 120:
        cache["value"] = await asyncio.to_thread(get_dir_size, str(config.BASE_DIR))
        cache["at"] = time.time()
    reminders = await ctx.db.list_all_active_reminders()
    per_guild: dict[int, int] = {}
    for r in reminders:
        per_guild[r["guild_id"]] = per_guild.get(r["guild_id"], 0) + 1
    guilds = []
    for g in bot.guilds:
        ids = {c.id for c in g.text_channels}
        guilds.append({"name": g.name, "id": g.id, "members": g.member_count or 0,
                       "autochat": len(ids & ctx.auto_chat_channels), "reminders": per_guild.get(g.id, 0)})
    stats = {
        "ping_ms": round(bot.latency * 1000) if bot.latency == bot.latency else 0,
        "uptime": datetime.now(timezone.utc) - START_TIME,
        "guild_count": len(bot.guilds),
        "members": sum(g["members"] for g in guilds),
        "ram": psutil.Process(os.getpid()).memory_info().rss,
        "ram_limit": get_memory_limit_bytes(),
        "disk": cache["value"],
        "db_size": os.path.getsize(config.DB_PATH) if os.path.exists(config.DB_PATH) else 0,
        "reminders": len(reminders),
        "autochat": len(ctx.auto_chat_channels),
        "model": config.GEMINI_MODEL,
        "python": platform.python_version(),
        "dpy": discord.__version__,
    }
    return _render(request, "Tổng quan", v.overview_body(stats, guilds), "/")


async def reminders_get(request: web.Request):
    ctx: Ctx = request.app["ctx"]
    rows = []
    for r in await ctx.db.list_all_active_reminders():
        nxt = datetime.fromisoformat(r["next_run_utc"]).astimezone(config.VN_TZ)
        msg = r["message"] if len(r["message"]) <= 150 else r["message"][:147] + "..."
        rows.append({
            "id": r["id"], "guild": _guild_label(ctx.bot, r["guild_id"]),
            "channel": _channel_label(ctx.bot, r["channel_id"]), "repeat": r["repeat"],
            "hhmm": f"{r['hour']:02d}:{r['minute']:02d}", "next_run": nxt.strftime("%H:%M %d/%m/%Y"),
            "creator": r["created_by"], "message": msg,
        })
    return _render(request, "Reminder", v.reminders_body(rows, request["session"]["csrf"]), "/reminders")


async def reminders_cancel(request: web.Request):
    form = await _form(request)
    rid = _int(form, "id", 1)
    ok = await request.app["ctx"].db.deactivate_reminder(rid)
    log.info("Dashboard hủy reminder #%s (%s)", rid, ok)
    raise _redirect("/reminders", f"Đã hủy #{rid}" if ok else f"Không tìm thấy #{rid}")


def _allowed_guilds(bot):
    return [g for g in bot.guilds if not config.ALLOWED_GUILD_IDS or g.id in config.ALLOWED_GUILD_IDS]


async def autochat_get(request: web.Request):
    ctx: Ctx = request.app["ctx"]
    entries, choices = [], []
    for g in _allowed_guilds(ctx.bot):
        for ch in g.text_channels:
            if ch.id in ctx.auto_chat_channels:
                entries.append({"guild": g.name, "channel": ch.name, "channel_id": ch.id})
        usable = [(ch.id, ch.name) for ch in g.text_channels
                  if ch.permissions_for(g.me).view_channel and ch.permissions_for(g.me).send_messages
                  and ch.id not in ctx.auto_chat_channels]
        if usable:
            choices.append((g.name, usable))
    return _render(request, "Auto-Chat", v.autochat_body(entries, choices, request["session"]["csrf"]), "/autochat")


async def autochat_add(request: web.Request):
    ctx: Ctx = request.app["ctx"]
    form = await _form(request)
    ch = ctx.bot.get_channel(_int(form, "channel_id", 1))
    if not isinstance(ch, discord.TextChannel) or ch.guild not in _allowed_guilds(ctx.bot):
        raise _redirect("/autochat", "Kênh không hợp lệ")
    await ctx.db.add_auto_chat_channel(ch.id, ch.guild.id, 0)  # added_by = 0 → thêm từ dashboard
    ctx.auto_chat_channels.add(ch.id)
    log.info("Dashboard bật auto-chat ở #%s (%s)", ch.name, ch.id)
    raise _redirect("/autochat", f"Đã bật auto-chat ở #{ch.name}")


async def autochat_remove(request: web.Request):
    ctx: Ctx = request.app["ctx"]
    form = await _form(request)
    cid = _int(form, "channel_id", 1)
    await ctx.db.remove_auto_chat_channel(cid)
    ctx.auto_chat_channels.discard(cid)
    log.info("Dashboard tắt auto-chat ở kênh %s", cid)
    raise _redirect("/autochat", "Đã tắt auto-chat")


async def history_get(request: web.Request):
    ctx: Ctx = request.app["ctx"]
    body = v.history_body(await ctx.db.count_history(), len(ctx.history_cache),
                          config.HISTORY_RETENTION_DAYS, request["session"]["csrf"])
    return _render(request, "Lịch sử hội thoại", body, "/history")


async def history_purge(request: web.Request):
    ctx: Ctx = request.app["ctx"]
    days = _int(await _form(request), "days", 1, 3650)
    n = await ctx.db.purge_old_history(days)
    ctx.history_cache.clear()
    raise _redirect("/history", f"Đã xóa {n} hội thoại cũ hơn {days} ngày")


async def history_delete_user(request: web.Request):
    ctx: Ctx = request.app["ctx"]
    form = await _form(request)
    g, u = _int(form, "guild_id", 1), _int(form, "user_id", 1)
    await ctx.db.delete_history(g, u)
    ctx.history_cache.pop((g, u), None)
    raise _redirect("/history", f"Đã xóa lịch sử của user {u}")


async def history_delete_all(request: web.Request):
    ctx: Ctx = request.app["ctx"]
    form = await _form(request)
    if form.get("confirm") != "yes":
        raise _redirect("/history", "Chưa tick ô xác nhận")
    n = await ctx.db.delete_all_history()
    ctx.history_cache.clear()
    log.warning("Dashboard xóa toàn bộ lịch sử (%d)", n)
    raise _redirect("/history", f"Đã xóa toàn bộ ({n}) hội thoại")


async def history_clear_cache(request: web.Request):
    await _form(request)
    request.app["ctx"].history_cache.clear()
    raise _redirect("/history", "Đã làm trống cache")


async def logs_get(request: web.Request):
    return _render(request, "Log", v.logs_body(list(log_buffer.lines)[-300:]), "/logs")


async def settings_get(request: web.Request):
    items = [
        ("GEMINI_MODEL", config.GEMINI_MODEL), ("MAX_OUTPUT_TOKENS", config.MAX_OUTPUT_TOKENS),
        ("THINKING_BUDGET", config.THINKING_BUDGET), ("GEMINI_TIMEOUT", config.GEMINI_TIMEOUT),
        ("GEMINI_CONCURRENCY", config.GEMINI_CONCURRENCY), ("MAX_HISTORY_TURNS", config.MAX_HISTORY_TURNS),
        ("HISTORY_RETENTION_DAYS", config.HISTORY_RETENTION_DAYS), ("MAX_IMAGES", config.MAX_IMAGES),
        ("MAX_IMAGE_MB", config.MAX_IMAGE_BYTES // (1024 * 1024)),
        ("STATUS", f"{config.STATUS_TYPE}: {config.STATUS_TEXT}"),
        ("ALLOWED_GUILD_IDS", ", ".join(map(str, sorted(config.ALLOWED_GUILD_IDS))) or "(không giới hạn)"),
        ("ADMIN_ROLE_IDS", ", ".join(map(str, sorted(config.ADMIN_ROLE_IDS))) or "(trống)"),
        ("MEMBERS_INTENT", config.MEMBERS_INTENT), ("MAX_REMINDERS_PER_USER", config.MAX_REMINDERS_PER_USER),
        ("REMINDER_GRACE_MINUTES", config.REMINDER_GRACE_MINUTES), ("DB_PATH", config.DB_PATH),
        ("DASHBOARD", f"{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}"),
    ]
    return _render(request, "Cấu hình (chỉ xem)", v.settings_body(items, config.SYSTEM_PROMPT), "/settings")


# ---------------------------------------------------------------- khởi tạo
def create_app(ctx: Ctx, password: str | None = None) -> web.Application:
    app = web.Application(middlewares=[security_middleware], client_max_size=64 * 1024)
    app["ctx"] = ctx
    app["password"] = password if password is not None else config.DASHBOARD_PASSWORD
    app["sessions"] = v.SessionStore()
    app["limiter"] = v.LoginLimiter()
    app["disk_cache"] = {"at": 0.0, "value": 0}
    app.add_routes([
        web.get("/login", login_get), web.post("/login", login_post), web.post("/logout", logout_post),
        web.get("/", overview),
        web.get("/reminders", reminders_get), web.post("/reminders/cancel", reminders_cancel),
        web.get("/autochat", autochat_get), web.post("/autochat/add", autochat_add),
        web.post("/autochat/remove", autochat_remove),
        web.get("/history", history_get), web.post("/history/purge", history_purge),
        web.post("/history/delete_user", history_delete_user),
        web.post("/history/delete_all", history_delete_all),
        web.post("/history/clear_cache", history_clear_cache),
        web.get("/logs", logs_get), web.get("/settings", settings_get),
    ])
    return app


async def start_dashboard(ctx: Ctx) -> web.AppRunner:
    if len(config.DASHBOARD_PASSWORD) < 12:
        raise RuntimeError("DASHBOARD_PASSWORD phải có ít nhất 12 ký tự")
    runner = web.AppRunner(create_app(ctx), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, config.DASHBOARD_HOST, config.DASHBOARD_PORT).start()
    log.info("Dashboard chạy tại http://%s:%s", config.DASHBOARD_HOST, config.DASHBOARD_PORT)
    if config.DASHBOARD_HOST not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Dashboard đang mở ra ngoài localhost qua HTTP thường — mật khẩu đi không mã hóa. "
                    "Hãy đặt sau reverse proxy HTTPS (và bật DASHBOARD_SECURE_COOKIE=true) hoặc dùng SSH tunnel.")
    return runner
