"""SQLite storage backend for Nitter Tweets plugin."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any

from astrbot.api import logger

try:
    from ..shared.group_ids import (
        DEFAULT_GROUP_ID,
        LEGACY_GLOBAL_GROUP_ID,
        normalize_stable_group_id,
    )
    from .seen import SEEN_LIMIT_PER_USER
    from ..shared import TweetItem, TweetMedia, normalize_username
except ImportError:
    from shared.group_ids import (
        DEFAULT_GROUP_ID,
        LEGACY_GLOBAL_GROUP_ID,
        normalize_stable_group_id,
    )
    from storage.seen import SEEN_LIMIT_PER_USER
    from shared import TweetItem, TweetMedia, normalize_username


SCHEMA_VERSION = 7
ORPHAN_SEEN_RETENTION_DAYS = 30

PUSH_HISTORY_V6_COLUMN_ADD_STATEMENTS: dict[str, str] = {
    "delivery_status": (
        "ALTER TABLE push_history "
        "ADD COLUMN delivery_status TEXT NOT NULL DEFAULT 'success'"
    ),
    "delivery_error": (
        "ALTER TABLE push_history "
        "ADD COLUMN delivery_error TEXT NOT NULL DEFAULT ''"
    ),
}
SQLITE_TABLE_NAMES = {"push_history"}




@dataclass(slots=True)
class PushHistoryRecord:
    id: int
    group_id: str
    username: str
    status_id: str
    original_link: str
    target_umo: str
    source: str
    instance: str
    pushed_at: int
    tweet: TweetItem
    delivery_status: str = "success"
    delivery_error: str = ""


@dataclass(slots=True)
class PushHistoryGroupSummary:
    group_id: str
    record_count: int
    user_count: int
    latest_pushed_at: int


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
                    f"[NitterTweets] 数据库完整性检查失败: {result[0]}"
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


            self._create_push_history_table(cursor)

            self.conn.commit()
            cursor.close()
            logger.info(f"[NitterTweets] SQLite 存储已初始化: {self.db_path}")

    def _migrate_schema(self, cursor: sqlite3.Cursor, stored_version: int) -> None:
        if stored_version < 2:
            self._migrate_schema_v2(cursor)
        if stored_version < 3:
            self._migrate_schema_v3(cursor)
        if stored_version < 4:
            self._migrate_schema_v4(cursor)
        if stored_version < 5:
            self._migrate_schema_v5(cursor)
        if stored_version < 6:
            self._migrate_schema_v6(cursor)
        if stored_version < 7:
            self._migrate_schema_v7(cursor)
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
        return

    def _migrate_schema_v3(self, cursor: sqlite3.Cursor) -> None:
        return

    def _migrate_schema_v4(self, cursor: sqlite3.Cursor) -> None:
        return

    def _migrate_schema_v5(self, cursor: sqlite3.Cursor) -> None:
        self._create_push_history_table(cursor)

    def _migrate_schema_v6(self, cursor: sqlite3.Cursor) -> None:
        self._ensure_push_history_delivery_columns(cursor)

    def _migrate_schema_v7(self, cursor: sqlite3.Cursor) -> None:
        # Pending/deferred publishing was removed in 0.16.0.
        cursor.execute("DROP TABLE IF EXISTS pending_media")
        cursor.execute("DROP TABLE IF EXISTS pending_tweets")

    def _create_push_history_table(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS push_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                username TEXT NOT NULL,
                status_id TEXT NOT NULL,
                original_link TEXT NOT NULL,
                target_umo TEXT NOT NULL,
                source TEXT NOT NULL,
                instance TEXT NOT NULL DEFAULT '',
                tweet_data TEXT NOT NULL,
                pushed_at INTEGER NOT NULL,
                delivery_status TEXT NOT NULL DEFAULT 'success',
                delivery_error TEXT NOT NULL DEFAULT ''
            )
        """)
        self._ensure_push_history_delivery_columns(cursor)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_push_history_group_time
            ON push_history(group_id, pushed_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_push_history_user_time
            ON push_history(username, pushed_at DESC)
        """)

    def _migrate_global_group_to_default(self, cursor: sqlite3.Cursor) -> None:
        legacy_id = LEGACY_GLOBAL_GROUP_ID
        default_id = DEFAULT_GROUP_ID
        now = int(time.time())

        if self._table_exists(cursor, "groups"):
            legacy_group = cursor.execute(
                "SELECT * FROM groups WHERE group_id = ?",
                (legacy_id,),
            ).fetchone()
            default_group = cursor.execute(
                "SELECT 1 FROM groups WHERE group_id = ?",
                (default_id,),
            ).fetchone()
            if legacy_group is not None and default_group is None:
                cursor.execute(
                    """
                    UPDATE groups
                    SET group_id = ?,
                        name = CASE WHEN name = '全局分组' THEN '默认分组' ELSE name END,
                        updated_at = ?
                    WHERE group_id = ?
                    """,
                    (default_id, now, legacy_id),
                )
            elif legacy_group is not None:
                cursor.execute("DELETE FROM groups WHERE group_id = ?", (legacy_id,))

        self._merge_group_key_table(
            cursor,
            table="group_users",
            legacy_id=legacy_id,
            default_id=default_id,
            key_column="username",
        )
        self._merge_group_key_table(
            cursor,
            table="group_targets",
            legacy_id=legacy_id,
            default_id=default_id,
            key_column="target_umo",
        )
        self._merge_group_key_table(
            cursor,
            table="seen_tweets",
            legacy_id=legacy_id,
            default_id=default_id,
            key_column=("username", "status_id"),
        )

    def _merge_group_key_table(
        self,
        cursor: sqlite3.Cursor,
        table: str,
        legacy_id: str,
        default_id: str,
        key_column: str | tuple[str, ...],
    ) -> None:
        if not self._table_exists(cursor, table):
            return
        key_columns = (key_column,) if isinstance(key_column, str) else key_column
        predicate = " AND ".join(
            f"target.{column} = {table}.{column}" for column in key_columns
        )
        cursor.execute(
            f"""
            DELETE FROM {table}
            WHERE group_id = ?
              AND EXISTS (
                  SELECT 1 FROM {table} AS target
                  WHERE target.group_id = ?
                    AND {predicate}
              )
            """,
            (legacy_id, default_id),
        )
        cursor.execute(
            f"UPDATE {table} SET group_id = ? WHERE group_id = ?",
            (default_id, legacy_id),
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

        normalized_group_id = normalize_stable_group_id(group_id)
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

        normalized_group_id = normalize_stable_group_id(group_id)
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

        normalized_group_id = normalize_stable_group_id(group_id)
        rows = self.conn.execute(
            "SELECT username FROM group_users WHERE group_id = ? ORDER BY username",
            (normalized_group_id,),
        ).fetchall()

        return [row[0] for row in rows]

    def set_group_targets(self, group_id: str, target_umos: list[str]) -> None:
        """设置分组的推送目标列表（替换现有）."""
        assert self.conn is not None

        normalized_group_id = normalize_stable_group_id(group_id)
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

        normalized_group_id = normalize_stable_group_id(group_id)
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

        normalized_group_id = normalize_stable_group_id(group_id)
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

        normalized_group_id = normalize_stable_group_id(group_id)
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

        normalized_group_id = normalize_stable_group_id(group_id)

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

    def clear_seen_tweets(self, group_id: str | None = None) -> int:
        """清理 seen 记录；group_id 为空时清理全部分组."""
        assert self.conn is not None

        if group_id:
            cursor = self.conn.execute(
                "DELETE FROM seen_tweets WHERE group_id = ?",
                (normalize_stable_group_id(group_id),),
            )
        else:
            cursor = self.conn.execute("DELETE FROM seen_tweets")
        return int(cursor.rowcount or 0)









    def delete_group_runtime_data(self, group_id: str) -> dict[str, int]:
        """Delete one group's runtime rows."""
        assert self.conn is not None
        normalized_group_id = normalize_stable_group_id(group_id)
        summary = {
            "groups_deleted": 0,
            "users_deleted": 0,
            "targets_deleted": 0,
            "seen_deleted": 0,
            "push_history_deleted": 0,
        }
        summary["seen_deleted"] = int(
            self.conn.execute(
                "DELETE FROM seen_tweets WHERE group_id = ?",
                (normalized_group_id,),
            ).rowcount
            or 0
        )
        summary["push_history_deleted"] = int(
            self.conn.execute(
                "DELETE FROM push_history WHERE group_id = ?",
                (normalized_group_id,),
            ).rowcount
            or 0
        )
        summary["users_deleted"] = int(
            self.conn.execute(
                "DELETE FROM group_users WHERE group_id = ?",
                (normalized_group_id,),
            ).rowcount
            or 0
        )
        summary["targets_deleted"] = int(
            self.conn.execute(
                "DELETE FROM group_targets WHERE group_id = ?",
                (normalized_group_id,),
            ).rowcount
            or 0
        )
        summary["groups_deleted"] = int(
            self.conn.execute(
                "DELETE FROM groups WHERE group_id = ?",
                (normalized_group_id,),
            ).rowcount
            or 0
        )
        return summary


    def record_push_history(
        self,
        group_id: str,
        username: str,
        tweet: TweetItem,
        target_umo: str,
        source: str,
        instance: str = "",
        pushed_at: int | None = None,
        delivery_status: str = "success",
        delivery_error: str = "",
    ) -> int:
        """Record one successfully pushed tweet/target pair."""
        assert self.conn is not None
        normalized_group_id = normalize_stable_group_id(group_id)
        normalized_username = normalize_username(username) or str(username or "").strip()
        status_id = str(getattr(tweet, "status_id", "") or "").strip()
        if not normalized_group_id or not normalized_username or not status_id:
            return 0
        now = int(pushed_at if pushed_at is not None else time.time())
        cursor = self.conn.execute(
            """
            INSERT INTO push_history (
                group_id, username, status_id, original_link, target_umo,
                source, instance, tweet_data, pushed_at,
                delivery_status, delivery_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_group_id,
                normalized_username,
                status_id,
                str(getattr(tweet, "x_url", "") or getattr(tweet, "link", "") or ""),
                str(target_umo or "").strip(),
                str(source or "").strip() or "scheduled",
                str(instance or ""),
                self._serialize_tweet(tweet),
                now,
                self._normalize_delivery_status(delivery_status),
                str(delivery_error or "").strip(),
            ),
        )
        return int(cursor.lastrowid or 0)

    def get_push_history(
        self,
        group_id: str = "",
        username: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[PushHistoryRecord]:
        """Return recent successful push history records."""
        assert self.conn is not None
        where, params = self._push_history_filter(group_id, username)
        params.extend(
            [
                max(1, min(int(limit or 50), 51)),
                max(0, int(offset or 0)),
            ]
        )
        rows = self.conn.execute(
            f"""
            WITH display_page AS (
                SELECT
                    group_id,
                    username,
                    status_id,
                    source,
                    original_link,
                    MAX(pushed_at) AS latest_pushed_at,
                    MAX(id) AS latest_id
                FROM push_history
                {where}
                GROUP BY group_id, username, status_id, source, original_link
                ORDER BY latest_pushed_at DESC, latest_id DESC
                LIMIT ? OFFSET ?
            )
            SELECT push_history.*
            FROM push_history
            JOIN display_page
              ON push_history.group_id = display_page.group_id
             AND push_history.username = display_page.username
             AND push_history.status_id = display_page.status_id
             AND push_history.source = display_page.source
             AND push_history.original_link = display_page.original_link
            ORDER BY
                display_page.latest_pushed_at DESC,
                display_page.latest_id DESC,
                push_history.pushed_at DESC,
                push_history.id DESC
            """,
            params,
        ).fetchall()
        return [self._push_history_record_from_row(row) for row in rows]

    def count_push_history(self, group_id: str = "", username: str = "") -> int:
        """Return count of grouped successful push history display records."""
        assert self.conn is not None
        where, params = self._push_history_filter(group_id, username)
        row = self.conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM (
                SELECT 1
                FROM push_history
                {where}
                GROUP BY group_id, username, status_id, source, original_link
            ) AS grouped_history
            """,
            params,
        ).fetchone()
        return int(row["count"] if row is not None else 0)

    def get_push_history_group_summaries(self) -> list[PushHistoryGroupSummary]:
        """Return successful push history counts grouped by stable group id."""
        assert self.conn is not None
        rows = self.conn.execute(
            """
            SELECT
                group_id,
                COUNT(*) AS record_count,
                COUNT(DISTINCT username) AS user_count,
                MAX(pushed_at) AS latest_pushed_at
            FROM push_history
            GROUP BY group_id
            ORDER BY latest_pushed_at DESC, group_id ASC
            """
        ).fetchall()
        return [
            PushHistoryGroupSummary(
                group_id=str(row["group_id"]),
                record_count=int(row["record_count"] or 0),
                user_count=int(row["user_count"] or 0),
                latest_pushed_at=int(row["latest_pushed_at"] or 0),
            )
            for row in rows
        ]

    @staticmethod
    def _push_history_filter(
        group_id: str = "",
        username: str = "",
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        normalized_group_id = normalize_stable_group_id(group_id) if group_id else ""
        username_query = str(username or "").strip().lstrip("@")
        if normalized_group_id:
            clauses.append("group_id = ?")
            params.append(normalized_group_id)
        if username_query:
            escaped_username = (
                username_query.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            clauses.append("username LIKE ? ESCAPE '\\' COLLATE NOCASE")
            params.append(f"%{escaped_username}%")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        return where, params

    def get_push_history_record(self, record_id: int) -> PushHistoryRecord | None:
        """Return one push history record by id."""
        assert self.conn is not None
        row = self.conn.execute(
            "SELECT * FROM push_history WHERE id = ?",
            (int(record_id),),
        ).fetchone()
        if row is None:
            return None
        return self._push_history_record_from_row(row)

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
                "media": [
                    {
                        "kind": media.kind,
                        "url": media.url,
                        "duration_seconds": media.duration_seconds,
                    }
                    for media in tweet.media
                    if media.url
                ],
                "media_warnings": tweet.media_warnings,
                "ai_warnings": tweet.ai_warnings,
                "translation": tweet.translation,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _deserialize_tweet(raw_data: str) -> TweetItem:
        try:
            data = json.loads(raw_data)
        except (TypeError, ValueError):
            data = {}
        tweet = TweetItem(
            text=str(data.get("text") or ""),
            link=str(data.get("link") or ""),
            published=str(data.get("published") or ""),
            media=[
                TweetMedia(
                    kind=str(item.get("kind") or ""),
                    url=str(item.get("url") or ""),
                    path=None,
                    duration_seconds=item.get("duration_seconds"),
                )
                for item in data.get("media", [])
                if isinstance(item, dict) and str(item.get("url") or "")
            ],
            media_warnings=[
                str(item)
                for item in data.get("media_warnings", [])
                if str(item)
            ],
            ai_warnings=[
                str(item)
                for item in data.get("ai_warnings", [])
                if str(item)
            ],
            translation=str(data.get("translation") or ""),
        )
        return tweet

    @staticmethod
    def _serialize_delivered_targets(targets: list[str] | tuple[str, ...]) -> str:
        values = [str(item).strip() for item in targets if str(item).strip()]
        return json.dumps(list(dict.fromkeys(values)), ensure_ascii=False)

    @staticmethod
    def _deserialize_delivered_targets(raw_data: str) -> tuple[str, ...]:
        try:
            data = json.loads(raw_data or "[]")
        except (TypeError, ValueError):
            data = []
        if not isinstance(data, list):
            return ()
        return tuple(
            dict.fromkeys(str(item).strip() for item in data if str(item).strip())
        )



    def _push_history_record_from_row(self, row: sqlite3.Row) -> PushHistoryRecord:
        return PushHistoryRecord(
            id=int(row["id"]),
            group_id=str(row["group_id"]),
            username=str(row["username"]),
            status_id=str(row["status_id"]),
            original_link=str(row["original_link"] or ""),
            target_umo=str(row["target_umo"] or ""),
            source=str(row["source"] or ""),
            instance=str(row["instance"] or ""),
            pushed_at=int(row["pushed_at"]),
            tweet=self._deserialize_tweet(row["tweet_data"]),
            delivery_status=self._normalize_delivery_status(row["delivery_status"]),
            delivery_error=str(row["delivery_error"] or ""),
        )

    def _ensure_push_history_delivery_columns(self, cursor: sqlite3.Cursor) -> None:
        if not self._table_exists(cursor, "push_history"):
            return
        columns = self._table_columns(cursor, "push_history")
        for name, statement in PUSH_HISTORY_V6_COLUMN_ADD_STATEMENTS.items():
            if name not in columns:
                cursor.execute(statement)

    @staticmethod
    def _normalize_delivery_status(value: object) -> str:
        status = str(value or "").strip()
        if status in {"success", "partial_failed"}:
            return status
        return "success"

    def migrate_kv_seen_data(
        self,
        grouped_seen_map: dict[str, dict[str, list[str]]],
    ) -> None:
        """从 KV 存储迁移 seen 数据到 SQLite."""
        assert self.conn is not None

        # 检查是否已迁移
        migrated_at = self.get_meta("kv_seen_migrated_at")
        if migrated_at:
            logger.info("[NitterTweets] KV seen 数据已迁移，跳过")
            return

        logger.info("[NitterTweets] 开始迁移 KV seen 数据...")

        try:
            cursor = self.conn.cursor()
            cursor.execute("BEGIN")

            total_users = 0
            total_ids = 0
            now = int(time.time())

            for group_id, seen_map in grouped_seen_map.items():
                normalized_group_id = normalize_stable_group_id(group_id)

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
                f"[NitterTweets] KV seen 数据迁移完成: "
                f"{total_users} users, {total_ids} status IDs"
            )

        except Exception as exc:
            if self.conn:
                self.conn.execute("ROLLBACK")
            logger.error(f"[NitterTweets] KV seen 数据迁移失败: {exc}")
            raise

    def sync_config_groups(self, schedule_groups: list) -> None:
        """从配置同步分组到数据库."""
        assert self.conn is not None

        # 计算配置指纹
        configured_group_ids = {
            normalize_stable_group_id(group.group_id)
            for group in schedule_groups
        }
        if (
            DEFAULT_GROUP_ID in configured_group_ids
            and LEGACY_GLOBAL_GROUP_ID not in configured_group_ids
        ):
            self._migrate_global_group_to_default(self.conn.cursor())

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
            logger.debug("[NitterTweets] 配置分组未变化，跳过同步")
            return

        logger.info("[NitterTweets] 正在同步配置分组到数据库...")

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
                f"[NitterTweets] 已清理 {deleted_seen} 条孤立 seen 推文记录"
            )

        # 更新指纹
        self.set_meta("config_groups_fingerprint", config_fingerprint)

        logger.info(f"[NitterTweets] 已同步 {len(schedule_groups)} 个分组到数据库")


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
    "clear_seen_tweets",
    "delete_group_runtime_data",
    "record_push_history",
    "get_push_history",
    "count_push_history",
    "get_push_history_group_summaries",
    "get_push_history_record",
    "cleanup_orphan_seen_tweets",
    "_migrate_global_group_to_default",
    "migrate_kv_seen_data",
    "sync_config_groups",
):
    setattr(
        SQLiteStorage,
        _method_name,
        _locked_sqlite_method(getattr(SQLiteStorage, _method_name)),
    )
