"""Giao diện + logic thuần của dashboard (không phụ thuộc aiohttp/discord → dễ test).

Giao diện: Kính mờ (frosted glass) thuần CSS, thanh menu dọc bên trái, tối ưu điện thoại.
Không dùng JavaScript và không tải tài nguyên bên ngoài → không mở thêm bề mặt tấn công.
"""

from __future__ import annotations

import html
import secrets
import time

from utils import format_bytes, format_uptime

CSS = """
:root{color-scheme:dark;--bg:#0a0e1c;--fg:#f3f5fa;--mut:rgba(243,245,250,.62);
--g1:rgba(255,255,255,.22);--g2:rgba(255,255,255,.08);--line:rgba(255,255,255,.25);--hi:rgba(255,255,255,.45);
--acc:#7b8cff;--acc2:#b06bff;--bad:#ff5a64;--ok:#2fd3a0;--sh:0 10px 34px rgba(0,0,0,.38);--side:252px;
--blur:44px;--sat:200%}
@media(prefers-color-scheme:light){:root{color-scheme:light;--bg:#e8ecf8;--fg:#141824;--mut:rgba(20,24,36,.6);
--g1:rgba(255,255,255,.78);--g2:rgba(255,255,255,.46);--line:rgba(255,255,255,.88);--hi:#fff;--sh:0 10px 34px rgba(50,60,110,.16)}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{scroll-padding-top:5rem}
body{margin:0;min-height:100vh;min-height:100dvh;color:var(--fg);overflow-x:hidden;white-space:nowrap;
font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,system-ui,sans-serif;-webkit-font-smoothing:antialiased;
background-color:var(--bg);
background-image:radial-gradient(55vmax 55vmax at 8% -5%,rgba(91,107,255,.55),transparent 62%),
radial-gradient(48vmax 48vmax at 105% 18%,rgba(255,106,213,.42),transparent 62%),
radial-gradient(60vmax 60vmax at 35% 112%,rgba(34,211,238,.38),transparent 62%);
background-attachment:fixed}
@media(prefers-color-scheme:light){
body{background-image:radial-gradient(55vmax 55vmax at 8% -5%,rgba(91,107,255,.35),transparent 62%),
radial-gradient(48vmax 48vmax at 105% 18%,rgba(255,106,213,.25),transparent 62%),
radial-gradient(60vmax 60vmax at 35% 112%,rgba(34,211,238,.20),transparent 62%)}}
a{color:inherit}code{font:.88em ui-monospace,SFMono-Regular,Menlo,monospace}

.glass,.card,.wrap,pre,.flash,.side,.top,details{background:linear-gradient(135deg,var(--g1),var(--g2));
-webkit-backdrop-filter:blur(var(--blur)) saturate(var(--sat));backdrop-filter:blur(var(--blur)) saturate(var(--sat));
border:1px solid var(--line);box-shadow:var(--sh),inset 0 1px 0 var(--hi),inset 0 -1px 0 rgba(255,255,255,.06);
transform:translateZ(0);will-change:transform}

#nt{position:absolute;opacity:0;pointer-events:none}
.side{position:fixed;top:0;bottom:0;left:0;width:var(--side);z-index:40;display:flex;flex-direction:column;
padding:max(18px,env(safe-area-inset-top)) 12px max(18px,env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-left));
border-radius:0 28px 28px 0;overflow-y:auto;transition:transform .32s cubic-bezier(.32,.72,0,1)}
.brand{display:flex;align-items:center;gap:12px;padding:6px 10px 20px;font-weight:700;font-size:1.05rem}
.logo{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;font-size:1.2rem;flex:none;
background:linear-gradient(135deg,var(--acc),var(--acc2));box-shadow:inset 0 1px 0 rgba(255,255,255,.5),0 6px 16px rgba(123,140,255,.45)}
.side nav{display:flex;flex-direction:column;gap:4px}
.side nav a{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:16px;text-decoration:none;
color:var(--mut);font-weight:500;transition:background .2s,color .2s}
.side nav a:hover{background:rgba(255,255,255,.1);color:var(--fg)}
.side nav a.on{color:var(--fg);background:linear-gradient(135deg,rgba(123,140,255,.55),rgba(176,107,255,.38));
box-shadow:inset 0 1px 0 rgba(255,255,255,.45),0 6px 18px rgba(123,140,255,.3)}
.side svg{width:20px;height:20px;flex:none;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.side form.out{margin-top:auto;padding-top:16px}.side form.out button{width:100%}

.top{display:none;position:fixed;z-index:30;left:max(10px,env(safe-area-inset-left));right:max(10px,env(safe-area-inset-right));
top:max(10px,env(safe-area-inset-top));height:52px;border-radius:26px;align-items:center;gap:12px;padding:0 8px}
.burger{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;cursor:pointer;flex:none;background:rgba(255,255,255,.12)}
.burger i,.burger i::before,.burger i::after{display:block;width:16px;height:2px;border-radius:2px;background:currentColor;position:relative;content:""}
.burger i::before{position:absolute;top:-5px}.burger i::after{position:absolute;top:5px}
.top b{overflow:hidden;text-overflow:ellipsis;font-size:1rem}
.scrim{display:none}

main{margin-left:var(--side);padding:max(28px,env(safe-area-inset-top)) 28px 40px;min-width:0}
main>*{max-width:1120px}
h1{font-size:1.7rem;letter-spacing:-.02em;margin:.1rem 0 1.2rem;overflow:hidden;text-overflow:ellipsis}
h2{font-size:1.05rem;margin:1.8rem 0 .7rem;color:var(--mut);font-weight:600}
main p{overflow-x:auto;scrollbar-width:none}main p::-webkit-scrollbar{display:none}

.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px}
.card{border-radius:22px;padding:14px 16px;min-width:0}
.card b{display:block;font-size:1.2rem;font-weight:650;overflow:hidden;text-overflow:ellipsis}
.card span{display:block;color:var(--mut);font-size:.84rem;overflow:hidden;text-overflow:ellipsis}

.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:22px}
table{border-collapse:collapse;width:100%}
th,td{padding:.7rem 1rem;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}
th{font-size:.8rem;color:var(--mut);font-weight:600}tr:last-child td{border-bottom:0}
tr:hover td{background:rgba(255,255,255,.05)}

input,select,button{font:inherit;font-size:16px;padding:.6rem .95rem;border-radius:999px;border:1px solid var(--line);
background:var(--g2);color:inherit;outline:0;-webkit-backdrop-filter:blur(20px) saturate(180%);backdrop-filter:blur(20px) saturate(180%)}
input::placeholder{color:var(--mut)}
input:focus-visible,select:focus-visible,button:focus-visible,a:focus-visible,.burger:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
input[type=checkbox]{width:1.1rem;height:1.1rem;padding:0;vertical-align:middle;accent-color:var(--acc)}
button{border:0;cursor:pointer;color:#fff;font-weight:600;background:linear-gradient(135deg,var(--acc),var(--acc2));
box-shadow:inset 0 1px 0 rgba(255,255,255,.45),0 6px 16px rgba(123,140,255,.35);transition:transform .15s,filter .2s}
button:active{transform:scale(.96)}button:hover{filter:brightness(1.08)}
button.bad{background:linear-gradient(135deg,#ff6b73,#e8343f);box-shadow:inset 0 1px 0 rgba(255,255,255,.4),0 6px 16px rgba(255,90,100,.35)}
button.ghost{background:var(--g2);color:inherit;box-shadow:inset 0 1px 0 var(--hi)}
form.inline{display:inline}form.row{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;margin:.5rem 0}
td form.inline button{padding:.35rem .85rem;font-size:14px}

.flash{border-radius:18px;padding:.75rem 1.1rem;margin-bottom:1.1rem;border-left:4px solid var(--ok);overflow-x:auto}
.err{border-left-color:var(--bad)}
pre{border-radius:22px;padding:1rem 1.2rem;overflow:auto;font-size:.8rem;max-height:70vh;white-space:pre;margin:.5rem 0}
details{border-radius:22px;padding:.8rem 1.1rem}summary{cursor:pointer;font-weight:600}
details pre{background:none;border:0;box-shadow:none;-webkit-backdrop-filter:none;backdrop-filter:none;padding:.8rem 0 0}
.muted{color:var(--mut)}

.login{max-width:380px;margin:14vh auto 0;padding:1.6rem;border-radius:30px;
background:linear-gradient(135deg,var(--g1),var(--g2));-webkit-backdrop-filter:blur(48px) saturate(200%);backdrop-filter:blur(48px) saturate(200%);
border:1px solid var(--line);box-shadow:var(--sh),inset 0 1px 0 var(--hi)}
.login h1{display:flex;align-items:center;gap:12px;font-size:1.35rem}
.login form.row{flex-wrap:nowrap}.login input{flex:1;min-width:0}
.wrapper{padding:0 16px}

@media(max-width:880px){
:root{--side:min(80vw,300px);--blur:32px}
.top{display:flex}
.side{transform:translateX(-105%);width:var(--side)}
#nt:checked~.side{transform:none}
#nt:checked~.scrim{display:block;position:fixed;inset:0;z-index:35;background:rgba(0,0,0,.4);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}
main{margin-left:0;padding:calc(76px + env(safe-area-inset-top)) max(14px,env(safe-area-inset-right)) 32px max(14px,env(safe-area-inset-left))}
h1{font-size:1.4rem}
.cards{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.card{padding:12px 14px}.card b{font-size:1.05rem}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){
.glass,.card,.wrap,pre,.flash,.side,.top,details,.login{background:rgba(30,34,52,.96)}}
"""

