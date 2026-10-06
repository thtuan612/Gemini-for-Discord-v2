"""SQLite — một connection dùng chung, chạy trong thread (không block event loop)."""
from __future__ import annotations

import asyncio
import logging
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

CREATE TABLE IF NOT EXISTS reminders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER NOT NULL,
    message      TEXT    NOT NULL,
    repeat       TEXT    NOT NULL,            -- 'once' hoặc 'daily'
    hour         INTEGER NOT NULL,            -- giờ VN (0-23)
    minute       INTEGER NOT NULL,            -- phút VN (0-59)
    next_run_utc TEXT    NOT NULL,            -- ISO datetime UTC
    created_by   INTEGER NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1,
    guild_id     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(active, next_run_utc);

CREATE TABLE IF NOT EXISTS auto_chat_channels (
    channel_id INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL,
    added_by   INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ---------- nội bộ ----------
    def _init_sync(self) -> None:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        # Migration: DB cũ chưa có cột guild_id
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(reminders)")}
        if "guild_id" not in cols:
            conn.execute("ALTER TABLE reminders ADD COLUMN guild_id INTEGER NOT NULL DEFAULT 0")
        # Bảng lịch sử cũ (khóa theo user_id, lẫn giữa các server) không còn dùng.
        conn.execute("DROP TABLE IF EXISTS conversations")
        conn.commit()
        self._conn = conn

    def _run_sync(self, sql: str, params: tuple, mode: str):
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database chưa được init()")
            cur = self._conn.execute(sql, params)
            if mode == "one":
                result = cur.fetchone()
            elif mode == "all":
                result = cur.fetchall()
            else:
                result = (cur.rowcount, cur.lastrowid)
            self._conn.commit()
            return result

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

    async def add_auto_chat_channel(self, channel_id: int, guild_id: int, added_by: int) -> bool:
        rowcount, _ = await self._q(
            "INSERT OR IGNORE INTO auto_chat_channels (channel_id, guild_id, added_by) VALUES (?, ?, ?)",
            (channel_id, guild_id, added_by),
        )
        return rowcount > 0

    async def remove_auto_chat_channel(self, channel_id: int) -> bool:
        rowcount, _ = await self._q(
            "DELETE FROM auto_chat_channels WHERE channel_id = ?", (channel_id,)
        )
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
        await self._q(
            "DELETE FROM chat_history WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )

    async def purge_old_history(self, days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rowcount, _ = await self._q("DELETE FROM chat_history WHERE updated_at < ?", (cutoff,))
        return rowcount

    async def count_history(self) -> int:
        row = await self._q("SELECT COUNT(*) FROM chat_history", mode="one")
        return row[0]

    async def delete_all_history(self) -> int:
        rowcount, _ = await self._q("DELETE FROM chat_history")
        return rowcount

    async def list_all_auto_chat(self):
        return await self._q("SELECT channel_id, guild_id FROM auto_chat_channels", mode="all")

    # ---------- reminders ----------
    async def list_all_active_reminders(self):
        return await self._q(
            "SELECT * FROM reminders WHERE active = 1 ORDER BY next_run_utc", mode="all"
        )

    async def add_reminder(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message: str,
        repeat: str,
        hour: int,
        minute: int,
        next_run_iso: str,
        created_by: int,
    ) -> int:
        _, rid = await self._q(
            """
            INSERT INTO reminders
              (channel_id, message, repeat, hour, minute, next_run_utc, created_by, active, guild_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (channel_id, message, repeat, hour, minute, next_run_iso, created_by, guild_id),
        )
        return rid

    async def get_reminder(self, reminder_id: int):
        return await self._q("SELECT * FROM reminders WHERE id = ?", (reminder_id,), "one")

    async def get_due_reminders(self, now_iso: str):
        return await self._q(
            "SELECT * FROM reminders WHERE active = 1 AND next_run_utc <= ? ORDER BY next_run_utc",
            (now_iso,),
            "all",
        )

    async def advance_reminder(self, reminder_id: int, next_run_iso: str) -> None:
        await self._q(
            "UPDATE reminders SET next_run_utc = ? WHERE id = ?", (next_run_iso, reminder_id)
        )

    async def deactivate_reminder(self, reminder_id: int) -> bool:
        rowcount, _ = await self._q(
            "UPDATE reminders SET active = 0 WHERE id = ? AND active = 1", (reminder_id,)
        )
        return rowcount > 0

    async def list_reminders(self, guild_id: int):
        return await self._q(
            "SELECT * FROM reminders WHERE active = 1 AND guild_id = ? ORDER BY next_run_utc",
            (guild_id,),
            "all",
        )

    async def count_active_reminders(self, user_id: int, guild_id: int) -> int:
        row = await self._q(
            "SELECT COUNT(*) FROM reminders WHERE active = 1 AND created_by = ? AND guild_id = ?",
            (user_id, guild_id),
            "one",
        )
        return row[0]

    async def count_active_reminders_total(self) -> int:
        row = await self._q("SELECT COUNT(*) FROM reminders WHERE active = 1", mode="one")
        return row[0]

    async def reminders_missing_guild(self):
        return await self._q(
            "SELECT id, channel_id FROM reminders WHERE active = 1 AND guild_id = 0", mode="all"
        )

    async def set_reminder_guild(self, reminder_id: int, guild_id: int) -> None:
        await self._q("UPDATE reminders SET guild_id = ? WHERE id = ?", (guild_id, reminder_id))
