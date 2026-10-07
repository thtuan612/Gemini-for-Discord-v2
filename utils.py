"""Các hàm tiện ích dùng chung cho bot."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import psutil

from config import VN_TZ


def next_run_utc(
    hour: int,
    minute: int,
    after: datetime | None = None,
) -> datetime:
    """Thời điểm UTC kế tiếp khớp giờ:phút VN."""
    now_vn = (after or datetime.now(timezone.utc)).astimezone(VN_TZ)

    candidate = now_vn.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    if candidate <= now_vn:
        candidate += timedelta(days=1)

    return candidate.astimezone(timezone.utc)


def parse_hhmm(value: str) -> tuple[int, int] | None:
    """Chuyển HH:MM thành (hour, minute)."""
    try:
        h, m = value.strip().split(":")
        hour = int(h)
        minute = int(m)
    except (ValueError, AttributeError):
        return None

    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute

    return None


def split_message(text: str, limit: int = 1900) -> list[str]:
    """Chia tin nhắn dài thành nhiều đoạn <= limit ký tự."""
    chunks: list[str] = []
    text = text.strip()

    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        cut = text.rfind("\n", 0, limit)

        if cut <= 0:
            cut = text.rfind(" ", 0, limit)

        if cut <= 0:
            cut = limit

        piece = text[:cut].rstrip()

        if piece:
            chunks.append(piece)

        text = text[cut:].lstrip()

    return chunks or ["…"]


def get_dir_size(path: str) -> int:
    """Tính tổng dung lượng của thư mục."""
    total = 0

    for dirpath, _, filenames in os.walk(path):
        for fname in filenames:
            try:
                total += os.path.getsize(
                    os.path.join(dirpath, fname)
                )
            except OSError:
                pass

    return total


def format_bytes(num_bytes: float) -> str:
    """Định dạng byte thành B/KB/MB/GB/TB/PB."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"

        num_bytes /= 1024

    return f"{num_bytes:.1f} PB"


def format_uptime(delta: timedelta) -> str:
    """Định dạng thời gian hoạt động."""
    total_seconds = int(delta.total_seconds())

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []

    if days:
        parts.append(f"{days} ngày")

    if hours:
        parts.append(f"{hours} giờ")

    if minutes:
        parts.append(f"{minutes} phút")

    if not parts:
        parts.append(f"{seconds} giây")

    return " ".join(parts)


def get_memory_limit_bytes() -> int:
    """Lấy giới hạn RAM thật của container."""
    host_total = psutil.virtual_memory().total

    paths = (
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    )

    for path in paths:
        try:
            with open(path) as f:
                value = f.read().strip()

            if value == "max":
                continue

            limit = int(value)

            if limit > 0 and limit < host_total:
                return limit

        except (
            FileNotFoundError,
            ValueError,
            PermissionError,
            OSError,
        ):
            continue

    return host_total


def is_trivial_message(text: str) -> bool:
    """Kiểm tra tin nhắn có quá đơn giản để bot xử lý hay không.

    Các tin nhắn như:
        "hi"
        "ok"
        "gg"
        "lol"
        "👍"
        "😂😂"
        "..."
    
    có thể được coi là trivial để tránh gọi Gemini
    khi bot đang ở chế độ auto-chat.
    """
    if not text:
        return True

    text = text.strip()

    if not text:
        return True

    # Tin nhắn chỉ là URL.
    if re.fullmatch(r"https?://\S+", text, re.IGNORECASE):
        return True

    # Các ký tự vô nghĩa / dấu câu.
    punctuation_only = re.sub(
        r"[\s\W_]+",
        "",
        text,
        flags=re.UNICODE,
    )

    if not punctuation_only:
        return True

    # Emoji Unicode.
    without_emoji = re.sub(
        r"[\U0001F1E6-\U0001F1FF"
        r"\U0001F300-\U0001FAFF"
        r"\U00002600-\U000027BF"
        r"\U0001F900-\U0001F9FF"
        r"\U0000200D"
        r"\U0000FE0F]+",
        "",
        text,
    ).strip()

    if not without_emoji:
        return True

    # Một số câu trả lời quá ngắn thường không cần AI.
    trivial_words = {
        "ok",
        "okay",
        "oke",
        "được",
        "ừ",
        "uh",
        "ừm",
        "hmm",
        "huh",
        "hi",
        "hello",
        "hey",
        "yo",
        "gg",
        "lol",
        "lmao",
        "thanks",
        "thank",
        "thx",
        "ty",
        "cảm ơn",
        "cam on",
        "nice",
        "good",
        "cool",
    }

    normalized = re.sub(
        r"\s+",
        " ",
        text.lower(),
    ).strip()

    if normalized in trivial_words:
        return True

    # Chỉ gồm vài ký tự, không đủ ý nghĩa.
    if len(without_emoji) <= 2:
        return True

    return False
