"""SQLite — một connection dùng chung, chạy trong thread (không block event loop)."""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

# Mã lỗi SQLite báo file hỏng (SQLITE_CORRUPT, SQLITE_NOTADB). Các lỗi tạm thời như BUSY/LOCKED,
# CANTOPEN, READONLY, IOERR, FULL KHÔNG nằm ở đây: chúng không được phép dẫn tới việc cách ly DB.
_CORRUPTION_CODES = {11, 26}
_CORRUPTION_MESSAGES = ("file is not a database", "database disk image is malformed", "malformed database schema")
MAX_QUARANTINED_DBS = 3  # số bản DB hỏng được giữ lại để điều tra; bản cũ hơn bị xóa

# Chỉ cứu các bảng cấu hình nhỏ và có giá trị; lịch sử hội thoại có thể tự tạo lại và tự hết hạn.
_SALVAGE_TABLES = {
    "auto_chat_channels": ("channel_id, guild_id, added_by", (int, int, int)),
    "allowed_guilds": ("guild_id, added_by, added_at", (int, int, str)),
}


class DatabaseCorruptError(sqlite3.DatabaseError):
    """PRAGMA quick_check báo cấu trúc file DB bị hỏng."""


def _is_corruption(exc: BaseException) -> bool:
    if isinstance(exc, DatabaseCorruptError):
        return True
    if not isinstance(exc, sqlite3.DatabaseError):
        return False
    code = getattr(exc, "sqlite_errorcode", None)  # Python 3.11+
    if isinstance(code, int):
        return (code & 0xFF) in _CORRUPTION_CODES  # & 0xFF: bỏ phần mã mở rộng (vd. CORRUPT_VTAB)
    text = str(exc).lower()
    return any(marker in text for marker in _CORRUPTION_MESSAGES)


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        # Đường dẫn bản DB hỏng đã được cách ly trong lần init gần nhất (None = DB bình thường).
        self.recovered_from: str | None = None

    # ---------- nội bộ ----------
    def _secure_files(self) -> None:
        """Giới hạn quyền DB và file phụ WAL/SHM về 0600 (chứa nội dung hội thoại).

        SQLite tạo -wal/-shm với quyền của file DB chính tại thời điểm tạo, nên với DB đã tồn
        tại từ bản cũ (0644) phải chmod file chính TRƯỚC khi mở kết nối, rồi chmod lại các file
        phụ còn sót sau khi init.
        """
        if os.name != "posix" or self.path == ":memory:":
            return
        for suffix in ("", "-wal", "-shm"):
            target = self.path + suffix
            try:
                if os.path.isfile(target) and (os.stat(target).st_mode & 0o077):
                    os.chmod(target, 0o600)
            except OSError as e:
                log.warning("Không thể giới hạn quyền truy cập %s (%s)", suffix or "file DB", type(e).__name__)

    def _open_sync(self) -> None:
        self._secure_files()  # DB cũ: chmod trước để -wal/-shm tạo mới thừa kế quyền 0600
        # WAL/SHM có thể chứa nội dung hội thoại. Dùng umask riêng lúc tạo
        # database để các file phụ cũng không bị mở quyền theo umask hệ thống.
        previous_umask = os.umask(0o077) if os.name == "posix" else None
        try:
            conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        finally:
            if previous_umask is not None:
                os.umask(previous_umask)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA secure_delete=ON")
            conn.execute("PRAGMA wal_autocheckpoint=1000")
            conn.execute("PRAGMA journal_size_limit=16777216")
            conn.executescript(SCHEMA)
            # Phát hiện sớm file hỏng ở tầng dữ liệu: nếu không, lỗi chỉ lộ ra ở từng truy vấn lúc chạy.
            problems = [row[0] for row in conn.execute("PRAGMA quick_check").fetchall()]
            if problems != ["ok"]:
                raise DatabaseCorruptError("quick_check: " + "; ".join(str(p) for p in problems[:3]))
            # Dọn bảng Reminder cũ nếu DB được nâng cấp từ phiên bản trước.
            # Các bảng dữ liệu khác được giữ nguyên.
            conn.execute("DROP TABLE IF EXISTS reminders")
            # Bảng lịch sử cũ (khóa theo user_id, lẫn giữa các server) không còn dùng.
            conn.execute("DROP TABLE IF EXISTS conversations")
            conn.commit()
        except BaseException:
            try:
                conn.close()  # không để lại kết nối/file khóa khi init thất bại
            except sqlite3.Error:
                pass
            raise
        self._conn = conn
        self._secure_files()  # file -wal/-shm có thể vừa được tạo/còn sót từ lần chạy trước

    def _quarantine_sync(self, exc: BaseException) -> dict[str, list[tuple]]:
        """Chuyển DB hỏng (cùng -wal/-shm) sang file `.corrupt-<thời gian>` và cứu các bảng cấu hình.

        File hỏng được GIỮ LẠI để điều tra, không bị xóa. -wal/-shm bắt buộc phải đi cùng: để lại
        một WAL cũ cạnh DB mới sẽ bị SQLite cố phát lại lên file không liên quan.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = f"{self.path}.corrupt-{stamp}"
        counter = 1
        while os.path.exists(target):
            target = f"{self.path}.corrupt-{stamp}-{counter}"
            counter += 1
        log.error(
            "File DB %s bị hỏng (%s: %s). Chuyển sang %s và tạo DB mới; "
            "lịch sử hội thoại trong file hỏng không được khôi phục.",
            self.path, type(exc).__name__, exc, target,
        )
        for suffix in ("", "-wal", "-shm"):
            source = self.path + suffix
            if os.path.exists(source):
                os.replace(source, target + suffix)
                if os.name == "posix":
                    try:
                        os.chmod(target + suffix, 0o600)
                    except OSError:
                        pass
        self.recovered_from = target
        salvaged = self._salvage_config(target)
        self._prune_quarantined()
        return salvaged

    @staticmethod
    def _salvage_config(corrupt_path: str) -> dict[str, list[tuple]]:
        """Đọc (best-effort, chỉ đọc) các bảng cấu hình còn đọc được từ file hỏng."""
        salvaged: dict[str, list[tuple]] = {}
        try:
            # immutable=1: bỏ qua khóa và WAL, chỉ đọc file chính (cấu hình luôn được checkpoint vào file chính).
            conn = sqlite3.connect(f"{Path(corrupt_path).resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        except (sqlite3.Error, OSError, ValueError):
            return salvaged
        try:
            for table, (columns, types_) in _SALVAGE_TABLES.items():
                try:
                    rows = conn.execute(f"SELECT {columns} FROM {table}").fetchall()
                except sqlite3.Error:
                    continue  # bảng/trang này hỏng: bỏ qua, các bảng khác vẫn có thể cứu được
                valid = [
                    tuple(row)
                    for row in rows
                    if len(row) == len(types_)
                    and all(isinstance(v, t) and not isinstance(v, bool) for v, t in zip(row, types_))
                ]
                if valid:
                    salvaged[table] = valid
        finally:
            conn.close()
        return salvaged

    def _restore_config_sync(self, salvaged: dict[str, list[tuple]]) -> None:
        if not salvaged or self._conn is None:
            return
        try:
            for table, rows in salvaged.items():
                columns = _SALVAGE_TABLES[table][0]
                marks = ", ".join("?" for _ in rows[0])
                self._conn.executemany(f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({marks})", rows)
            self._conn.commit()
            log.warning(
                "Đã cứu từ DB hỏng: %s",
                ", ".join(f"{len(rows)} dòng {table}" for table, rows in salvaged.items()),
            )
        except sqlite3.Error:
            self._conn.rollback()
            log.exception("Không khôi phục được cấu hình đã cứu từ DB hỏng")

    def _prune_quarantined(self) -> None:
        """Chỉ giữ MAX_QUARANTINED_DBS bản DB hỏng mới nhất (chúng chứa nội dung hội thoại cũ)."""
        directory = os.path.dirname(os.path.abspath(self.path))
        prefix = os.path.basename(self.path) + ".corrupt-"
        try:
            names = sorted(
                n for n in os.listdir(directory)
                if n.startswith(prefix) and not n.endswith(("-wal", "-shm"))
            )
            for name in names[: max(0, len(names) - MAX_QUARANTINED_DBS)]:
                for suffix in ("", "-wal", "-shm"):
                    try:
                        os.remove(os.path.join(directory, name + suffix))
                    except FileNotFoundError:
                        pass
        except OSError as e:
            log.warning("Không dọn được các bản DB hỏng cũ (%s)", type(e).__name__)

    def _init_sync(self) -> None:
        if self.path != ":memory:":
            parent = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(parent, mode=0o700, exist_ok=True)
        self.recovered_from = None
        try:
            self._open_sync()
        except Exception as exc:
            # Chỉ file thực sự hỏng mới bị cách ly. Lỗi tạm thời (locked, thiếu quyền, đầy ổ đĩa...)
            # được ném nguyên vẹn để không đổi tên một DB còn lành chỉ vì một sự cố thoáng qua.
            if self.path == ":memory:" or not _is_corruption(exc):
                raise
            salvaged = self._quarantine_sync(exc)
            self._open_sync()  # nếu lần mở thứ hai vẫn lỗi thì ném ra, không lặp vô hạn
            self._restore_config_sync(salvaged)

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

    def _run_many_sync(self, statements: list[tuple[str, tuple]]) -> list[int]:
        """Chạy nhiều câu lệnh ghi trong MỘT transaction: hoặc tất cả được commit, hoặc không gì cả."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database chưa được init()")
            try:
                counts = [self._conn.execute(sql, params).rowcount for sql, params in statements]
                self._conn.commit()
                return counts
            except Exception:
                self._conn.rollback()
                raise

    async def _q(self, sql: str, params: tuple = (), mode: str = "exec"):
        return await asyncio.to_thread(self._run_sync, sql, params, mode)

    async def _tx(self, statements: list[tuple[str, tuple]]) -> list[int]:
        return await asyncio.to_thread(self._run_many_sync, statements)

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

    async def delete_guild_data(self, guild_id: int) -> tuple[int, int]:
        """Xóa lịch sử hội thoại và kênh auto-chat của một server (khi bot bị đuổi/rời server).

        Trả về (số lịch sử đã xóa, số kênh auto-chat đã xóa). Hai thao tác nằm trong cùng một transaction.
        """
        history_rows, channel_rows = await self._tx(
            [
                ("DELETE FROM chat_history WHERE guild_id = ?", (guild_id,)),
                ("DELETE FROM auto_chat_channels WHERE guild_id = ?", (guild_id,)),
            ]
        )
        if history_rows or channel_rows:
            await self._checkpoint()
        return history_rows, channel_rows

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
