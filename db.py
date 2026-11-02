"""SQLite — một connection dùng chung, chạy trong thread (không block event loop)."""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

log = logging.getLogger("discord-ai-bot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_history (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    history    TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_chat_history_updated ON chat_history(updated_at);

CREATE TABLE IF NOT EXISTS auto_chat_channels (
    channel_id INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL,
    added_by   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS allowed_guilds (
    guild_id   INTEGER PRIMARY KEY,
    added_by   INTEGER NOT NULL,
    added_at   TEXT    NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ---------- nội bộ ----------
    def _init_sync(self) -> None:
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)
        # WAL/SHM có thể chứa nội dung hội thoại. Dùng umask riêng lúc tạo
        # database để các file phụ cũng không bị mở quyền theo umask hệ thống.
        previous_umask = os.umask(0o077) if os.name == "posix" else None
        try:
            conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        finally:
            if previous_umask is not None:
                os.umask(previous_umask)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA secure_delete=ON")
        conn.execute("PRAGMA wal_autocheckpoint=1000")
        conn.execute("PRAGMA journal_size_limit=16777216")
        conn.executescript(SCHEMA)
        if self.path != ":memory:" and os.path.isfile(self.path):
            try:
                os.chmod(self.path, 0o600)
            except OSError as e:
                log.warning("Không thể giới hạn quyền truy cập file DB (%s)", type(e).__name__)
        # Dọn bảng Reminder cũ nếu DB được nâng cấp từ phiên bản trước.
        # Các bảng dữ liệu khác được giữ nguyên.
        conn.execute("DROP TABLE IF EXISTS reminders")
        # Bảng lịch sử cũ (khóa theo user_id, lẫn giữa các server) không còn dùng.
        conn.execute("DROP TABLE IF EXISTS conversations")
        conn.commit()
        self._conn = conn

    def _run_sync(self, sql: str, params: tuple, mode: str):
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database chưa được init()")
            try:
                cur = self._conn.execute(sql, params)
                if mode == "one":
                    result = cur.fetchone()
                elif mode == "all":
                    result = cur.fetchall()
                else:
                    result = (cur.rowcount, cur.lastrowid)
                    self._conn.commit()
                return result
            except Exception:
                self._conn.rollback()
                raise

    async def _q(self, sql: str, params: tuple = (), mode: str = "exec"):
        return await asyncio.to_thread(self._run_sync, sql, params, mode)

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)
        log.info("Database sẵn sàng tại %s", self.path)

    async def close(self) -> None:
        def _close():
            with self._lock:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None

        await asyncio.to_thread(_close)

    # ---------- auto-chat ----------
    async def load_auto_chat_channels(self) -> list[int]:
        rows = await self._q("SELECT channel_id FROM auto_chat_channels", mode="all")
        return [r[0] for r in rows]

    async def _checkpoint(self) -> None:
        """Đẩy WAL vào DB chính và thu gọn WAL sau các thao tác xóa/cập nhật cấu hình."""
        result = await self._q("PRAGMA wal_checkpoint(TRUNCATE)", mode="one")
        if result and result[0]:
            log.warning("WAL checkpoint đang bận; SQLite sẽ hoàn tất ở lần checkpoint sau")

    async def add_auto_chat_channel(self, channel_id: int, guild_id: int, added_by: int) -> bool:
        rowcount, _ = await self._q(
            "INSERT OR IGNORE INTO auto_chat_channels (channel_id, guild_id, added_by) VALUES (?, ?, ?)",
            (channel_id, guild_id, added_by),
        )
        await self._checkpoint()
        return rowcount > 0

    async def remove_auto_chat_channel(self, channel_id: int) -> bool:
        rowcount, _ = await self._q(
            "DELETE FROM auto_chat_channels WHERE channel_id = ?", (channel_id,)
        )
        await self._checkpoint()
        return rowcount > 0

    async def list_auto_chat_channels(self, guild_id: int) -> list[int]:
        rows = await self._q(
            "SELECT channel_id FROM auto_chat_channels WHERE guild_id = ?", (guild_id,), "all"
        )
        return [r[0] for r in rows]

    # ---------- lịch sử hội thoại ----------
    async def load_history_raw(self, guild_id: int, user_id: int) -> str | None:
        row = await self._q(
            "SELECT history FROM chat_history WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
            "one",
        )
        return row[0] if row else None

    async def save_history_raw(self, guild_id: int, user_id: int, raw: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._q(
            """
            INSERT INTO chat_history (guild_id, user_id, history, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE
              SET history = excluded.history, updated_at = excluded.updated_at
            """,
            (guild_id, user_id, raw, now),
        )

    async def delete_history(self, guild_id: int, user_id: int) -> None:
        rowcount, _ = await self._q(
            "DELETE FROM chat_history WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        if rowcount:
            await self._checkpoint()

    async def purge_old_history(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rowcount, _ = await self._q("DELETE FROM chat_history WHERE updated_at < ?", (cutoff,))
        if rowcount:
            await self._checkpoint()
        return rowcount

    async def count_history(self) -> int:
        row = await self._q("SELECT COUNT(*) FROM chat_history", mode="one")
        return row[0]

    async def delete_all_history(self) -> int:
        rowcount, _ = await self._q("DELETE FROM chat_history")
        if rowcount:
            await self._checkpoint()
        return rowcount

    async def list_all_auto_chat(self):
        return await self._q("SELECT channel_id, guild_id FROM auto_chat_channels", mode="all")

    # ---------- allowed guilds ----------
    async def load_allowed_guilds(self) -> list[int]:
        rows = await self._q("SELECT guild_id FROM allowed_guilds", mode="all")
        return [r[0] for r in rows]

    async def add_allowed_guild(self, guild_id: int, added_by: int) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        rowcount, _ = await self._q(
            "INSERT OR IGNORE INTO allowed_guilds (guild_id, added_by, added_at) VALUES (?, ?, ?)",
            (guild_id, added_by, now),
        )
        return rowcount > 0

    async def remove_allowed_guild(self, guild_id: int) -> bool:
        rowcount, _ = await self._q(
            "DELETE FROM allowed_guilds WHERE guild_id = ?", (guild_id,)
        )
        return rowcount > 0

    async def clear_allowed_guilds(self) -> int:
        rowcount, _ = await self._q("DELETE FROM allowed_guilds")
        return rowcount

    async def list_allowed_guilds_details(self):
        return await self._q(
            "SELECT guild_id, added_by, added_at FROM allowed_guilds ORDER BY added_at DESC",
            mode="all",
        )
