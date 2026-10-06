from __future__ import annotations

import html
import secrets
import time
from dataclasses import dataclass
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_STATIC_DIR = _HERE / "static"
_TEMPLATE_DIR = _HERE / "templates"

_cache: dict[str, str] = {}


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _load(name: str, path: Path) -> str:
    """Đọc file 1 lần, cache lại. Trả về chuỗi rỗng nếu thiếu."""
    if name not in _cache:
        try:
            _cache[name] = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            _cache[name] = ""
    return _cache[name]


def get_css() -> str:
    """Trả về nội dung dashboard.css."""
    return _load("css", _STATIC_DIR / "dashboard.css")


def _render(tpl_name: str, repl: dict[str, str]) -> str:
    tpl = _load(tpl_name, _TEMPLATE_DIR / tpl_name)
    out = tpl

    for k, v in repl.items():
        out = out.replace(f"__{k}__", str(v))

    return out


# =========================================================
# SESSION
# =========================================================

@dataclass
class Session:
    token: str
    csrf: str
    created_at: float


class SessionStore:
    def __init__(self, ttl: int = 60 * 60 * 24 * 7):
        self.ttl = ttl
        self._sessions: dict[str, Session] = {}

    def create(self):
        self._cleanup()

        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)

        session = Session(
            token=token,
            csrf=csrf,
            created_at=time.time(),
        )

        self._sessions[token] = session
        return token, session

    def get(self, token: str | None):
        if not token:
            return None

        session = self._sessions.get(token)

        if session is None:
            return None

        if time.time() - session.created_at > self.ttl:
            self._sessions.pop(token, None)
            return None

        return session

    def delete(self, token: str | None):
        if token:
            self._sessions.pop(token, None)

    def _cleanup(self):
        now = time.time()

        dead = [
            token
            for token, session in self._sessions.items()
            if now - session.created_at > self.ttl
        ]

        for token in dead:
            self._sessions.pop(token, None)


# =========================================================
# LOGIN RATE LIMIT
# =========================================================

class LoginLimiter:
    def __init__(
        self,
        max_failures: int = 8,
        block_seconds: int = 600,
    ):
        self.max_failures = max_failures
        self.block_seconds = block_seconds
        self._data: dict[str, tuple[int, float]] = {}

    def blocked(self, key: str) -> bool:
        failures, last_time = self._data.get(key, (0, 0.0))

        if failures < self.max_failures:
            return False

        if time.time() - last_time >= self.block_seconds:
            self._data.pop(key, None)
            return False

        return True

    def fail(self, key: str):
        failures, _ = self._data.get(key, (0, 0.0))
        self._data[key] = (failures + 1, time.time())

    def reset(self, key: str):
        self._data.pop(key, None)


# =========================================================
# NAVIGATION
# =========================================================

NAV = [
    ("/", "Tổng quan"),
    ("/reminders", "Reminder"),
    ("/autochat", "Auto-Chat"),
    ("/history", "Lịch sử"),
    ("/logs", "Log"),
    ("/settings", "Cấu hình"),
]


_ICONS = {
    "/": """
        <path d="M3 10.5 12 3l9 7.5"></path>
        <path d="M5 9.5V21h14V9.5"></path>
        <path d="M9 21v-6h6v6"></path>
    """,

    "/reminders": """
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"></path>
        <path d="M10 21h4"></path>
    """,

    "/autochat": """
        <path d="M21 11.5a8.4 8.4 0 0 1-9 8.5 9.7 9.7 0 0 1-4-.8L3 21l1.8-4A8.1 8.1 0 0 1 3 11.5 8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5Z"></path>
        <path d="M8 11h.01M12 11h.01M16 11h.01"></path>
    """,

    "/history": """
        <path d="M3 12a9 9 0 1 0 3-6.7"></path>
        <path d="M3 4v5h5"></path>
        <path d="M12 7v5l3 2"></path>
    """,

    "/logs": """
        <path d="M4 4h16v16H4z"></path>
        <path d="m7 9 3 3-3 3"></path>
        <path d="M12 15h5"></path>
    """,

    "/settings": """
        <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"></path>
        <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-1.8 1.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.1h-2.6V20a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1-1.8-1.8.1-.1A1.7 1.7 0 0 0 8 15a1.7 1.7 0 0 0-1.6-1H6v-2.6h.4A1.7 1.7 0 0 0 8 10a1.7 1.7 0 0 0-.3-1.9l-.1-.1 1.8-1.8.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6v-.1H15v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1 1.8 1.8-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.1V14h-.1a1.7 1.7 0 0 0-1.6 1Z"></path>
    """,
}


def layout(
    *,
    title: str,
    body: str,
    csrf: str,
    active: str,
    msg: str = "",
) -> str:

    nav = "".join(
        f'<a href="{esc(h)}"'
        f'{" class=on" if h == active else ""}>'
        f'<svg viewBox="0 0 24 24" aria-hidden="true">'
        f'{_ICONS.get(h, "")}'
        f'</svg>'
        f'{esc(label)}'
        f'</a>'
        for h, label in NAV
    )

    flash = (
        f'<div class="flash">{esc(msg)}</div>'
        if msg
        else ""
    )

    return _render(
        "dashboard.html",
        {
            "TITLE": esc(title),
            "NAV": nav,
            "CSRF": esc(csrf),
            "FLASH": flash,
            "BODY": body,
        },
    )


