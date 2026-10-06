"""Cấu hình bot — đọc từ biến môi trường / file .env."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _opt_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int_set(name: str) -> set[int]:
    return {
        int(x.strip())
        for x in os.getenv(name, "").split(",")
        if x.strip().isdigit()
    }


def _str_set(name: str) -> set[str]:
    return {x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip()}


def _load_prompt() -> str:
    env_prompt = os.getenv("SYSTEM_PROMPT")
    if env_prompt:
        return env_prompt
    path = BASE_DIR / "prompt.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return "Bạn là một người bạn thân trong server Discord. Trả lời ngắn gọn, tự nhiên."


# --- Bắt buộc ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Gemini ---
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
SYSTEM_PROMPT = _load_prompt()
PRIVILEGED_NOTE = os.getenv(
    "PRIVILEGED_NOTE",
    "Lưu ý: người đang nhắn tin với bạn là Owner hoặc Admin của server này. "
    "Vẫn giữ giọng vui vẻ, lầy lội như bình thường, nhưng bớt cà khịa xược hơn, "
    "tôn trọng hơn một chút, không công kích hay nói hỗn.",
)
MAX_OUTPUT_TOKENS = _int("MAX_OUTPUT_TOKENS", 1024)
# Để trống = không gửi tham số thinking (an toàn cho mọi model).
THINKING_BUDGET = _opt_int("THINKING_BUDGET")
GEMINI_TIMEOUT = _int("GEMINI_TIMEOUT", 60)
GEMINI_CONCURRENCY = max(1, _int("GEMINI_CONCURRENCY", 4))

# --- Hội thoại ---
MAX_HISTORY_TURNS = _int("MAX_HISTORY_TURNS", 10)
HISTORY_RETENTION_DAYS = _int("HISTORY_RETENTION_DAYS", 30)  # 0 = không tự xóa
MAX_REPLY_CHARS = 1900

# --- Ảnh ---
MAX_IMAGES = _int("MAX_IMAGES", 4)
MAX_IMAGE_BYTES = _int("MAX_IMAGE_MB", 8) * 1024 * 1024
ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}

# --- Discord ---
STATUS_TYPE = os.getenv("STATUS_TYPE", "playing").lower()
STATUS_TEXT = os.getenv("STATUS_TEXT", "Where Winds Meet")
ALLOWED_GUILD_IDS = _int_set("ALLOWED_GUILD_IDS")
AUTO_CHAT_CHANNEL_IDS = _int_set("AUTO_CHAT_CHANNEL_IDS")
MEMBERS_INTENT = _bool("MEMBERS_INTENT", False)
SYNC_ON_START = _bool("SYNC_ON_START", True)

# --- Quyền admin của bot (ngoài Owner / quyền Administrator) ---
ADMIN_ROLE_IDS = _int_set("ADMIN_ROLE_IDS")
# Tùy chọn, mặc định TẮT vì so khớp theo tên role dễ bị giả mạo.
ADMIN_ROLE_NAMES = _str_set("ADMIN_ROLE_NAMES")

# --- Reminder ---
REMINDER_GRACE_MINUTES = _int("REMINDER_GRACE_MINUTES", 10)
MAX_REMINDERS_PER_USER = _int("MAX_REMINDERS_PER_USER", 20)
MAX_REMINDER_LENGTH = _int("MAX_REMINDER_LENGTH", 1500)

# --- Database ---
DB_PATH = os.getenv("DB_PATH", "conversations.db")
