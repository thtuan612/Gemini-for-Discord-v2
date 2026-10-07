"""Hàm tiện ích thuần (không phụ thuộc discord) — dễ test."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import psutil

from config import VN_TZ


def next_run_utc(hour: int, minute: int, after: datetime | None = None) -> datetime:
    """Thời điểm UTC kế tiếp khớp giờ:phút VN, sau mốc `after` (mặc định: bây giờ)."""
    now_vn = (after or datetime.now(timezone.utc)).astimezone(VN_TZ)
    candidate = now_vn.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_vn:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        h, m = value.strip().split(":")
        hour, minute = int(h), int(m)
    except ValueError:
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def split_message(text: str, limit: int = 1900) -> list[str]:
    """Chia tin nhắn dài thành nhiều đoạn <= limit ký tự (ưu tiên cắt ở xuống dòng/khoảng trắng)."""
    chunks: list[str] = []
    text = text.strip()
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:  # <= 0: tránh vòng lặp vô hạn khi text bắt đầu bằng "\n"
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        piece = text[:cut].rstrip()
        if piece:
            chunks.append(piece)
        text = text[cut:].lstrip()
    return chunks or ["…"]


def get_dir_size(path: str) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for fname in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fname))
            except OSError:
                pass
    return total


def format_bytes(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


def format_uptime(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
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
    """Giới hạn RAM thật của container (cgroup); nếu không có thì trả về RAM host."""
    host_total = psutil.virtual_memory().total
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path) as f:
                val = f.read().strip()
            if val != "max" and int(val) < host_total:
                return int(val)
        except (FileNotFoundError, ValueError, PermissionError):
            continue
    return host_total


_URL_RE = re.compile(r"https?://\S+")
_DISCORD_TOKEN_RE = re.compile(r"<(?:a?:\w+:|[@#&!]{1,2})\d+>")


def is_trivial_message(text: str) -> bool:
    """True nếu tin nhắn không có chữ/số nào (chỉ emoji, link, sticker, ký tự lạ...).

    Dùng để Auto-Chat bỏ qua mà không tốn một request Gemini.
    """
    cleaned = _DISCORD_TOKEN_RE.sub("", _URL_RE.sub("", text or ""))
    return not any(ch.isalnum() for ch in cleaned)
