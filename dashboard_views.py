from pathlib import Path

_HERE = Path(__file__).resolve().parent
_STATIC_DIR = _HERE / "static"
_TEMPLATE_DIR = _HERE / "templates"

_cache: dict[str, str] = {}


def _load(name: str, path: Path) -> str:
    """Đọc file 1 lần, cache lại. Trả về chuỗi rỗng nếu thiếu."""
    if name not in _cache:
        try:
            _cache[name] = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            _cache[name] = ""
    return _cache[name]


def get_css() -> str:
    """Trả về nội dung dashboard.css (cho route /dashboard.css)."""
    return _load("css", _STATIC_DIR / "dashboard.css")


def _render(tpl_name: str, repl: dict[str, str]) -> str:
    tpl = _load(tpl_name, _TEMPLATE_DIR / tpl_name)
    out = tpl
    for k, v in repl.items():
        out = out.replace(f"__{k}__", v)
    return out


def _doc(title: str, inner: str) -> str:
    """Dùng cho trang login (không có sidebar)."""
    return _render("login.html", {
        "TITLE": esc(title),
        "ERROR": inner,
    })


def layout(*, title: str, body: str, csrf: str, active: str, msg: str = "") -> str:
    nav = "".join(
        f'<a href="{h}"{" class=on" if h == active else ""}>'
        f'<svg viewBox="0 0 24 24" aria-hidden="true">{_ICONS.get(h, "")}</svg>{esc(label)}</a>'
        for h, label in NAV
    )
    flash = f'<div class="flash">{esc(msg)}</div>' if msg else ""
    return _render("dashboard.html", {
        "TITLE": esc(title),
        "NAV":   nav,
        "CSRF":  esc(csrf),
        "FLASH": flash,
        "BODY":  body,
    })


def login_page(error: str = "") -> str:
    err = f'<div class="flash err">{esc(error)}</div>' if error else ""
    return _render("login.html", {
        "TITLE": "Đăng nhập",
        "ERROR": err,
    })
