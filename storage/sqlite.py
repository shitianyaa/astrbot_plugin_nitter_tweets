"""SQLite storage backend for Nitter Tweets plugin."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any

from astrbot.api import logger

try:
    from ..shared import TweetItem, normalize_seen_account_key
    from ..shared.group_ids import (
        DEFAULT_GROUP_ID,
        LEGACY_GLOBAL_GROUP_ID,
        normalize_stable_group_id,
    )
    from .records import PushHistoryGroupSummary, PushHistoryRecord
    from .seen import SEEN_LIMIT_PER_USER
    from .sqlite_schema import (
        PUSH_HISTORY_V6_COLUMN_ADD_STATEMENTS,
        SCAN_ANCHOR_LIMIT,
        SCHEMA_VERSION,
        SQLITE_TABLE_NAMES,
        SQLiteSchemaMixin,
    )
    from .sqlite_serde import SQLiteSerdeMixin
except ImportError:
    from shared import TweetItem, normalize_seen_account_key
    from shared.group_ids import (
        DEFAULT_GROUP_ID,
        LEGACY_GLOBAL_GROUP_ID,
        normalize_stable_group_id,
    )
    from storage.records import PushHistoryGroupSummary, PushHistoryRecord
    from storage.seen import SEEN_LIMIT_PER_USER
    from storage.sqlite_schema import (  # noqa: F401  拆分前定义于此，保留再导出
        PUSH_HISTORY_V6_COLUMN_ADD_STATEMENTS,
        SCAN_ANCHOR_LIMIT,
        SCHEMA_VERSION,
        SQLITE_TABLE_NAMES,
        SQLiteSchemaMixin,
    )
    from storage.sqlite_serde import SQLiteSerdeMixin

ORPHAN_SEEN_RETENTION_DAYS = 30


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


class SQLiteStorage(SQLiteSchemaMixin, SQLiteSerdeMixin):
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
            connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            self.conn = connection
            try:
                await asyncio.to_thread(self._init_schema)
            except BaseException:
                # Schema checks/migrations can fail before the first usable
                # connection is established.  Drop the failed handle so a
                # later lifecycle retry opens a fresh connection instead of
                # treating the half-initialized one as healthy.
                with self._conn_lock:
                    if self.conn is connection:
                        try:
                            connection.rollback()
                        except sqlite3.Error:
                            pass
                        try:
                            connection.close()
                        finally:
                            self.conn = None
                raise

    def close(self) -> None:
        """关闭数据库连接."""
        with self._conn_lock:
            if self.conn:
                self.conn.close()
                self.conn = None

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
        normalized_usernames = list(
            dict.fromkeys(
                normalized
                for u in usernames
                if (normalized := normalize_seen_account_key(u))
            )
        )

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

        rows = self.conn.execute("SELECT * FROM groups ORDER BY group_id").fetchall()

        groups = []
        for row in rows:
            groups.append(
                {
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
                }
            )

        return groups

    def get_seen_ids(self, group_id: str, username: str) -> list[str]:
        """获取指定分组和用户的已见推文 ID 列表."""
        assert self.conn is not None

        normalized_group_id = normalize_stable_group_id(group_id)
        normalized_username = normalize_seen_account_key(username)

        if not normalized_username:
            return []

        rows = self.conn.execute(
            """
            SELECT status_id FROM seen_tweets
            WHERE group_id = ? AND username = ?
            ORDER BY seen_at DESC, rowid DESC
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
        normalized_username = normalize_seen_account_key(username)

        if not normalized_username or not status_ids:
            return

        now = int(time.time())

        # 批量插入或更新时间戳（REPLACE = DELETE + INSERT）。输入列表是
        # newest-first，因此反向写入，让同秒记录按 rowid DESC 读取时仍
        # 保持原顺序，同时保证后续调用写入的新 ID 不会被限额清理误删。
        self.conn.executemany(
            """
            REPLACE INTO seen_tweets (group_id, username, status_id, seen_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (normalized_group_id, normalized_username, sid, now)
                for sid in reversed(status_ids)
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
                  ORDER BY seen_at DESC, rowid DESC
                  LIMIT ?
              )
            """,
            (
                normalized_group_id,
                normalized_username,
                normalized_group_id,
                normalized_username,
                SEEN_LIMIT_PER_USER,
            ),
        )

    def get_group_seen_map(self, group_id: str) -> dict[str, list[str]]:
        """获取指定分组的所有用户 seen map."""
        assert self.conn is not None

        normalized_group_id = normalize_stable_group_id(group_id)

        rows = self.conn.execute(
            """
            SELECT username, status_id FROM seen_tweets
            WHERE group_id = ?
            ORDER BY username, seen_at DESC, rowid DESC
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

    def get_group_scan_watermarks(self, group_id: str) -> dict[str, list[str]]:
        """获取分组中已初始化账号的最近扫描基准组。"""
        assert self.conn is not None

        normalized_group_id = normalize_stable_group_id(group_id)
        rows = self.conn.execute(
            """
            SELECT username, status_ids
            FROM scan_watermarks
            WHERE group_id = ? AND initialized = 1
            ORDER BY username
            """,
            (normalized_group_id,),
        ).fetchall()
        return {str(row[0]): self._decode_scan_anchor_ids(row[1]) for row in rows}

    def set_scan_watermark(
        self,
        group_id: str,
        username: str,
        status_ids: list[str] | str | None = None,
    ) -> None:
        """设置一个分组账号的最近扫描基准组并标记为已初始化。"""
        assert self.conn is not None

        normalized_group_id = normalize_stable_group_id(group_id)
        normalized_username = normalize_seen_account_key(username)
        if not normalized_username:
            return

        normalized_status_ids = self._normalize_scan_anchor_ids(status_ids)
        self.conn.execute(
            """
            INSERT INTO scan_watermarks
            (group_id, username, initialized, status_ids, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(group_id, username) DO UPDATE SET
                initialized = 1,
                status_ids = excluded.status_ids,
                updated_at = excluded.updated_at
            """,
            (
                normalized_group_id,
                normalized_username,
                json.dumps(normalized_status_ids, ensure_ascii=False),
                int(time.time()),
            ),
        )

    def clear_seen_tweets(self, group_id: str | None = None) -> int:
        """清理 seen 记录；group_id 为空时清理全部分组."""
        assert self.conn is not None

        if group_id:
            normalized_group_id = normalize_stable_group_id(group_id)
            cursor = self.conn.execute(
                "DELETE FROM seen_tweets WHERE group_id = ?",
                (normalized_group_id,),
            )
            self.conn.execute(
                "DELETE FROM scan_watermarks WHERE group_id = ?",
                (normalized_group_id,),
            )
        else:
            cursor = self.conn.execute("DELETE FROM seen_tweets")
            self.conn.execute("DELETE FROM scan_watermarks")
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
            "scan_watermarks_deleted": 0,
            "push_history_deleted": 0,
        }
        summary["seen_deleted"] = int(
            self.conn.execute(
                "DELETE FROM seen_tweets WHERE group_id = ?",
                (normalized_group_id,),
            ).rowcount
            or 0
        )
        summary["scan_watermarks_deleted"] = int(
            self.conn.execute(
                "DELETE FROM scan_watermarks WHERE group_id = ?",
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
        """Record one successful or partially delivered tweet/target pair."""
        assert self.conn is not None
        normalized_group_id = normalize_stable_group_id(group_id)
        normalized_username = (
            normalize_seen_account_key(username) or str(username or "").strip()
        )
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
        """Return recent successful and partially delivered push history records."""
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
        """Return count of grouped successful and partial push history records."""
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
        """Return successful and partial push history counts by stable group id."""
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
        """清理长期不在订阅配置中的 seen 和扫描水位记录."""
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
        self.conn.execute(
            """
            DELETE FROM scan_watermarks
            WHERE updated_at < ?
              AND NOT EXISTS (
                  SELECT 1 FROM group_users
                  WHERE group_users.group_id = scan_watermarks.group_id
                    AND group_users.username = scan_watermarks.username
              )
            """,
            (cutoff,),
        )
        return int(cursor.rowcount or 0)

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
                    normalized_username = normalize_seen_account_key(username)
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
                                for sid in reversed(limited_ids)
                                if sid
                            ],
                        )
                        total_users += 1
                        total_ids += len(limited_ids)

            # KV 导入发生在 schema v8 迁移之后，因此为新导入的 seen
            # 同步建立扫描水位，避免首次启动后重复初始化账号。
            self._backfill_scan_watermarks(cursor)

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
            normalize_stable_group_id(group.group_id) for group in schedule_groups
        }
        if (
            DEFAULT_GROUP_ID in configured_group_ids
            and LEGACY_GLOBAL_GROUP_ID not in configured_group_ids
        ):
            self._migrate_global_group_to_default(self.conn.cursor())

        fingerprint_data = []
        for group in schedule_groups:
            account_keys = list(
                getattr(group, "account_keys", None) or getattr(group, "users", [])
            )
            fingerprint_data.append(
                {
                    "group_id": group.group_id,
                    "name": group.name,
                    "enabled": group.enabled,
                    "check_on_startup": group.check_on_startup,
                    "interval_check_enabled": group.interval_check_enabled,
                    "check_interval_minutes": group.check_interval_minutes,
                    "daily_check_enabled": group.daily_check_enabled,
                    "daily_check_times": group.daily_check_times,
                    "scheduled_fetch_limit": group.scheduled_fetch_limit,
                    "send_target_interval": group.send_target_interval,
                    "send_user_interval": group.send_user_interval,
                    "notify_no_updates": group.notify_no_updates,
                    "aliases": sorted(group.aliases),
                    # Tag groups use q:<casefold query> as their runtime account
                    # key.  Include the effective keys so query edits refresh the
                    # active-subscription table and orphan cleanup remains safe.
                    "account_keys": sorted(account_keys),
                    "targets": sorted(group.targets),
                }
            )

        config_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_data, sort_keys=True).encode()
        ).hexdigest()[:32]  # 128 bits for lower collision risk

        stored_fingerprint = self.get_meta("config_groups_fingerprint")

        if stored_fingerprint == config_fingerprint:
            logger.debug("[NitterTweets] 配置分组未变化，跳过同步")
            return

        logger.info("[NitterTweets] 正在同步配置分组到数据库...")

        for group in schedule_groups:
            account_keys = list(
                getattr(group, "account_keys", None) or getattr(group, "users", [])
            )
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
            self.set_group_users(group.group_id, account_keys)

            # 同步推送目标
            self.set_group_targets(group.group_id, group.targets)

        deleted_seen = self.cleanup_orphan_seen_tweets()
        if deleted_seen:
            logger.info(f"[NitterTweets] 已清理 {deleted_seen} 条孤立 seen 推文记录")

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
    "get_group_scan_watermarks",
    "set_scan_watermark",
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