NAV = [
    ("/", "Tổng quan"),
    ("/autochat", "Auto-Chat"),
    ("/reminders", "Reminder"),
    ("/history", "Lịch sử"),
    ("/logs", "Log"),
    ("/settings", "Cấu hình"),
]

_ICONS = {
    "/": '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/>'
         '<rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    "/autochat": '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
    "/reminders": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "/history": '<path d="M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6'
                'M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    "/logs": '<path d="M5 4h14v16H5zM9 9h6M9 13h6M9 17h3"/>',
    "/settings": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/>'
                 '<circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
}


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _doc(title: str, inner: str) -> str:
    return (
        '<!doctype html><html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="theme-color" content="#0a0e1c"><meta name="color-scheme" content="dark light">'
        f"<title>{esc(title)} · Gemini Dashboard</title><style>{CSS}</style></head>"
        f"<body>{inner}</body></html>"
    )


def layout(*, title: str, body: str, csrf: str, active: str, msg: str = "") -> str:
    nav = "".join(
        f'<a href="{h}"{" class=on" if h == active else ""}>'
        f'<svg viewBox="0 0 24 24" aria-hidden="true">{_ICONS.get(h, "")}</svg>{esc(label)}</a>'
        for h, label in NAV
    )
    flash = f'<div class="flash">{esc(msg)}</div>' if msg else ""
    inner = (
        '<input type="checkbox" id="nt" aria-hidden="true">'
        '<label class="scrim" for="nt"></label>'
        f'<aside class="side"><div class="brand"><span class="logo">🤖</span>Gemini Dashboard</div>'
        f"<nav>{nav}</nav>"
        f'<form class="out" method="post" action="/logout">'
        f'<input type="hidden" name="csrf" value="{esc(csrf)}"><button class="ghost">Đăng xuất</button></form></aside>'
        f'<header class="top"><label class="burger" for="nt" tabindex="0" aria-label="Mở menu"><i></i></label>'
        f"<b>{esc(title)}</b></header>"
        f"<main>{flash}<h1>{esc(title)}</h1>{body}</main>"
    )
    return _doc(title, inner)


def login_page(error: str = "") -> str:
    err = f'<div class="flash err">{esc(error)}</div>' if error else ""
    inner = (
        '<div class="wrapper"><div class="login"><h1><span class="logo">🤖</span>Gemini Dashboard</h1>' + err +
        '<form method="post" action="/login" class="row">'
        '<input type="password" name="password" placeholder="Mật khẩu" autocomplete="current-password" '
        'required autofocus><button>Đăng nhập</button></form></div></div>'
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
