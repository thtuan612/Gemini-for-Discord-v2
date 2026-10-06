"""Giao diện + logic thuần của dashboard (không phụ thuộc aiohttp/discord → dễ test).

Giao diện theo phong cách iOS: large title, nhóm danh sách bo góc, thanh điều hướng kính mờ,
tab bar dưới cùng trên điện thoại, tự đổi sáng/tối theo hệ thống.
"""

from __future__ import annotations

import html
import secrets
import time

from utils import format_bytes, format_uptime

CSS = """
:root{--bg:#f2f2f7;--fg:#000;--card:#fff;--line:rgba(60,60,67,.18);--fill:rgba(118,118,128,.12);
--sub:rgba(60,60,67,.6);--acc:#007aff;--bad:#ff3b30;--ok:#34c759;--glass:rgba(249,249,249,.78);
--r:14px;--sat:env(safe-area-inset-top,0px);--sab:env(safe-area-inset-bottom,0px)}
@media(prefers-color-scheme:dark){:root{--bg:#000;--fg:#fff;--card:#1c1c1e;--line:rgba(84,84,88,.55);
--fill:rgba(118,118,128,.24);--sub:rgba(235,235,245,.6);--acc:#0a84ff;--bad:#ff453a;--ok:#30d158;
--glass:rgba(29,29,31,.78)}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);
font:17px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,"Helvetica Neue",sans-serif;
-webkit-font-smoothing:antialiased;padding-top:var(--sat)}
header{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:12px;
padding:10px max(16px,calc((100% - 960px)/2));background:var(--glass);
-webkit-backdrop-filter:saturate(180%) blur(22px);backdrop-filter:saturate(180%) blur(22px);
border-bottom:.5px solid var(--line)}
header strong{font-size:17px;font-weight:600;white-space:nowrap}
nav{display:flex;gap:4px;flex:1;overflow-x:auto;scrollbar-width:none}nav::-webkit-scrollbar{display:none}
nav a{display:flex;align-items:center;gap:6px;padding:6px 14px;border-radius:999px;color:var(--sub);
text-decoration:none;font-size:15px;font-weight:500;white-space:nowrap;transition:background .2s,color .2s}
nav a i{font-style:normal;font-size:16px}
nav a:hover{background:var(--fill)}nav a.on{background:var(--acc);color:#fff}
main{max-width:960px;margin:0 auto;padding:8px 16px calc(40px + var(--sab))}
h1{font-size:34px;line-height:1.15;font-weight:700;letter-spacing:-.02em;margin:18px 4px 18px}
h2{font-size:13px;font-weight:400;color:var(--sub);text-transform:uppercase;letter-spacing:.02em;margin:28px 16px 8px}
p{margin:.5rem 4px}code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--fill);
padding:2px 6px;border-radius:6px}
a{color:var(--acc);text-decoration:none}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.card{background:var(--card);border-radius:var(--r);padding:14px 16px;min-width:0}
.card b{display:block;font-size:22px;font-weight:600;letter-spacing:-.01em;overflow-wrap:anywhere}
.card span{color:var(--sub);font-size:13px}
.wrap{overflow-x:auto;background:var(--card);border-radius:var(--r);-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:15px}
th,td{padding:12px 16px;text-align:left;border-bottom:.5px solid var(--line);vertical-align:middle}
th{font-size:13px;font-weight:500;color:var(--sub);white-space:nowrap}
tr:last-child td{border-bottom:0}
input,select,button{font:inherit;font-size:16px;border-radius:10px;border:0;padding:9px 14px;outline:0}
input,select{background:var(--fill);color:inherit;min-width:0}
input:focus,select:focus{box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 35%,transparent)}
input[type=checkbox]{width:22px;height:22px;accent-color:var(--acc);vertical-align:middle;margin-right:6px}
button{background:var(--acc);color:#fff;font-weight:600;cursor:pointer;transition:opacity .15s,transform .1s;white-space:nowrap}
button:hover{opacity:.9}button:active{opacity:.7;transform:scale(.97)}
button.bad{background:color-mix(in srgb,var(--bad) 14%,transparent);color:var(--bad)}
button.ghost{background:var(--fill);color:var(--acc)}
form.inline{display:inline}
form.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:var(--card);
border-radius:var(--r);padding:12px 16px;margin:0 0 8px}
.flash{background:var(--ok);color:#fff;padding:12px 16px;border-radius:var(--r);margin:12px 0 0;font-weight:500}
.err{background:var(--bad)}
pre{background:var(--card);border-radius:var(--r);padding:14px 16px;overflow:auto;font:12.5px/1.5 ui-monospace,Menlo,monospace;
max-height:70vh;margin:8px 0}
details{background:var(--card);border-radius:var(--r);padding:12px 16px}summary{cursor:pointer;color:var(--acc)}
.muted{color:var(--sub)}
.login{max-width:360px;margin:14vh auto 0;padding:16px;text-align:center}
.login h1{font-size:28px;margin-bottom:24px}
.login form.row{flex-direction:column;align-items:stretch;padding:16px}
.login input,.login button{width:100%;padding:12px 14px}
@media(max-width:640px){
header strong{display:none}
header{padding:8px 12px}
nav{position:fixed;left:0;right:0;bottom:0;z-index:20;justify-content:space-around;gap:0;
padding:6px 4px calc(6px + var(--sab));background:var(--glass);
-webkit-backdrop-filter:saturate(180%) blur(22px);backdrop-filter:saturate(180%) blur(22px);
border-top:.5px solid var(--line)}
nav a{flex-direction:column;gap:2px;padding:4px 6px;border-radius:10px;font-size:10px;background:none!important;
color:var(--sub)}
nav a i{font-size:22px}nav a.on{color:var(--acc)}
header{justify-content:flex-end}
main{padding-bottom:calc(90px + var(--sab))}
h1{font-size:30px}
th,td{padding:10px 12px}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

NAV = [
    ("/", "Tổng quan"),
    ("/autochat", "Auto-Chat"),
    ("/reminders", "Reminder"),
    ("/history", "Lịch sử"),
    ("/logs", "Log"),
    ("/settings", "Cấu hình"),
]

ICONS = {
    "/": "📊",
    "/autochat": "💬",
    "/reminders": "⏰",
    "/history": "🗂️",
    "/logs": "📜",
    "/settings": "⚙️",
}


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _doc(title: str, inner: str) -> str:
    return (
        '<!doctype html><html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="theme-color" content="#f2f2f7" media="(prefers-color-scheme: light)">'
        '<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">'
        f"<title>{esc(title)} · Gemini Dashboard</title><style>{CSS}</style></head>"
        f"<body>{inner}</body></html>"
    )


def layout(*, title: str, body: str, csrf: str, active: str, msg: str = "") -> str:
    nav = "".join(
        f'<a href="{h}"{" class=on" if h == active else ""}><i>{ICONS.get(h, "•")}</i>{esc(label)}</a>'
        for h, label in NAV
    )
    flash = f'<div class="flash">{esc(msg)}</div>' if msg else ""
    inner = (
        f"<header><strong>🤖 Gemini</strong><nav>{nav}</nav>"
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
        'required autofocus><button>Đăng nhập</button></form></div>'
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
