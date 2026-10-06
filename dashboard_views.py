"""Giao diện + logic thuần của dashboard (không phụ thuộc aiohttp/discord → dễ test)."""
from __future__ import annotations

import html
import secrets
import time

from utils import format_bytes, format_uptime

CSS = """
:root{--bg:#f6f7f9;--fg:#1c1f24;--card:#fff;--line:#e2e5ea;--acc:#5865f2;--bad:#d83c3e;--ok:#2d9d5c}
@media(prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e8eaee;--card:#1e2126;--line:#2e333a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
header{display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center;padding:.6rem 1rem;background:var(--card);border-bottom:1px solid var(--line)}
nav{display:flex;flex-wrap:wrap;gap:.25rem;flex:1}nav a{padding:.3rem .7rem;border-radius:6px;color:inherit;text-decoration:none}
nav a.on{background:var(--acc);color:#fff}main{max-width:1000px;margin:0 auto;padding:1rem}
h1{font-size:1.3rem;margin:.2rem 0 1rem}h2{font-size:1.05rem;margin:1.4rem 0 .5rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.7rem .9rem}
.card b{display:block;font-size:1.15rem}.card span{opacity:.65;font-size:.85rem}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%}th,td{padding:.45rem .7rem;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.8rem;opacity:.7}tr:last-child td{border-bottom:0}
input,select,button{font:inherit;padding:.4rem .6rem;border-radius:6px;border:1px solid var(--line);background:var(--card);color:inherit}
button{background:var(--acc);color:#fff;border:0;cursor:pointer}button.bad{background:var(--bad)}button.ghost{background:none;color:inherit;border:1px solid var(--line)}
form.inline{display:inline}form.row{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.4rem 0}
.flash{background:var(--ok);color:#fff;padding:.5rem .8rem;border-radius:8px;margin-bottom:1rem}
.err{background:var(--bad)}pre{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.7rem;overflow:auto;font-size:.8rem;max-height:70vh}
.muted{opacity:.65}.login{max-width:340px;margin:12vh auto;padding:1rem}
"""

NAV = [
    ("/", "Tổng quan"),
    ("/autochat", "Auto-Chat"),
    ("/reminders", "Reminder"),
    ("/history", "Lịch sử"),
    ("/logs", "Log"),
    ("/settings", "Cấu hình"),
]


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _doc(title: str, inner: str) -> str:
    return (
        '<!doctype html><html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)} · Gemini Dashboard</title><style>{CSS}</style></head>"
        f"<body>{inner}</body></html>"
    )


def layout(*, title: str, body: str, csrf: str, active: str, msg: str = "") -> str:
    nav = "".join(
        f'<a href="{h}"{" class=on" if h == active else ""}>{esc(label)}</a>' for h, label in NAV
    )
    flash = f'<div class="flash">{esc(msg)}</div>' if msg else ""
    inner = (
        f"<header><strong>🤖 Gemini Dashboard</strong><nav>{nav}</nav>"
        f'<form class="inline" method="post" action="/logout">'
        f'<input type="hidden" name="csrf" value="{esc(csrf)}"><button class="ghost">Đăng xuất</button></form>'
        f"</header><main>{flash}<h1>{esc(title)}</h1>{body}</main>"
    )
    return _doc(title, inner)


def login_page(error: str = "") -> str:
    err = f'<div class="flash err">{esc(error)}</div>' if error else ""
    inner = (
        '<div class="login"><h1>🤖 Gemini Dashboard</h1>' + err +
        '<form method="post" action="/login" class="row">'
        '<input type="password" name="password" placeholder="Mật khẩu" autocomplete="current-password" '
        'required autofocus style="flex:1"><button>Đăng nhập</button></form></div>'
    )
    return _doc("Đăng nhập", inner)


def table(headers: list[str], rows: list[list[str]], empty: str = "Không có dữ liệu.") -> str:
    """`rows` chứa HTML đã được escape sẵn bởi người gọi."""
    if not rows:
        return f'<p class="muted">{esc(empty)}</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="wrap"><table><tr>{head}</tr>{body}</table></div>'


def post_form(action: str, csrf: str, fields: str, button: str, *, inline=False, bad=False) -> str:
    cls = "inline" if inline else "row"
    return (
        f'<form class="{cls}" method="post" action="{esc(action)}">'
        f'<input type="hidden" name="csrf" value="{esc(csrf)}">{fields}'
        f'<button class="{"bad" if bad else ""}">{esc(button)}</button></form>'
    )


def hidden(name: str, value) -> str:
    return f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'


# ----------------------------------------------------------------- các trang
def overview_body(stats: dict, guilds: list[dict]) -> str:
    cards = [
        ("Ping", f"{stats['ping_ms']} ms"),
        ("Uptime", format_uptime(stats["uptime"])),
        ("Server", stats["guild_count"]),
        ("Thành viên", f"{stats['members']:,}".replace(",", ".")),
        ("RAM", f"{format_bytes(stats['ram'])} / {format_bytes(stats['ram_limit'])}"),
        ("Disk (thư mục bot)", format_bytes(stats["disk"])),
        ("Database", format_bytes(stats["db_size"])),
        ("Reminder đang chạy", stats["reminders"]),
        ("Kênh auto-chat", stats["autochat"]),
        ("Model", stats["model"]),
        ("Python / discord.py", f"{stats['python']} / {stats['dpy']}"),
    ]
    html_cards = "".join(f'<div class="card"><b>{esc(v)}</b><span>{esc(k)}</span></div>' for k, v in cards)
    rows = [
        [esc(g["name"]), esc(g["id"]), esc(g["members"]), esc(g["autochat"]), esc(g["reminders"])]
        for g in guilds
    ]
    return (
        f'<div class="cards">{html_cards}</div><h2>Server</h2>'
        + table(["Tên", "ID", "Thành viên", "Auto-Chat", "Reminder"], rows, "Bot chưa ở server nào.")
    )


