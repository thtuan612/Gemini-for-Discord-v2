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
:root{--bg:#f2f2f7;--fg:#000;--card:rgba(255,255,255,.74);--line:rgba(60,60,67,.16);--fill:rgba(118,118,128,.12);
--fill2:rgba(0,122,255,.14);--sub:rgba(60,60,67,.62);--acc:#007aff;--bad:#ff3b30;--ok:#34c759;
--glass:rgba(250,250,252,.62);--glassline:rgba(255,255,255,.65);--shadow:0 8px 30px rgba(0,0,0,.12);
--bgimg:radial-gradient(60% 38% at 12% 0%,rgba(0,122,255,.26),transparent),
radial-gradient(50% 34% at 100% 18%,rgba(175,82,222,.20),transparent),
radial-gradient(70% 40% at 55% 100%,rgba(52,199,89,.16),transparent);
--sat:env(safe-area-inset-top,0px);--sab:env(safe-area-inset-bottom,0px)}
@media(prefers-color-scheme:dark){:root{--bg:#000;--fg:#fff;--card:rgba(44,44,46,.66);--line:rgba(84,84,88,.5);
--fill:rgba(118,118,128,.28);--fill2:rgba(10,132,255,.28);--sub:rgba(235,235,245,.6);--acc:#0a84ff;--bad:#ff453a;
--ok:#30d158;--glass:rgba(40,40,44,.55);--glassline:rgba(255,255,255,.14);--shadow:0 8px 30px rgba(0,0,0,.5);
--bgimg:radial-gradient(60% 38% at 12% 0%,rgba(10,132,255,.38),transparent),
radial-gradient(50% 34% at 100% 18%,rgba(191,90,242,.30),transparent),
radial-gradient(70% 40% at 55% 100%,rgba(48,209,88,.20),transparent)}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-text-size-adjust:100%;background:var(--bg)}
body{margin:0;background:transparent;color:var(--fg);min-height:100vh;
font:17px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","Segoe UI",Roboto,"Helvetica Neue",sans-serif;
-webkit-font-smoothing:antialiased}
.bg{position:fixed;inset:0;z-index:-1;background:var(--bgimg),var(--bg)}
.page{max-width:980px;margin:0 auto;padding:calc(10px + var(--sat)) 16px calc(130px + var(--sab))}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:44px}
.brand{font-weight:600;font-size:17px;display:flex;align-items:center;gap:8px;white-space:nowrap}
.dot{width:9px;height:9px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 4px color-mix(in srgb,var(--ok) 25%,transparent)}
h1{font-size:34px;line-height:1.12;font-weight:700;letter-spacing:-.025em;margin:14px 2px 16px}
h2{font-size:13px;font-weight:500;color:var(--sub);text-transform:uppercase;letter-spacing:.03em;margin:28px 14px 8px}
p{margin:.5rem 2px}a{color:var(--acc);text-decoration:none}
code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--fill);padding:2px 6px;border-radius:6px;overflow-wrap:anywhere}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card,.wrap,form.row,details,pre{background:var(--card);border:.5px solid var(--glassline);border-radius:22px;
-webkit-backdrop-filter:blur(18px) saturate(160%);backdrop-filter:blur(18px) saturate(160%)}
.card{padding:14px 16px;min-width:0}
.card b{display:block;font-size:22px;font-weight:600;letter-spacing:-.015em;line-height:1.2;overflow-wrap:break-word;text-wrap:balance}
.card span{display:block;margin-top:2px;color:var(--sub);font-size:13px}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:15px}
th,td{padding:12px 16px;text-align:left;border-bottom:.5px solid var(--line);vertical-align:middle}
th{font-size:12.5px;font-weight:500;color:var(--sub);white-space:nowrap}
tr:last-child td{border-bottom:0}
td{overflow-wrap:anywhere}
input,select,button{font:inherit;font-size:16px;border-radius:12px;border:0;padding:10px 14px;outline:0;min-height:42px}
input,select{background:var(--fill);color:inherit;min-width:0;max-width:100%}
input:focus,select:focus{box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 40%,transparent)}
input[type=checkbox]{width:24px;height:24px;min-height:0;accent-color:var(--acc);vertical-align:middle;margin-right:8px}
button{background:var(--acc);color:#fff;font-weight:600;cursor:pointer;transition:opacity .15s,transform .12s;white-space:nowrap;border-radius:999px;padding:10px 20px}
button:hover{opacity:.9}button:active{opacity:.65;transform:scale(.96)}
button.bad{background:color-mix(in srgb,var(--bad) 16%,transparent);color:var(--bad)}
button.ghost{background:var(--fill);color:var(--acc);padding:8px 16px;min-height:36px;font-size:15px}
form.inline{display:inline}
form.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:12px 14px;margin:0 0 10px}
label{overflow-wrap:anywhere}
.flash{background:var(--ok);color:#fff;padding:12px 16px;border-radius:18px;margin:10px 0 0;font-weight:500;
box-shadow:var(--shadow)}.err{background:var(--bad)}
pre{padding:14px 16px;overflow:auto;font:12px/1.55 ui-monospace,Menlo,monospace;max-height:70vh;margin:8px 0;
white-space:pre-wrap;overflow-wrap:anywhere}
details{padding:12px 16px}summary{cursor:pointer;color:var(--acc);font-weight:500}
.muted{color:var(--sub)}
.login{max-width:380px;margin:16vh auto 0;padding:16px;text-align:center}
.login h1{font-size:28px;margin-bottom:22px;text-align:center}
.login form.row{flex-direction:column;align-items:stretch;padding:16px;gap:12px}
.login input,.login button{width:100%;padding:13px 16px}
#lg-root{position:fixed;inset:0;z-index:30;pointer-events:none;overflow:visible}
.lg-bg{position:absolute;inset:0;background:var(--bgimg),var(--bg)}
.glass{position:absolute;pointer-events:auto;left:0;right:0;margin:0 auto;width:max-content;max-width:calc(100% - 24px);
display:flex;gap:2px;padding:6px;border-radius:32px;background:var(--glass);border:.5px solid var(--glassline);
-webkit-backdrop-filter:blur(26px) saturate(190%);backdrop-filter:blur(26px) saturate(190%);box-shadow:var(--shadow)}
.lg-on .glass{background:none;border-color:transparent;box-shadow:none;-webkit-backdrop-filter:none;backdrop-filter:none}
.glass a{position:relative;display:flex;align-items:center;gap:8px;padding:9px 16px;border-radius:26px;color:var(--sub);
font-size:15px;font-weight:500;white-space:nowrap;transition:background .25s,color .25s}
.glass a i{font-style:normal;font-size:18px;line-height:1}
.glass a.on{background:var(--fill2);color:var(--acc)}
.glass{top:calc(10px + var(--sat))}
@media(min-width:761px){.page{padding-top:calc(78px + var(--sat));padding-bottom:60px}.top{position:absolute;left:0;right:0;top:calc(18px + var(--sat));padding:0 16px;max-width:980px;margin:0 auto}}
@media(max-width:760px){
.page{padding-left:14px;padding-right:14px}
.glass{top:auto;bottom:calc(10px + var(--sab));left:10px;right:10px;width:auto;max-width:none;justify-content:space-between}
.glass a{flex:1 1 0;min-width:0;flex-direction:column;gap:2px;padding:7px 2px;font-size:10.5px;justify-content:center;border-radius:24px}
.glass a i{font-size:21px}
h1{font-size:31px}
.cards{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.card.wide{grid-column:1/-1}
.card b{font-size:20px}
.wrap{background:none;border:0;border-radius:0;overflow:visible;-webkit-backdrop-filter:none;backdrop-filter:none}
table,tbody,tr,td{display:block;width:100%}
tr.h{display:none}
tr{background:var(--card);border:.5px solid var(--glassline);border-radius:22px;padding:4px 16px;margin:0 0 10px;
-webkit-backdrop-filter:blur(18px) saturate(160%);backdrop-filter:blur(18px) saturate(160%)}
td{display:flex;justify-content:space-between;align-items:baseline;gap:16px;padding:9px 0;text-align:right;
border-bottom:.5px solid var(--line);font-size:15px}
td::before{content:attr(data-label);flex:none;color:var(--sub);font-size:13px;text-align:left}
td[data-label=""]{justify-content:flex-end}td[data-label=""]::before{display:none}
form.row>*{flex:1 1 100%}form.row>input[type=hidden]{display:none}
form.row>button{width:100%}form.row label{display:flex;align-items:center;gap:8px}
form.row label input[type=number]{flex:1;width:auto!important}
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


LG_JS = """<script type="module">
const root=document.getElementById('lg-root');
try{
const gl=document.createElement('canvas');
if(!(gl.getContext('webgl')||gl.getContext('experimental-webgl')))throw 0;
if(matchMedia('(prefers-reduced-motion: reduce)').matches||/[?&]lg=0/.test(location.search))throw 0;
const {LiquidGlass}=await import('https://cdn.jsdelivr.net/npm/@ybouane/liquidglass/dist/index.js');
const inst=await LiquidGlass.init({root,glassElements:[root.querySelector('.glass')]});
root.classList.add('lg-on');
addEventListener('pagehide',()=>inst.destroy());
}catch(e){/* giữ giao diện kính CSS dự phòng */}
</script>"""

LG_CFG = (
    '{"cornerRadius":32,"zRadius":22,"blurAmount":0.3,"refraction":0.55,"chromAberration":0.03,'
    '"edgeHighlight":0.08,"specular":0.25,"shadowOpacity":0.18,"shadowSpread":14,"shadowOffsetY":6}'
)


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
        f'<body><div class="bg"></div>{inner}</body></html>'
    )


def layout(*, title: str, body: str, csrf: str, active: str, msg: str = "") -> str:
    nav = "".join(
        f'<a href="{h}"{" class=on" if h == active else ""}><i>{ICONS.get(h, "•")}</i><span>{esc(label)}</span></a>'
        for h, label in NAV
    )
    flash = f'<div class="flash">{esc(msg)}</div>' if msg else ""
    inner = (
        '<div class="page"><div class="top"><div class="brand"><span class="dot"></span>Gemini</div>'
        f'<form class="inline" method="post" action="/logout">'
        f'<input type="hidden" name="csrf" value="{esc(csrf)}"><button class="ghost">Đăng xuất</button></form></div>'
        f"{flash}<h1>{esc(title)}</h1>{body}</div>"
        f'<div id="lg-root"><div class="lg-bg"></div>'
        f"<nav class=\"glass\" data-config='{LG_CFG}'>{nav}</nav></div>"
        + LG_JS
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
    body = "".join(
        "<tr>" + "".join(
            f'<td data-label="{esc(headers[i] if i < len(headers) else "")}">{c}</td>' for i, c in enumerate(r)
        ) + "</tr>"
        for r in rows
    )
    return f'<div class="wrap"><table><tr class="h">{head}</tr>{body}</table></div>'


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
    html_cards = "".join(
        f'<div class="card{" wide" if len(str(v)) > 12 else ""}"><b>{esc(v)}</b><span>{esc(k)}</span></div>'
        for k, v in cards
    )
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
