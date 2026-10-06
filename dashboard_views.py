from __future__ import annotations

import html
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict, deque
from threading import Lock

_HERE = Path(__file__).resolve().parent
_STATIC_DIR = _HERE / "static"
_TEMPLATE_DIR = _HERE / "templates"
_cache: dict[str, str] = {}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _load(name: str, path: Path) -> str:
    if name not in _cache:
        try:
            _cache[name] = path.read_text(encoding="utf-8")
        except OSError:
            _cache[name] = ""
    return _cache[name]


def get_css() -> str:
    return _load("css", _STATIC_DIR / "dashboard.css")


def _render(tpl_name: str, repl: dict[str, str]) -> str:
    tpl = _load(tpl_name, _TEMPLATE_DIR / tpl_name)
    if not tpl:
        raise RuntimeError(f"Không tìm thấy template dashboard: {tpl_name}")
    out = tpl
    for key, value in repl.items():
        out = out.replace(f"__{key}__", value)
    return out


@dataclass(frozen=True)
class Session:
    csrf: str
    created_at: float
    expires_at: float


class SessionStore:
    """In-memory server-side sessions.

    Tokens are high-entropy random values and only the opaque token is stored in
    the browser. Sessions expire automatically and are never persisted to disk.
    """

    def __init__(self, ttl: int = 12 * 60 * 60):
        self.ttl = ttl
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def _purge_locked(self, now: float) -> None:
        expired = [token for token, session in self._sessions.items()
                   if session.expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)

    def create(self) -> tuple[str, Session]:
        now = time.time()
        token = secrets.token_urlsafe(32)
        session = Session(
            csrf=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + self.ttl,
        )
        with self._lock:
            self._purge_locked(now)
            self._sessions[token] = session
        return token, session

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            session = self._sessions.get(token)
            if session is None or session.expires_at <= now:
                self._sessions.pop(token, None)
                return None
            return session

    def delete(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._sessions.pop(token, None)


class LoginLimiter:
    """Small in-memory per-IP login limiter.

    Five failed attempts within ten minutes cause a ten-minute cooldown.
    Successful login clears the failure history for that IP.
    """

    def __init__(self, max_failures: int = 5, window: int = 10 * 60,
                 block_time: int = 10 * 60):
        self.max_failures = max_failures
        self.window = window
        self.block_time = block_time
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[str, float] = {}
        self._lock = Lock()

    def _trim(self, ip: str, now: float) -> deque[float]:
        q = self._fails[ip]
        cutoff = now - self.window
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def blocked(self, ip: str) -> bool:
        now = time.time()
        with self._lock:
            until = self._blocked_until.get(ip, 0.0)
            if until > now:
                return True
            self._blocked_until.pop(ip, None)
            self._trim(ip, now)
            return False

    def fail(self, ip: str) -> None:
        now = time.time()
        with self._lock:
            q = self._trim(ip, now)
            q.append(now)
            if len(q) >= self.max_failures:
                self._blocked_until[ip] = now + self.block_time

    def reset(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)
            self._blocked_until.pop(ip, None)


NAV = (
    ("/", "Tổng quan"),
    ("/autochat", "Auto-Chat"),
    ("/reminders", "Reminder"),
    ("/history", "Lịch sử"),
    ("/logs", "Log"),
    ("/settings", "Cấu hình"),
)

_ICONS = {
    "/": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9 21v-6h6v6"/>',
    "/autochat": '<path d="M4 5h16v11H7l-3 3V5Z"/><path d="M8 9h8M8 12h5"/>',
    "/reminders": '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    "/history": '<path d="M4 5h16v14H4z"/><path d="M8 9h8M8 13h6M8 17h4"/>',
    "/logs": '<path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "/settings": '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><circle cx="12" cy="12" r="5"/>',
}


def _doc(title: str, inner: str) -> str:
    return _render("login.html", {"TITLE": esc(title), "ERROR": inner})


def layout(*, title: str, body: str, csrf: str, active: str, msg: str = "") -> str:
    nav = "".join(
        f'<a href="{esc(href)}"{(" class=\"on\" aria-current=\"page\"" if href == active else "")}>'
        f'<svg viewBox="0 0 24 24" aria-hidden="true">{_ICONS.get(href, "")}</svg>'
        f'<span>{esc(label)}</span></a>'
        for href, label in NAV
    )
    flash = f'<div class="flash" role="status">{esc(msg)}</div>' if msg else ""
    return _render("dashboard.html", {
        "TITLE": esc(title),
        "NAV": nav,
        "CSRF": esc(csrf),
        "FLASH": flash,
        "BODY": body,
    })


def login_page(error: str = "") -> str:
    err = f'<div class="flash err" role="alert">{esc(error)}</div>' if error else ""
    return _render("login.html", {"TITLE": "Đăng nhập", "ERROR": err})


def _bytes(n: int | float | None) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return "—"


def _duration(value) -> str:
    seconds = max(0, int(value.total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days: parts.append(f"{days}d")
    if hours or days: parts.append(f"{hours}h")
    if minutes or hours or days: parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _cards(items: list[tuple[str, str]]) -> str:
    return '<section class="cards">' + "".join(
        f'<article class="card"><b>{esc(value)}</b><span>{esc(label)}</span></article>'
        for label, value in items
    ) + '</section>'


def overview_body(stats: dict, guilds: list[dict]) -> str:
    cards = _cards([
        ("Ping", f"{stats['ping_ms']} ms"),
        ("Uptime", _duration(stats["uptime"])),
        ("Server", str(stats["guild_count"])),
        ("Members", str(stats["members"])),
        ("RAM", _bytes(stats["ram"])),
        ("Disk", _bytes(stats["disk"])),
        ("Database", _bytes(stats["db_size"])),
        ("Reminder", str(stats["reminders"])),
        ("Auto-Chat", str(stats["autochat"])),
    ])
    rows = "".join(
        '<tr>'
        f'<td data-label="Server"><strong>{esc(g["name"])}</strong><div class="muted">ID {esc(g["id"])}</div></td>'
        f'<td data-label="Members">{esc(g["members"])}</td>'
        f'<td data-label="Auto-Chat">{esc(g["autochat"])}</td>'
        f'<td data-label="Reminder">{esc(g["reminders"])}</td>'
        '</tr>' for g in guilds
    ) or '<tr><td colspan="4" class="muted">Bot chưa tham gia server nào.</td></tr>'
    return cards + f'''\n<h2>Server</h2>\n<div class="wrap"><table><thead><tr><th>Server</th><th>Members</th><th>Auto-Chat</th><th>Reminder</th></tr></thead><tbody>{rows}</tbody></table></div>\n<details><summary>Runtime</summary><dl class="kv"><div><dt>Model</dt><dd>{esc(stats["model"])}</dd></div><div><dt>Python</dt><dd>{esc(stats["python"])}</dd></div><div><dt>discord.py</dt><dd>{esc(stats["dpy"])}</dd></div><div><dt>RAM limit</dt><dd>{esc(_bytes(stats["ram_limit"]))}</dd></div></dl></details>'''


def reminders_body(rows: list[dict], csrf: str) -> str:
    body = "".join(
        '<tr>'
        f'<td data-label="ID">#{esc(r["id"])}</td>'
        f'<td data-label="Server">{esc(r["guild"])}</td>'
        f'<td data-label="Kênh">{esc(r["channel"])}</td>'
        f'<td data-label="Lặp">{esc(r["repeat"])} · {esc(r["hhmm"])}</td>'
        f'<td data-label="Lần tới">{esc(r["next_run"])}</td>'
        f'<td data-label="Nội dung"><span class="wrap-text">{esc(r["message"])}</span></td>'
        f'<td data-label="Thao tác"><form method="post" action="/reminders/cancel" class="inline"><input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="id" value="{esc(r["id"])}"><button class="bad" type="submit">Hủy</button></form></td>'
        '</tr>' for r in rows
    ) or '<tr><td colspan="7" class="muted">Không có reminder đang chạy.</td></tr>'
    return '<div class="wrap"><table><thead><tr><th>ID</th><th>Server</th><th>Kênh</th><th>Lặp</th><th>Lần tới</th><th>Nội dung</th><th></th></tr></thead><tbody>' + body + '</tbody></table></div>'


def autochat_body(entries: list[dict], choices: list[tuple[str, list[tuple[int, str]]]], csrf: str) -> str:
    active = "".join(
        '<li><span><strong>#' + esc(e["channel"]) + '</strong> · ' + esc(e["guild"]) + '</span>'
        f'<form method="post" action="/autochat/remove" class="inline"><input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="channel_id" value="{esc(e["channel_id"])}"><button class="bad" type="submit">Tắt</button></form></li>'
        for e in entries
    ) or '<li class="muted">Chưa có kênh Auto-Chat.</li>'
    opts = ''.join(
        f'<optgroup label="{esc(guild)}">' + ''.join(f'<option value="{esc(cid)}">#{esc(name)}</option>' for cid, name in channels) + '</optgroup>'
        for guild, channels in choices
    )
    add = ('<form method="post" action="/autochat/add" class="row">'
           f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
           f'<select name="channel_id" required>{opts}</select><button type="submit">Bật Auto-Chat</button></form>') if opts else '<p class="muted">Không có kênh khả dụng để bật Auto-Chat.</p>'
    return f'<h2>Đang bật</h2><ul class="items">{active}</ul><h2>Thêm kênh</h2>{add}'


def history_body(count: int, cache_len: int, retention: int, csrf: str) -> str:
    return f'''{_cards([("Bản ghi lịch sử", str(count)), ("Cache trong RAM", str(cache_len)), ("Tự xóa sau", f"{retention} ngày" if retention else "Tắt")])}
<h2>Dọn lịch sử</h2>
<form method="post" action="/history/purge" class="row"><input type="hidden" name="csrf" value="{esc(csrf)}"><label for="days">Cũ hơn</label><input id="days" name="days" type="number" min="1" max="3650" value="{esc(retention or 30)}" required><span>ngày</span><button type="submit">Xóa</button></form>
<h2>Xóa theo user</h2>
<form method="post" action="/history/delete_user" class="row"><input type="hidden" name="csrf" value="{esc(csrf)}"><input name="guild_id" type="number" min="1" placeholder="Guild ID" required><input name="user_id" type="number" min="1" placeholder="User ID" required><button type="submit">Xóa lịch sử user</button></form>
<h2>Toàn bộ</h2>
<form method="post" action="/history/delete_all" class="row"><input type="hidden" name="csrf" value="{esc(csrf)}"><label><input type="checkbox" name="confirm" value="yes" required> Tôi hiểu thao tác này không thể hoàn tác.</label><button class="bad" type="submit">Xóa toàn bộ</button></form>
<form method="post" action="/history/clear_cache" class="row"><input type="hidden" name="csrf" value="{esc(csrf)}"><button class="ghost" type="submit">Xóa cache RAM</button></form>'''


def logs_body(lines: list[str]) -> str:
    text = "\n".join(lines) if lines else "Chưa có log."
    return f'<pre aria-label="Dashboard logs">{esc(text)}</pre>'


def settings_body(items: list[tuple[str, object]], prompt: str) -> str:
    rows = "".join(f'<div><dt>{esc(k)}</dt><dd><code>{esc(v)}</code></dd></div>' for k, v in items)
    return f'<dl class="kv">{rows}</dl><h2>System prompt</h2><details><summary>Xem prompt</summary><pre>{esc(prompt)}</pre></details>'
