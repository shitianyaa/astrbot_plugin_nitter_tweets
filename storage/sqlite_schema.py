"""SQLite 建表、版本迁移与历史数据回填。

`SQLiteStorage` 的 mixin：只通过 `self` 协作，不 import 宿主类。
加锁仍由 `sqlite.py` 末尾统一的 `_locked_sqlite_method` 包装列表施加。
"""

from __future__ import annotations

import json
import sqlite3
import time

from astrbot.api import logger

try:
    from ..shared.group_ids import DEFAULT_GROUP_ID, LEGACY_GLOBAL_GROUP_ID
except ImportError:
    from shared.group_ids import DEFAULT_GROUP_ID, LEGACY_GLOBAL_GROUP_ID


SCHEMA_VERSION = 9
SCAN_ANCHOR_LIMIT = 20

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


class SQLiteSchemaMixin:
    """schema 初始化与迁移。"""

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

            # scan_watermarks 表：每个分组账号的连续扫描水位和初始化状态
            self._create_scan_watermarks_table(cursor)


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
        if stored_version < 8:
            self._migrate_schema_v8(cursor)
        if stored_version < 9:
            self._migrate_schema_v9(cursor)
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
        # Keep legacy pending/staged tables intact.  The current runtime no
        # longer consumes them, but an upgrade must not destroy operators'
        # unpublished queue or its media before an explicit migration policy
        # has been chosen.
        return

    def _migrate_schema_v8(self, cursor: sqlite3.Cursor) -> None:
        self._create_scan_watermarks_table(cursor)
        self._backfill_scan_watermarks(cursor)

    def _migrate_schema_v9(self, cursor: sqlite3.Cursor) -> None:
        if not self._table_exists(cursor, "scan_watermarks"):
            self._create_scan_watermarks_table(cursor)
            self._backfill_scan_watermarks(cursor)
            return

        columns = {
            str(row[1])
            for row in cursor.execute(
                "PRAGMA table_info(scan_watermarks)"
            ).fetchall()
        }
        if "status_id" not in columns or "status_ids" in columns:
            self._create_scan_watermarks_table(cursor)
            self._backfill_scan_watermarks(cursor)
            return

        cursor.execute("ALTER TABLE scan_watermarks RENAME TO scan_watermarks_v8")
        self._create_scan_watermarks_table(cursor)
        rows = cursor.execute(
            """
            SELECT group_id, username, initialized, status_id, updated_at
            FROM scan_watermarks_v8
            """
        ).fetchall()
        for row in rows:
            anchors = self._normalize_scan_anchor_ids([row[3]])
            cursor.execute(
                """
                INSERT INTO scan_watermarks
                (group_id, username, initialized, status_ids, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(row[0]),
                    str(row[1]),
                    int(row[2] or 0),
                    json.dumps(anchors, ensure_ascii=False),
                    int(row[4] or 0),
                ),
            )
        cursor.execute("DROP TABLE scan_watermarks_v8")
        self._create_scan_watermarks_table(cursor)
        self._backfill_scan_watermarks(cursor)

    @staticmethod
    def _create_scan_watermarks_table(cursor: sqlite3.Cursor) -> None:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scan_watermarks (
                group_id TEXT NOT NULL,
                username TEXT NOT NULL,
                initialized INTEGER NOT NULL DEFAULT 0,
                status_ids TEXT NOT NULL DEFAULT '[]',
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (group_id, username)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scan_watermarks_group_user
            ON scan_watermarks(group_id, username)
        """)

    @classmethod
    def _backfill_scan_watermarks(cls, cursor: sqlite3.Cursor) -> None:
        """Backfill a recent anchor window from existing seen IDs."""
        if not cls._table_exists(cursor, "seen_tweets"):
            return

        rows = cursor.execute(
            """
            SELECT group_id, username, MAX(seen_at) AS updated_at
            FROM seen_tweets
            GROUP BY group_id, username
            """
        ).fetchall()
        for row in rows:
            group_id = str(row[0])
            username = str(row[1])
            seen_rows = cursor.execute(
                """
                SELECT status_id FROM seen_tweets
                WHERE group_id = ? AND username = ?
                ORDER BY seen_at DESC, rowid DESC
                LIMIT ?
                """,
                (group_id, username, SCAN_ANCHOR_LIMIT),
            ).fetchall()
            seen_anchors = cls._normalize_scan_anchor_ids(
                [row[0] for row in seen_rows]
            )
            existing = cursor.execute(
                """
                SELECT initialized, status_ids, updated_at
                FROM scan_watermarks
                WHERE group_id = ? AND username = ?
                """,
                (group_id, username),
            ).fetchone()
            if existing is not None:
                anchors = cls._normalize_scan_anchor_ids(
                    [*cls._decode_scan_anchor_ids(existing[1]), *seen_anchors]
                )
                updated_at = max(int(row[2] or 0), int(existing[2] or 0))
                cursor.execute(
                    """
                    UPDATE scan_watermarks
                    SET initialized = ?, status_ids = ?, updated_at = ?
                    WHERE group_id = ? AND username = ?
                    """,
                    (
                        1,
                        json.dumps(anchors, ensure_ascii=False),
                        updated_at,
                        group_id,
                        username,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO scan_watermarks
                    (group_id, username, initialized, status_ids, updated_at)
                    VALUES (?, ?, 1, ?, ?)
                    """,
                    (
                        group_id,
                        username,
                        json.dumps(seen_anchors, ensure_ascii=False),
                        int(row[2] or 0),
                    ),
                )

    @staticmethod
    def _decode_scan_anchor_ids(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        text = str(value or "").strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return [text]
        if not isinstance(decoded, list):
            return [text]
        return [str(item) for item in decoded]

    @classmethod
    def _normalize_scan_anchor_ids(cls, values: object) -> list[str]:
        if isinstance(values, (str, bytes)) or values is None:
            raw_values = cls._decode_scan_anchor_ids(values)
        else:
            try:
                raw_values = list(values)
            except TypeError:
                raw_values = [values]
        return list(
            dict.fromkeys(
                str(value).strip()
                for value in raw_values
                if str(value or "").strip().isdigit()
            )
        )[:SCAN_ANCHOR_LIMIT]

    @staticmethod
    def _max_numeric_status_id(first: object, second: object) -> str | None:
        values = [str(value).strip() for value in (first, second) if value]
        numeric = [value for value in values if value.isdigit()]
        if numeric:
            return max(numeric, key=lambda value: (len(value), value))
        return values[0] if values else None

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
        self._merge_scan_watermarks(cursor, legacy_id, default_id)
        if self._table_exists(cursor, "push_history"):
            cursor.execute(
                "UPDATE push_history SET group_id = ? WHERE group_id = ?",
                (default_id, legacy_id),
            )

    @classmethod
    def _merge_scan_watermarks(
        cls,
        cursor: sqlite3.Cursor,
        legacy_id: str,
        default_id: str,
    ) -> None:
        if not cls._table_exists(cursor, "scan_watermarks"):
            return

        legacy_rows = cursor.execute(
            """
            SELECT username, initialized, status_ids, updated_at
            FROM scan_watermarks
            WHERE group_id = ?
            """,
            (legacy_id,),
        ).fetchall()
        for row in legacy_rows:
            username = str(row[0])
            target = cursor.execute(
                """
                SELECT initialized, status_ids, updated_at
                FROM scan_watermarks
                WHERE group_id = ? AND username = ?
                """,
                (default_id, username),
            ).fetchone()
            if target is None:
                cursor.execute(
                    """
                    UPDATE scan_watermarks
                    SET group_id = ?
                    WHERE group_id = ? AND username = ?
                    """,
                    (default_id, legacy_id, username),
                )
                continue

            legacy_anchors = cls._decode_scan_anchor_ids(row[2])
            target_anchors = cls._decode_scan_anchor_ids(target[1])
            if int(row[3] or 0) >= int(target[2] or 0):
                anchors = cls._normalize_scan_anchor_ids(
                    [*legacy_anchors, *target_anchors]
                )
            else:
                anchors = cls._normalize_scan_anchor_ids(
                    [*target_anchors, *legacy_anchors]
                )
            cursor.execute(
                """
                UPDATE scan_watermarks
                SET initialized = ?, status_ids = ?, updated_at = ?
                WHERE group_id = ? AND username = ?
                """,
                (
                    1 if bool(row[1]) or bool(target[0]) else 0,
                    json.dumps(anchors, ensure_ascii=False),
                    max(int(row[3] or 0), int(target[2] or 0)),
                    default_id,
                    username,
                ),
            )
            cursor.execute(
                """
                DELETE FROM scan_watermarks
                WHERE group_id = ? AND username = ?
                """,
                (legacy_id, username),
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