def login_page(error: str = "") -> str:
    err = (
        f'<div class="flash err">{esc(error)}</div>'
        if error
        else ""
    )

    return _render(
        "login.html",
        {
            "TITLE": "Đăng nhập",
            "ERROR": err,
        },
    )


# =========================================================
# HELPERS
# =========================================================

def _fmt_bytes(value) -> str:
    try:
        value = float(value)
    except Exception:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]

    for unit in units:
        if abs(value) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"

        value /= 1024

    return "0 B"


def _fmt_uptime(value) -> str:
    try:
        seconds = int(value.total_seconds())
    except Exception:
        return str(value)

    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []

    if days:
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


# =========================================================
# OVERVIEW
# =========================================================

def overview_body(stats: dict, guilds: list[dict]) -> str:

    cards = f"""
    <section class="cards">

        <div class="card stat-card">
            <b>{esc(stats.get("guild_count", 0))}</b>
            <span>Server</span>
        </div>

        <div class="card stat-card">
            <b>{esc(stats.get("members", 0))}</b>
            <span>Members</span>
        </div>

        <div class="card stat-card">
            <b>{esc(stats.get("autochat", 0))}</b>
            <span>Auto-Chat</span>
        </div>

        <div class="card stat-card">
            <b>{esc(stats.get("reminders", 0))}</b>
            <span>Reminder</span>
        </div>

        <div class="card stat-card">
            <b>{esc(stats.get("ping_ms", 0))} ms</b>
            <span>Ping</span>
        </div>

        <div class="card stat-card">
            <b>{esc(_fmt_uptime(stats.get("uptime", 0)))}</b>
            <span>Uptime</span>
        </div>

        <div class="card stat-card">
            <b>{esc(_fmt_bytes(stats.get("ram", 0)))}</b>
            <span>RAM</span>
        </div>

        <div class="card stat-card">
            <b>{esc(_fmt_bytes(stats.get("disk", 0)))}</b>
            <span>Disk</span>
        </div>

    </section>
    """

    server_cards = []

    for g in guilds:
        name = esc(g.get("name", "?"))
        guild_id = esc(g.get("id", "?"))
        members = esc(g.get("members", 0))
        autochat = esc(g.get("autochat", 0))
        reminders = esc(g.get("reminders", 0))

        server_cards.append(
            f"""
            <div class="card server-card">

                <div class="server-title">
                    <span>Server</span>
                    <b title="{name}">{name}</b>
                </div>

                <div class="server-info">

                    <div class="server-row">
                        <span>ID</span>
                        <code title="{guild_id}">{guild_id}</code>
                    </div>

                    <div class="server-row">
                        <span>Members</span>
                        <strong>{members}</strong>
                    </div>

                    <div class="server-row">
                        <span>Auto-Chat</span>
                        <strong>{autochat}</strong>
                    </div>

                    <div class="server-row">
                        <span>Reminder</span>
                        <strong>{reminders}</strong>
                    </div>

                </div>
            </div>
            """
        )

    servers = "".join(server_cards)

    if not servers:
        servers = """
        <div class="card empty-card">
            <b>Chưa có server</b>
            <span>Bot chưa kết nối server nào.</span>
        </div>
        """

    return f"""
    {cards}

    <h2>Server</h2>

    <section class="server-grid">
        {servers}
    </section>

    <h2>Thông tin hệ thống</h2>

    <section class="cards system-cards">

        <div class="card">
            <b>{esc(stats.get("model", "?"))}</b>
            <span>Gemini model</span>
        </div>

        <div class="card">
            <b>{esc(stats.get("python", "?"))}</b>
            <span>Python</span>
        </div>

        <div class="card">
            <b>{esc(stats.get("dpy", "?"))}</b>
            <span>discord.py</span>
        </div>

        <div class="card">
            <b>{esc(stats.get("db_size", 0))}</b>
            <span>Database bytes</span>
        </div>

    </section>
    """


# =========================================================
# REMINDERS
# =========================================================

def reminders_body(rows: list[dict], csrf: str) -> str:

    body_rows = []

    for r in rows:
        body_rows.append(
            f"""
            <tr>
                <td>{esc(r.get("id", ""))}</td>
                <td>{esc(r.get("guild", ""))}</td>
                <td>{esc(r.get("channel", ""))}</td>
                <td>{esc(r.get("hhmm", ""))}</td>
                <td>{esc(r.get("repeat", ""))}</td>
                <td>{esc(r.get("next_run", ""))}</td>
                <td>{esc(r.get("message", ""))}</td>
                <td>
                    <form class="inline" method="post" action="/reminders/cancel">
                        <input type="hidden" name="csrf" value="{esc(csrf)}">
                        <input type="hidden" name="id" value="{esc(r.get("id", ""))}">
                        <button class="bad">Hủy</button>
                    </form>
                </td>
            </tr>
            """
        )

    if not body_rows:
        body_rows.append(
            """
            <tr>
                <td colspan="8" class="muted">
                    Không có reminder đang hoạt động.
                </td>
            </tr>
            """
        )

    return f"""
    <div class="wrap">
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Server</th>
                    <th>Kênh</th>
                    <th>Giờ</th>
                    <th>Lặp</th>
                    <th>Lần chạy tiếp</th>
                    <th>Nội dung</th>
                    <th></th>
                </tr>
            </thead>

            <tbody>
                {"".join(body_rows)}
            </tbody>
        </table>
    </div>
    """


