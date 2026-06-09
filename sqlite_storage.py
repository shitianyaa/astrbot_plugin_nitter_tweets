"""SQLite storage backend for Nitter Tweets plugin."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any

from astrbot.api import logger

try:
    from .seen_store import SEEN_LIMIT_PER_USER, normalize_group_id
    from .utils import TweetItem, TweetMedia, normalize_username
except ImportError:
    from seen_store import SEEN_LIMIT_PER_USER, normalize_group_id
    from utils import TweetItem, TweetMedia, normalize_username


SCHEMA_VERSION = 2
ORPHAN_SEEN_RETENTION_DAYS = 30

PENDING_TWEETS_V2_COLUMN_ADD_STATEMENTS: dict[str, str] = {
    "instance": "ALTER TABLE pending_tweets ADD COLUMN instance TEXT NOT NULL DEFAULT ''",
    "published_at": "ALTER TABLE pending_tweets ADD COLUMN published_at INTEGER",
    "failed_at": "ALTER TABLE pending_tweets ADD COLUMN failed_at INTEGER",
    "fail_count": "ALTER TABLE pending_tweets ADD COLUMN fail_count INTEGER NOT NULL DEFAULT 0",
    "last_error": "ALTER TABLE pending_tweets ADD COLUMN last_error TEXT NOT NULL DEFAULT ''",
}
SQLITE_TABLE_NAMES = {"pending_tweets", "pending_media"}


@dataclass(slots=True)
class PendingTweetRecord:
    id: int
    group_id: str
    username: str
    status_id: str
    instance: str
    tweet: TweetItem
    created_at: int
    scheduled_at: int | None = None
    published_at: int | None = None
    sent_at: int | None = None
    failed_at: int | None = None
    fail_count: int = 0
    last_error: str = ""


@dataclass(slots=True)
class PendingQueueSummary:
    group_id: str
    pending_count: int = 0
    failed_count: int = 0
    media_count: int = 0
    oldest_created_at: int | None = None
    newest_created_at: int | None = None
    user_counts: list[tuple[str, int]] = field(default_factory=list)


def _locked_sqlite_method(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._conn_lock:
            try:
                result = method(self, *args, **kwargs)
                if self.conn is not None:
                    self.conn.commit()
                return result
            except Exception:
                if self.conn is not None:
                    try:
                        self.conn.rollback()
                    except sqlite3.Error:
                        pass
                raise

    return wrapper


class SQLiteStorage:
    """SQLite storage backend."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._conn_lock = threading.RLock()

    async def connect(self) -> None:
        """打开数据库连接并初始化表结构."""
        async with self._lock:
            if self.conn is not None:
                return

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            self.conn.row_factory = sqlite3.Row
            await asyncio.to_thread(self._init_schema)

    def close(self) -> None:
        """关闭数据库连接."""
        with self._conn_lock:
            if self.conn:
                self.conn.close()
                self.conn = None

    def _init_schema(self) -> None:
        """初始化数据库表结构."""
        with self._conn_lock:
            assert self.conn is not None

            cursor = self.conn.cursor()

            # 检查数据库完整性
            result = cursor.execute("PRAGMA integrity_check").fetchone()
            if result[0] != "ok":
                logger.error(
                    f"[NitterTweets] Database integrity check failed: {result[0]}"
                )
                raise RuntimeError("Database corruption detected")

            # meta 表：schema version、迁移标记、配置导入指纹
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)

            # 检查 schema version
            row = cursor.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()

            if row is None:
                # 首次初始化
                cursor.execute(
                    "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?)",
                    ("schema_version", str(SCHEMA_VERSION), int(time.time())),
                )
            else:
                stored_version = int(row[0])
                if stored_version > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Database schema version mismatch: "
                        f"expected <= {SCHEMA_VERSION}, got {stored_version}"
                    )
                if stored_version < SCHEMA_VERSION:
                    self._migrate_schema(cursor, stored_version)

            # groups 表：分组配置快照
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    group_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    check_on_startup INTEGER NOT NULL,
                    interval_check_enabled INTEGER NOT NULL,
                    check_interval_minutes INTEGER NOT NULL,
                    daily_check_enabled INTEGER NOT NULL,
                    daily_check_times TEXT NOT NULL,
                    scheduled_fetch_limit INTEGER NOT NULL,
                    send_target_interval REAL NOT NULL,
                    send_user_interval REAL NOT NULL,
                    notify_no_updates INTEGER NOT NULL,
                    aliases TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)

            # group_users 表：分组订阅账号
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS group_users (
                    group_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    added_at INTEGER NOT NULL,
                    PRIMARY KEY (group_id, username)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_group_users_group_id
                ON group_users(group_id)
            """)

            # group_targets 表：分组推送目标 UMO
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS group_targets (
                    group_id TEXT NOT NULL,
                    target_umo TEXT NOT NULL,
                    added_at INTEGER NOT NULL,
                    PRIMARY KEY (group_id, target_umo)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_group_targets_group_id
                ON group_targets(group_id)
            """)

            # seen_tweets 表：已见推文 ID
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen_tweets (
                    group_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    status_id TEXT NOT NULL,
                    seen_at INTEGER NOT NULL,
                    PRIMARY KEY (group_id, username, status_id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_seen_tweets_group_user
                ON seen_tweets(group_id, username)
            """)

            # pending_tweets 表：待推/发送队列
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_tweets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    status_id TEXT NOT NULL,
                    instance TEXT NOT NULL DEFAULT '',
                    tweet_data TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    scheduled_at INTEGER,
                    published_at INTEGER,
                    sent_at INTEGER,
                    failed_at INTEGER,
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT ''
                )
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_tweets_unique
                ON pending_tweets(group_id, username, status_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pending_tweets_schedule
                ON pending_tweets(group_id, scheduled_at)
                WHERE sent_at IS NULL
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pending_tweets_unsent
                ON pending_tweets(group_id, created_at)
                WHERE sent_at IS NULL
            """)

            # pending_media 表：暂存推文媒体，按推文 ID + 媒体索引绑定
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pending_tweet_id INTEGER NOT NULL,
                    media_index INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    url TEXT NOT NULL,
                    path TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(pending_tweet_id)
                        REFERENCES pending_tweets(id)
                        ON DELETE CASCADE,
                    UNIQUE(pending_tweet_id, media_index)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pending_media_tweet_id
                ON pending_media(pending_tweet_id)
            """)

            self.conn.commit()
            cursor.close()
            logger.info(f"[NitterTweets] SQLite storage initialized: {self.db_path}")

    def _migrate_schema(self, cursor: sqlite3.Cursor, stored_version: int) -> None:
        if stored_version < 2:
            self._migrate_schema_v2(cursor)
        cursor.execute(
            """
            INSERT INTO meta (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            ("schema_version", str(SCHEMA_VERSION), int(time.time())),
        )

    def _migrate_schema_v2(self, cursor: sqlite3.Cursor) -> None:
        if not self._table_exists(cursor, "pending_tweets"):
            return

        columns = self._table_columns(cursor, "pending_tweets")
        for name, statement in PENDING_TWEETS_V2_COLUMN_ADD_STATEMENTS.items():
            if name not in columns:
                cursor.execute(statement)
        cursor.execute(
            """
            DELETE FROM pending_tweets
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM pending_tweets
                GROUP BY group_id, username, status_id
            )
            """
        )

    @staticmethod
    def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
        row = cursor.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        return row is not None

    @classmethod
    def _table_columns(cls, cursor: sqlite3.Cursor, table_name: str) -> set[str]:
        if table_name not in SQLITE_TABLE_NAMES:
            raise ValueError(f"Unsupported SQLite table: {table_name}")
        rows = cursor.execute(
            "SELECT name FROM pragma_table_info(?)",
            (table_name,),
        ).fetchall()
        return {str(row[0]) for row in rows}

    def set_meta(self, key: str, value: str) -> None:
        """设置 meta 键值."""
        assert self.conn is not None
        self.conn.execute(
            """
            INSERT INTO meta (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, int(time.time())),
        )

    def get_meta(self, key: str) -> str | None:
        """获取 meta 键值."""
        assert self.conn is not None
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (key,),
        ).fetchone()
        return row[0] if row else None

    def upsert_group(
        self,
        group_id: str,
        name: str,
        enabled: bool,
        check_on_startup: bool,
        interval_check_enabled: bool,
        check_interval_minutes: int,
        daily_check_enabled: bool,
        daily_check_times: list[tuple[int, int]],
        scheduled_fetch_limit: int,
        send_target_interval: float,
        send_user_interval: float,
        notify_no_updates: bool,
        aliases: list[str],
    ) -> None:
        """插入或更新分组配置."""
        assert self.conn is not None

        normalized_group_id = normalize_group_id(group_id)
        now = int(time.time())

        # 检查是否存在
        row = self.conn.execute(
            "SELECT created_at FROM groups WHERE group_id = ?",
            (normalized_group_id,),
        ).fetchone()

        created_at = row[0] if row else now

        self.conn.execute(
            """
            INSERT INTO groups (
                group_id, name, enabled, check_on_startup,
                interval_check_enabled, check_interval_minutes,
                daily_check_enabled, daily_check_times,
                scheduled_fetch_limit, send_target_interval,
                send_user_interval, notify_no_updates, aliases,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                name = excluded.name,
                enabled = excluded.enabled,
                check_on_startup = excluded.check_on_startup,
                interval_check_enabled = excluded.interval_check_enabled,
                check_interval_minutes = excluded.check_interval_minutes,
                daily_check_enabled = excluded.daily_check_enabled,
                daily_check_times = excluded.daily_check_times,
                scheduled_fetch_limit = excluded.scheduled_fetch_limit,
                send_target_interval = excluded.send_target_interval,
                send_user_interval = excluded.send_user_interval,
                notify_no_updates = excluded.notify_no_updates,
                aliases = excluded.aliases,
                updated_at = excluded.updated_at
            """,
            (
                normalized_group_id,
                name,
                1 if enabled else 0,
                1 if check_on_startup else 0,
                1 if interval_check_enabled else 0,
                check_interval_minutes,
                1 if daily_check_enabled else 0,
                json.dumps(daily_check_times),
                scheduled_fetch_limit,
                send_target_interval,
                send_user_interval,
                1 if notify_no_updates else 0,
                json.dumps(aliases),
                created_at,
                now,
            ),
        )

    def set_group_users(self, group_id: str, usernames: list[str]) -> None:
        """设置分组的订阅账号列表（替换现有）."""
        assert self.conn is not None

        normalized_group_id = normalize_group_id(group_id)
        now = int(time.time())

        # 删除旧的
        self.conn.execute(
            "DELETE FROM group_users WHERE group_id = ?",
            (normalized_group_id,),
        )

        # 插入新的
        normalized_usernames = [
            normalize_username(u) for u in usernames if normalize_username(u)
        ]

        if normalized_usernames:
            self.conn.executemany(
                """
                INSERT INTO group_users (group_id, username, added_at)
                VALUES (?, ?, ?)
                """,
                [(normalized_group_id, u, now) for u in normalized_usernames],
            )

    def get_group_users(self, group_id: str) -> list[str]:
        """获取分组的订阅账号列表."""
        assert self.conn is not None

        normalized_group_id = normalize_group_id(group_id)
        rows = self.conn.execute(
            "SELECT username FROM group_users WHERE group_id = ? ORDER BY username",
            (normalized_group_id,),
        ).fetchall()

        return [row[0] for row in rows]

    def set_group_targets(self, group_id: str, target_umos: list[str]) -> None:
        """设置分组的推送目标列表（替换现有）."""
        assert self.conn is not None

        normalized_group_id = normalize_group_id(group_id)
        now = int(time.time())

        # 删除旧的
        self.conn.execute(
            "DELETE FROM group_targets WHERE group_id = ?",
            (normalized_group_id,),
        )

        # 插入新的
        if target_umos:
            self.conn.executemany(
                """
                INSERT INTO group_targets (group_id, target_umo, added_at)
                VALUES (?, ?, ?)
                """,
                [(normalized_group_id, umo, now) for umo in target_umos],
            )

    def get_group_targets(self, group_id: str) -> list[str]:
        """获取分组的推送目标列表."""
        assert self.conn is not None

        normalized_group_id = normalize_group_id(group_id)
        rows = self.conn.execute(
            "SELECT target_umo FROM group_targets WHERE group_id = ? ORDER BY target_umo",
            (normalized_group_id,),
        ).fetchall()

        return [row[0] for row in rows]

    def get_all_groups(self) -> list[dict[str, Any]]:
        """获取所有分组配置."""
        assert self.conn is not None

        rows = self.conn.execute(
            "SELECT * FROM groups ORDER BY group_id"
        ).fetchall()

        groups = []
        for row in rows:
            groups.append({
                "group_id": row["group_id"],
                "name": row["name"],
                "enabled": bool(row["enabled"]),
                "check_on_startup": bool(row["check_on_startup"]),
                "interval_check_enabled": bool(row["interval_check_enabled"]),
                "check_interval_minutes": row["check_interval_minutes"],
                "daily_check_enabled": bool(row["daily_check_enabled"]),
                "daily_check_times": json.loads(row["daily_check_times"]),
                "scheduled_fetch_limit": row["scheduled_fetch_limit"],
                "send_target_interval": row["send_target_interval"],
                "send_user_interval": row["send_user_interval"],
                "notify_no_updates": bool(row["notify_no_updates"]),
                "aliases": json.loads(row["aliases"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })

        return groups

    def get_seen_ids(self, group_id: str, username: str) -> list[str]:
        """获取指定分组和用户的已见推文 ID 列表."""
        assert self.conn is not None

        normalized_group_id = normalize_group_id(group_id)
        normalized_username = normalize_username(username)

        if not normalized_username:
            return []

        rows = self.conn.execute(
            """
            SELECT status_id FROM seen_tweets
            WHERE group_id = ? AND username = ?
            ORDER BY seen_at DESC
            LIMIT ?
            """,
            (normalized_group_id, normalized_username, SEEN_LIMIT_PER_USER),
        ).fetchall()

        return [row[0] for row in rows]

    def add_seen_ids(
        self,
        group_id: str,
        username: str,
        status_ids: list[str],
    ) -> None:
        """添加已见推文 ID（批量）."""
        assert self.conn is not None

        normalized_group_id = normalize_group_id(group_id)
        normalized_username = normalize_username(username)

        if not normalized_username or not status_ids:
            return

        now = int(time.time())

        # 批量插入或更新时间戳（REPLACE = DELETE + INSERT）
        self.conn.executemany(
            """
            REPLACE INTO seen_tweets (group_id, username, status_id, seen_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (normalized_group_id, normalized_username, sid, now)
                for sid in status_ids
                if sid
            ],
        )

        # 清理超过限制的旧记录
        self.conn.execute(
            """
            DELETE FROM seen_tweets
            WHERE group_id = ? AND username = ?
              AND rowid NOT IN (
                  SELECT rowid FROM seen_tweets
                  WHERE group_id = ? AND username = ?
                  ORDER BY seen_at DESC
                  LIMIT ?
              )
            """,
            (normalized_group_id, normalized_username,
             normalized_group_id, normalized_username,
             SEEN_LIMIT_PER_USER),
        )

    def get_group_seen_map(self, group_id: str) -> dict[str, list[str]]:
        """获取指定分组的所有用户 seen map."""
        assert self.conn is not None

        normalized_group_id = normalize_group_id(group_id)

        rows = self.conn.execute(
            """
            SELECT username, status_id FROM seen_tweets
            WHERE group_id = ?
            ORDER BY username, seen_at DESC
            """,
            (normalized_group_id,),
        ).fetchall()

        seen_map: dict[str, list[str]] = {}
        for row in rows:
            username = row[0]
            status_id = row[1]
            if username not in seen_map:
                seen_map[username] = []
            if len(seen_map[username]) < SEEN_LIMIT_PER_USER:
                seen_map[username].append(status_id)

        return seen_map

    def enqueue_pending_tweets(
        self,
        group_id: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        scheduled_at: int | None = None,
    ) -> int:
        """Add tweets to the pending publish queue."""
        assert self.conn is not None

        normalized_group_id = normalize_group_id(group_id)
        normalized_username = normalize_username(username)
        if not normalized_username or not tweets:
            return 0

        now = int(time.time())
        inserted = 0
        for tweet in tweets:
            status_id = str(tweet.status_id or "").strip()
            if not status_id:
                continue
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO pending_tweets (
                    group_id, username, status_id, instance, tweet_data,
                    created_at, scheduled_at, published_at, sent_at,
                    failed_at, fail_count, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, '')
                """,
                (
                    normalized_group_id,
                    normalized_username,
                    status_id,
                    instance or "",
                    self._serialize_tweet(tweet),
                    now,
                    scheduled_at,
                ),
            )
            if int(cursor.rowcount or 0) <= 0:
                continue

            pending_tweet_id = int(cursor.lastrowid)
            media_rows = [
                (
                    pending_tweet_id,
                    media_index,
                    media.kind,
                    media.url,
                    str(media.path) if media.path else "",
                    now,
                )
                for media_index, media in enumerate(tweet.media)
            ]
            if media_rows:
                self.conn.executemany(
                    """
                    INSERT INTO pending_media (
                        pending_tweet_id, media_index, kind, url, path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    media_rows,
                )
            inserted += 1
        return inserted

    def get_pending_tweets(
        self,
        group_id: str,
        limit: int,
    ) -> list[PendingTweetRecord]:
        """Get unsent pending tweets for a group."""
        assert self.conn is not None

        with self._conn_lock:
            normalized_group_id = normalize_group_id(group_id)
            rows = self.conn.execute(
                """
                SELECT * FROM pending_tweets
                WHERE group_id = ? AND sent_at IS NULL
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (normalized_group_id, max(1, int(limit))),
            ).fetchall()
            if not rows:
                return []

            pending_ids = [int(row["id"]) for row in rows]
            media_map = self._pending_media_map(pending_ids)
            return [self._pending_record_from_row(row, media_map) for row in rows]

    def get_pending_queue_summary(self, group_id: str) -> PendingQueueSummary:
        """Get pending queue counts for a group."""
        assert self.conn is not None

        normalized_group_id = normalize_group_id(group_id)
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS pending_count,
                SUM(CASE WHEN failed_at IS NOT NULL THEN 1 ELSE 0 END)
                    AS failed_count,
                MIN(created_at) AS oldest_created_at,
                MAX(created_at) AS newest_created_at
            FROM pending_tweets
            WHERE group_id = ? AND sent_at IS NULL
            """,
            (normalized_group_id,),
        ).fetchone()
        media_row = self.conn.execute(
            """
            SELECT COUNT(*) AS media_count
            FROM pending_media
            WHERE pending_tweet_id IN (
                SELECT id FROM pending_tweets
                WHERE group_id = ? AND sent_at IS NULL
            )
            """,
            (normalized_group_id,),
        ).fetchone()
        user_rows = self.conn.execute(
            """
            SELECT username, COUNT(*) AS pending_count
            FROM pending_tweets
            WHERE group_id = ? AND sent_at IS NULL
            GROUP BY username
            ORDER BY pending_count DESC, username COLLATE NOCASE ASC
            LIMIT 10
            """,
            (normalized_group_id,),
        ).fetchall()
        return PendingQueueSummary(
            group_id=normalized_group_id,
            pending_count=int(row["pending_count"] or 0),
            failed_count=int(row["failed_count"] or 0),
            media_count=int(media_row["media_count"] or 0),
            oldest_created_at=row["oldest_created_at"],
            newest_created_at=row["newest_created_at"],
            user_counts=[
                (str(item["username"]), int(item["pending_count"] or 0))
                for item in user_rows
            ],
        )

    def get_pending_media_paths(self) -> set[str]:
        """Get staged media paths still referenced by unsent queue rows."""
        assert self.conn is not None
        rows = self.conn.execute(
            """
            SELECT pending_media.path
            FROM pending_media
            JOIN pending_tweets
                ON pending_tweets.id = pending_media.pending_tweet_id
            WHERE pending_tweets.sent_at IS NULL
              AND pending_media.path != ''
            """
        ).fetchall()
        return {str(row[0]) for row in rows if row[0]}

    def mark_pending_tweets_published(self, pending_ids: list[int]) -> None:
        """Mark pending tweets as sent."""
        assert self.conn is not None
        ids = [int(item) for item in pending_ids if int(item) > 0]
        if not ids:
            return
        now = int(time.time())
        self.conn.executemany(
            """
            UPDATE pending_tweets
            SET published_at = COALESCE(published_at, ?),
                sent_at = ?,
                last_error = ''
            WHERE id = ?
            """,
            [(now, now, pending_id) for pending_id in ids],
        )

    def mark_pending_tweets_failed(
        self, pending_ids: list[int], error: str
    ) -> None:
        """Record a publish failure for pending tweets."""
        assert self.conn is not None
        ids = [int(item) for item in pending_ids if int(item) > 0]
        if not ids:
            return
        now = int(time.time())
        message = str(error or "")[:1000]
        self.conn.executemany(
            """
            UPDATE pending_tweets
            SET failed_at = ?,
                fail_count = fail_count + 1,
                last_error = ?
            WHERE id = ? AND sent_at IS NULL
            """,
            [(now, message, pending_id) for pending_id in ids],
        )

    def delete_pending_tweets(self, pending_ids: list[int]) -> None:
        """Delete pending tweets and their media rows."""
        assert self.conn is not None
        ids = [int(item) for item in pending_ids if int(item) > 0]
        if not ids:
            return
        self.conn.executemany(
            "DELETE FROM pending_media WHERE pending_tweet_id = ?",
            [(pending_id,) for pending_id in ids],
        )
        self.conn.executemany(
            "DELETE FROM pending_tweets WHERE id = ?",
            [(pending_id,) for pending_id in ids],
        )

    def cleanup_sent_pending_tweets(self, older_than: int) -> int:
        """Delete sent pending tweet rows at or before the timestamp."""
        assert self.conn is not None
        ids = [
            int(row[0])
            for row in self.conn.execute(
                """
                SELECT id FROM pending_tweets
                WHERE sent_at IS NOT NULL AND sent_at <= ?
                """,
                (older_than,),
            ).fetchall()
        ]
        self.delete_pending_tweets(ids)
        return len(ids)

    def cleanup_orphan_seen_tweets(self) -> int:
        """清理长期不在订阅配置中的 seen 记录."""
        assert self.conn is not None

        cutoff = int(time.time()) - ORPHAN_SEEN_RETENTION_DAYS * 86400
        cursor = self.conn.execute(
            """
            DELETE FROM seen_tweets
            WHERE seen_at < ?
              AND NOT EXISTS (
                  SELECT 1 FROM group_users
                  WHERE group_users.group_id = seen_tweets.group_id
                    AND group_users.username = seen_tweets.username
              )
            """,
            (cutoff,),
        )
        return int(cursor.rowcount or 0)

    @staticmethod
    def _serialize_tweet(tweet: TweetItem) -> str:
        return json.dumps(
            {
                "text": tweet.text,
                "link": tweet.link,
                "published": tweet.published,
                "media_warnings": tweet.media_warnings,
                "translation": tweet.translation,
                "image_caption": tweet.image_caption,
                "ai_comment": tweet.ai_comment,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _deserialize_tweet(raw_data: str) -> TweetItem:
        try:
            data = json.loads(raw_data)
        except (TypeError, ValueError):
            data = {}
        return TweetItem(
            text=str(data.get("text") or ""),
            link=str(data.get("link") or ""),
            published=str(data.get("published") or ""),
            media_warnings=[
                str(item)
                for item in data.get("media_warnings", [])
                if str(item)
            ],
            translation=str(data.get("translation") or ""),
            image_caption=str(data.get("image_caption") or ""),
            ai_comment=str(data.get("ai_comment") or ""),
        )

    def _pending_media_map(
        self, pending_ids: list[int]
    ) -> dict[int, list[TweetMedia]]:
        if not pending_ids:
            return {}
        assert self.conn is not None
        ids = [(int(item),) for item in pending_ids if int(item) > 0]
        if not ids:
            return {}
        self.conn.execute(
            """
            CREATE TEMP TABLE IF NOT EXISTS temp_pending_media_ids (
                id INTEGER PRIMARY KEY
            )
            """
        )
        self.conn.execute("DELETE FROM temp_pending_media_ids")
        self.conn.executemany(
            "INSERT OR IGNORE INTO temp_pending_media_ids (id) VALUES (?)",
            ids,
        )
        rows = self.conn.execute(
            """
            SELECT pending_tweet_id, kind, url, path
            FROM pending_media
            JOIN temp_pending_media_ids
                ON temp_pending_media_ids.id = pending_media.pending_tweet_id
            ORDER BY pending_tweet_id, media_index
            """,
        ).fetchall()
        media_map: dict[int, list[TweetMedia]] = {}
        for row in rows:
            media_path = str(row["path"] or "")
            media_map.setdefault(int(row["pending_tweet_id"]), []).append(
                TweetMedia(
                    kind=str(row["kind"] or ""),
                    url=str(row["url"] or ""),
                    path=Path(media_path) if media_path else None,
                )
            )
        return media_map

    def _pending_record_from_row(
        self,
        row: sqlite3.Row,
        media_map: dict[int, list[TweetMedia]],
    ) -> PendingTweetRecord:
        pending_id = int(row["id"])
        tweet = self._deserialize_tweet(row["tweet_data"])
        tweet.media = media_map.get(pending_id, [])
        return PendingTweetRecord(
            id=pending_id,
            group_id=str(row["group_id"]),
            username=str(row["username"]),
            status_id=str(row["status_id"]),
            instance=str(row["instance"] or ""),
            tweet=tweet,
            created_at=int(row["created_at"]),
            scheduled_at=row["scheduled_at"],
            published_at=row["published_at"],
            sent_at=row["sent_at"],
            failed_at=row["failed_at"],
            fail_count=int(row["fail_count"] or 0),
            last_error=str(row["last_error"] or ""),
        )

    def migrate_kv_seen_data(
        self,
        grouped_seen_map: dict[str, dict[str, list[str]]],
    ) -> None:
        """从 KV 存储迁移 seen 数据到 SQLite."""
        assert self.conn is not None

        # 检查是否已迁移
        migrated_at = self.get_meta("kv_seen_migrated_at")
        if migrated_at:
            logger.info("[NitterTweets] KV seen data already migrated, skipping")
            return

        logger.info("[NitterTweets] Starting KV seen data migration...")

        try:
            cursor = self.conn.cursor()
            cursor.execute("BEGIN")

            total_users = 0
            total_ids = 0
            now = int(time.time())

            for group_id, seen_map in grouped_seen_map.items():
                normalized_group_id = normalize_group_id(group_id)

                for username, status_ids in seen_map.items():
                    normalized_username = normalize_username(username)
                    if not normalized_username:
                        continue

                    # 只迁移最近 SEEN_LIMIT_PER_USER 条
                    limited_ids = status_ids[:SEEN_LIMIT_PER_USER]

                    if limited_ids:
                        cursor.executemany(
                            """
                            INSERT OR IGNORE INTO seen_tweets
                            (group_id, username, status_id, seen_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            [
                                (normalized_group_id, normalized_username, sid, now)
                                for sid in limited_ids
                                if sid
                            ],
                        )
                        total_users += 1
                        total_ids += len(limited_ids)

            # 标记迁移完成
            cursor.execute(
                """
                INSERT INTO meta (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                ("kv_seen_migrated_at", str(now), now),
            )

            cursor.execute("COMMIT")
            cursor.close()

            logger.info(
                f"[NitterTweets] KV seen data migration completed: "
                f"{total_users} users, {total_ids} status IDs"
            )

        except Exception as exc:
            if self.conn:
                self.conn.execute("ROLLBACK")
            logger.error(f"[NitterTweets] KV seen data migration failed: {exc}")
            raise

    def sync_config_groups(self, schedule_groups: list) -> None:
        """从配置同步分组到数据库."""
        assert self.conn is not None

        # 计算配置指纹
        fingerprint_data = []
        for group in schedule_groups:
            fingerprint_data.append({
                "group_id": group.group_id,
                "name": group.name,
                "users": sorted(group.users),
                "targets": sorted(group.targets),
            })

        config_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_data, sort_keys=True).encode()
        ).hexdigest()[:32]  # 128 bits for lower collision risk

        stored_fingerprint = self.get_meta("config_groups_fingerprint")

        if stored_fingerprint == config_fingerprint:
            logger.debug("[NitterTweets] Config groups unchanged, skipping sync")
            return

        logger.info("[NitterTweets] Syncing config groups to database...")

        for group in schedule_groups:
            # 同步分组配置
            self.upsert_group(
                group_id=group.group_id,
                name=group.name,
                enabled=group.enabled,
                check_on_startup=group.check_on_startup,
                interval_check_enabled=group.interval_check_enabled,
                check_interval_minutes=group.check_interval_minutes,
                daily_check_enabled=group.daily_check_enabled,
                daily_check_times=group.daily_check_times,
                scheduled_fetch_limit=group.scheduled_fetch_limit,
                send_target_interval=group.send_target_interval,
                send_user_interval=group.send_user_interval,
                notify_no_updates=group.notify_no_updates,
                aliases=group.aliases,
            )

            # 同步订阅账号
            self.set_group_users(group.group_id, group.users)

            # 同步推送目标
            self.set_group_targets(group.group_id, group.targets)

        deleted_seen = self.cleanup_orphan_seen_tweets()
        if deleted_seen:
            logger.info(
                f"[NitterTweets] Cleaned {deleted_seen} orphan seen tweet records"
            )

        # 更新指纹
        self.set_meta("config_groups_fingerprint", config_fingerprint)

        logger.info(f"[NitterTweets] Synced {len(schedule_groups)} groups to database")


for _method_name in (
    "set_meta",
    "get_meta",
    "upsert_group",
    "set_group_users",
    "get_group_users",
    "set_group_targets",
    "get_group_targets",
    "get_all_groups",
    "get_seen_ids",
    "add_seen_ids",
    "get_group_seen_map",
    "enqueue_pending_tweets",
    "get_pending_tweets",
    "get_pending_queue_summary",
    "get_pending_media_paths",
    "mark_pending_tweets_published",
    "mark_pending_tweets_failed",
    "delete_pending_tweets",
    "cleanup_sent_pending_tweets",
    "cleanup_orphan_seen_tweets",
    "migrate_kv_seen_data",
    "sync_config_groups",
):
    setattr(
        SQLiteStorage,
        _method_name,
        _locked_sqlite_method(getattr(SQLiteStorage, _method_name)),
    )