def reminders_body(rows: list[dict], csrf: str) -> str:
    out = []
    for r in rows:
        out.append([
            f"#{esc(r['id'])}", esc(r["guild"]), esc(r["channel"]),
            esc("hàng ngày" if r["repeat"] == "daily" else "1 lần") + f" {esc(r['hhmm'])}",
            esc(r["next_run"]), esc(r["creator"]),
            esc(r["message"]),
            post_form("/reminders/cancel", csrf, hidden("id", r["id"]), "Hủy", inline=True, bad=True),
        ])
    return table(["ID", "Server", "Kênh", "Lịch", "Lần tới (VN)", "Người tạo", "Nội dung", ""], out,
                 "Chưa có reminder nào đang hoạt động.")


def autochat_body(entries: list[dict], choices: list[tuple[str, list[tuple[int, str]]]], csrf: str) -> str:
    rows = [
        [esc(e["guild"]), "#" + esc(e["channel"]),
         post_form("/autochat/remove", csrf, hidden("channel_id", e["channel_id"]), "Tắt", inline=True, bad=True)]
        for e in entries
    ]
    groups = "".join(
        f'<optgroup label="{esc(g)}">'
        + "".join(f'<option value="{cid}">#{esc(name)}</option>' for cid, name in chans)
        + "</optgroup>"
        for g, chans in choices
    )
    add = post_form("/autochat/add", csrf, f'<select name="channel_id" required>{groups}</select>', "Bật auto-chat")
    return table(["Server", "Kênh", ""], rows, "Chưa kênh nào bật auto-chat.") + "<h2>Thêm kênh</h2>" + add


def history_body(count: int, cache: int, retention: int, csrf: str) -> str:
    cards = (
        f'<div class="cards"><div class="card"><b>{count}</b><span>Hội thoại trong DB</span></div>'
        f'<div class="card"><b>{cache}</b><span>Trong cache RAM</span></div>'
        f'<div class="card"><b>{esc(str(retention) + " ngày" if retention else "tắt")}</b>'
        f"<span>Tự xóa sau</span></div></div>"
    )
    purge = post_form("/history/purge", csrf,
                      '<label>Xóa lịch sử cũ hơn <input type="number" name="days" min="1" max="3650" value="30" '
                      'style="width:6rem"> ngày</label>', "Xóa")
    user = post_form("/history/delete_user", csrf,
                     '<input name="guild_id" placeholder="Guild ID" inputmode="numeric" required>'
                     '<input name="user_id" placeholder="User ID" inputmode="numeric" required>', "Xóa của user", bad=True)
    everything = post_form("/history/delete_all", csrf,
                           '<label><input type="checkbox" name="confirm" value="yes"> Tôi chắc chắn</label>',
                           "Xóa toàn bộ", bad=True)
    clear = post_form("/history/clear_cache", csrf, "", "Làm trống cache RAM")
    return (cards + "<h2>Dọn dẹp theo thời gian</h2>" + purge + "<h2>Xóa theo người dùng</h2>" + user
            + "<h2>Xóa tất cả</h2>" + everything + "<h2>Cache</h2>" + clear)


def logs_body(lines: list[str]) -> str:
    text = "\n".join(lines) if lines else "(chưa có log)"
    return f'<p><a href="/logs">↻ Tải lại</a> <span class="muted">· {len(lines)} dòng gần nhất</span></p><pre>{esc(text)}</pre>'


def settings_body(items: list[tuple[str, object]], prompt: str) -> str:
    rows = [[f"<code>{esc(k)}</code>", esc(v)] for k, v in items]
    return (
        '<p class="muted">Chỉ xem. Muốn đổi cấu hình hãy sửa <code>.env</code> rồi khởi động lại bot. '
        "Token và API key không bao giờ hiển thị ở đây.</p>"
        + table(["Biến", "Giá trị"], rows)
        + f"<h2>System prompt</h2><details><summary>Xem ({len(prompt)} ký tự)</summary><pre>{esc(prompt)}</pre></details>"
    )


# ----------------------------------------------------------------- phiên & rate limit
class SessionStore:
    def __init__(self, ttl: int = 12 * 3600):
        self.ttl = ttl
        self._sessions: dict[str, dict] = {}

    def create(self) -> tuple[str, str]:
        now = time.time()
        self._sessions = {t: s for t, s in self._sessions.items() if s["exp"] > now}
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        self._sessions[token] = {"csrf": csrf, "exp": now + self.ttl}
        return token, csrf

    def get(self, token: str | None) -> dict | None:
        if not token:
            return None
        s = self._sessions.get(token)
        if s and s["exp"] > time.time():
            return s
        self._sessions.pop(token, None)
        return None

    def delete(self, token: str | None) -> None:
        self._sessions.pop(token or "", None)


class LoginLimiter:
    def __init__(self, max_fails: int = 5, window: int = 600):
        self.max_fails, self.window = max_fails, window
        self._fails: dict[str, list[float]] = {}

    def _recent(self, ip: str, now: float) -> list[float]:
        recent = [t for t in self._fails.get(ip, []) if now - t < self.window]
        if recent:
            self._fails[ip] = recent
        else:
            self._fails.pop(ip, None)
        return recent

    def blocked(self, ip: str, now: float | None = None) -> bool:
        return len(self._recent(ip, now or time.time())) >= self.max_fails

    def fail(self, ip: str, now: float | None = None) -> None:
        now = now or time.time()
        self._fails.setdefault(ip, []).append(now)

    def reset(self, ip: str) -> None:
        self._fails.pop(ip, None)