# =========================================================
# AUTO CHAT
# =========================================================

def autochat_body(
    entries: list[dict],
    choices: list[tuple[str, list[tuple[int, str]]]],
    csrf: str,
) -> str:

    current_rows = []

    for item in entries:
        current_rows.append(
            f"""
            <tr>
                <td>{esc(item.get("guild", ""))}</td>
                <td>#{esc(item.get("channel", ""))}</td>
                <td>{esc(item.get("channel_id", ""))}</td>
                <td>
                    <form class="inline" method="post" action="/autochat/remove">
                        <input type="hidden" name="csrf" value="{esc(csrf)}">
                        <input type="hidden" name="channel_id" value="{esc(item.get("channel_id", ""))}">
                        <button class="bad">Tắt</button>
                    </form>
                </td>
            </tr>
            """
        )

    if not current_rows:
        current_rows.append(
            """
            <tr>
                <td colspan="4" class="muted">
                    Chưa có kênh Auto-Chat.
                </td>
            </tr>
            """
        )

    option_html = []

    for guild_name, channels in choices:
        option_html.append(
            f'<optgroup label="{esc(guild_name)}">'
            + "".join(
                f'<option value="{esc(cid)}">'
                f'#{esc(name)}'
                f'</option>'
                for cid, name in channels
            )
            + "</optgroup>"
        )

    return f"""
    <div class="card action-card">
        <b>Bật Auto-Chat</b>

        <form class="row" method="post" action="/autochat/add">
            <input type="hidden" name="csrf" value="{esc(csrf)}">

            <select name="channel_id" required>
                <option value="">-- Chọn kênh --</option>
                {"".join(option_html)}
            </select>

            <button>Bật</button>
        </form>
    </div>

    <h2>Kênh đang bật</h2>

    <div class="wrap">
        <table>
            <thead>
                <tr>
                    <th>Server</th>
                    <th>Kênh</th>
                    <th>ID</th>
                    <th></th>
                </tr>
            </thead>

            <tbody>
                {"".join(current_rows)}
            </tbody>
        </table>
    </div>
    """


# =========================================================
# HISTORY
# =========================================================

def history_body(
    count: int,
    cache_count: int,
    retention_days: int,
    csrf: str,
) -> str:

    return f"""
    <section class="cards">

        <div class="card">
            <b>{esc(count)}</b>
            <span>Tổng hội thoại</span>
        </div>

        <div class="card">
            <b>{esc(cache_count)}</b>
            <span>Cache</span>
        </div>

        <div class="card">
            <b>{esc(retention_days)} ngày</b>
            <span>Retention</span>
        </div>

    </section>

    <h2>Dọn lịch sử</h2>

    <div class="card action-card">

        <form class="row" method="post" action="/history/purge">
            <input type="hidden" name="csrf" value="{esc(csrf)}">

            <input
                type="number"
                name="days"
                min="1"
                max="3650"
                value="{esc(retention_days)}"
                required
            >

            <button class="bad">
                Xóa lịch sử cũ
            </button>
        </form>

    </div>

    <h2>Xóa cache</h2>

    <div class="card action-card">

        <form class="row" method="post" action="/history/clear_cache">
            <input type="hidden" name="csrf" value="{esc(csrf)}">

            <button class="ghost">
                Xóa cache
            </button>
        </form>

    </div>

    <h2>Xóa toàn bộ lịch sử</h2>

    <div class="card action-card danger-card">

        <form class="row" method="post" action="/history/delete_all">

            <input type="hidden" name="csrf" value="{esc(csrf)}">

            <label class="check-row">
                <input
                    type="checkbox"
                    name="confirm"
                    value="yes"
                    required
                >
                Tôi xác nhận muốn xóa toàn bộ lịch sử.
            </label>

            <button class="bad">
                Xóa toàn bộ
            </button>

        </form>

    </div>
    """


# =========================================================
# LOGS
# =========================================================

def logs_body(lines: list[str]) -> str:

    text = "\n".join(str(x) for x in lines)

    return f"""
    <pre>{esc(text)}</pre>
    """


# =========================================================
# SETTINGS
# =========================================================

def settings_body(
    items: list[tuple[str, object]],
    system_prompt: str,
) -> str:

    rows = []

    for key, value in items:
        rows.append(
            f"""
            <tr>
                <th>{esc(key)}</th>
                <td><code>{esc(value)}</code></td>
            </tr>
            """
        )

    return f"""
    <div class="wrap">
        <table>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>

    <h2>System Prompt</h2>

    <pre>{esc(system_prompt)}</pre>
    """
