from __future__ import annotations

import asyncio
import datetime as dt
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astrbot.api import logger

try:
    from .utils import clamp_float, clamp_int, normalize_username
except ImportError:
    from utils import clamp_float, clamp_int, normalize_username


try:
    CN_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    CN_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")


KV_KEY_SEEN = "nitter_seen_status_ids"
POLL_SECONDS = 30
SEEN_LIMIT_PER_USER = 100


class NitterTweetScheduler:
    def __init__(self, owner, context, config, nitter, media, sender, translator):
        self.owner = owner
        self.context = context
        self.config = config
        self.nitter = nitter
        self.media = media
        self.sender = sender
        self.translator = translator
        self._task: asyncio.Task | None = None
        self._last_interval_slot: int | None = None
        self._daily_slots: set[str] = set()

    def start(self, reason: str = "") -> None:
        if self._task is not None and not self._task.done():
            return
        try:
            self._task = asyncio.create_task(self._loop())
            logger.info(f"[NitterTweets] scheduler started ({reason})")
        except RuntimeError:
            logger.debug(
                f"[NitterTweets] no running event loop during {reason}, scheduler waits"
            )

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            try:
                if self.config.get("schedule_enabled", False):
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[NitterTweets] scheduler error: {exc}", exc_info=True)
                await asyncio.sleep(60)
                continue
            await asyncio.sleep(POLL_SECONDS)

    async def _tick(self) -> None:
        now = dt.datetime.now(CN_TZ)
        reasons: list[str] = []

        if self.config.get("interval_check_enabled", True):
            interval_minutes = clamp_int(
                self.config.get("check_interval_minutes", 30), 1, 1440
            )
            slot = int(now.timestamp() // (interval_minutes * 60))
            if slot != self._last_interval_slot:
                self._last_interval_slot = slot
                reasons.append(f"interval:{interval_minutes}m")

        if self.config.get("daily_check_enabled", False):
            for hhmm in self._parse_daily_times():
                hour, minute = hhmm
                if now.hour == hour and now.minute == minute:
                    slot_key = f"{now.date().isoformat()}:{hour:02d}:{minute:02d}"
                    if slot_key not in self._daily_slots:
                        self._daily_slots.add(slot_key)
                        reasons.append(f"daily:{hour:02d}:{minute:02d}")

            if len(self._daily_slots) > 256:
                today = now.date().isoformat()
                self._daily_slots = {
                    slot for slot in self._daily_slots if slot.startswith(today)
                }

        if reasons:
            logger.info(f"[NitterTweets] scheduled check triggered: {', '.join(reasons)}")
            await self.run_check()

    async def run_check(self) -> None:
        users = self._watch_users()
        if not users:
            logger.debug("[NitterTweets] no watch_users configured, skip scheduled check")
            return

        targets = self._push_targets()
        if not targets:
            logger.debug("[NitterTweets] no push_targets configured, skip scheduled check")
            return

        seen_map = await self._get_seen_map()
        fetch_limit = clamp_int(self.config.get("scheduled_fetch_limit", 5), 1, 20)
        target_interval = clamp_float(
            self.config.get("send_target_interval", 1.5), 0.0, 60.0
        )
        user_interval = clamp_float(
            self.config.get("send_user_interval", 2.0), 0.0, 60.0
        )

        for user_index, username in enumerate(users):
            try:
                instance, tweets = await self.nitter.fetch_tweets(username, fetch_limit)
            except Exception as exc:
                logger.warning(f"[NitterTweets] scheduled fetch @{username} failed: {exc}")
                continue

            tweets = [tweet for tweet in tweets if tweet.status_id]
            if not tweets:
                continue

            fetched_ids = [tweet.status_id for tweet in tweets]
            seen_ids = seen_map.get(username)

            if not isinstance(seen_ids, list):
                seen_map[username] = fetched_ids[:SEEN_LIMIT_PER_USER]
                await self._put_seen_map(seen_map)
                logger.info(
                    f"[NitterTweets] initialized @{username} with {len(fetched_ids)} seen tweets"
                )
                continue

            seen_set = set(str(item) for item in seen_ids)
            new_tweets = [
                tweet for tweet in tweets if tweet.status_id not in seen_set
            ]

            if new_tweets:
                new_tweets.reverse()
                await self.translator.attach_translations(new_tweets, targets[0])
                await self.media.attach_media(new_tweets)
                success = 0
                for target_index, umo in enumerate(targets):
                    try:
                        if await self.sender.send_to_umo(
                            self.context, umo, username, instance, new_tweets
                        ):
                            success += 1
                    except Exception as exc:
                        logger.warning(
                            f"[NitterTweets] scheduled push @{username} to {umo} failed: {exc}"
                        )
                    if target_index < len(targets) - 1 and target_interval > 0:
                        await asyncio.sleep(target_interval)
                logger.info(
                    f"[NitterTweets] pushed @{username} {len(new_tweets)} new tweets "
                    f"to {success}/{len(targets)} targets"
                )

            seen_map[username] = self._merge_seen_ids(fetched_ids, seen_ids)
            await self._put_seen_map(seen_map)

            if user_index < len(users) - 1 and user_interval > 0:
                await asyncio.sleep(user_interval)

    async def _get_seen_map(self) -> dict[str, list[str]]:
        value = await self.owner.get_kv_data(KV_KEY_SEEN, {})
        if not isinstance(value, dict):
            return {}
        result: dict[str, list[str]] = {}
        for key, ids in value.items():
            username = normalize_username(str(key))
            if not username or not isinstance(ids, list):
                continue
            result[username] = [str(item) for item in ids if item]
        return result

    async def _put_seen_map(self, seen_map: dict[str, list[str]]) -> None:
        await self.owner.put_kv_data(KV_KEY_SEEN, seen_map)

    @staticmethod
    def _merge_seen_ids(new_ids: list[str], old_ids: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for status_id in [*new_ids, *[str(item) for item in old_ids]]:
            if not status_id or status_id in seen:
                continue
            seen.add(status_id)
            merged.append(status_id)
            if len(merged) >= SEEN_LIMIT_PER_USER:
                break
        return merged

    def _watch_users(self) -> list[str]:
        raw_users = self.config.get("watch_users", []) or []
        if isinstance(raw_users, str):
            raw_users = re.split(r"[\n,，]+", raw_users)
        users: list[str] = []
        seen: set[str] = set()
        for raw in raw_users:
            username = normalize_username(str(raw))
            if username and username not in seen:
                seen.add(username)
                users.append(username)
        return users

    def _push_targets(self) -> list[str]:
        default_platform = self._get_platform()
        raw_targets = self.config.get("push_targets", []) or []
        targets: list[str] = []
        seen: set[str] = set()
        for raw in raw_targets:
            if not isinstance(raw, str):
                continue
            target = raw.strip().replace("：", ":")
            if not target:
                continue
            umo = self._parse_target_to_umo(target, default_platform)
            if umo is None:
                logger.warning(f"[NitterTweets] invalid push target: {raw!r}")
                continue
            if umo not in seen:
                seen.add(umo)
                targets.append(umo)
        return targets

    def _get_platform(self) -> str:
        configured = (self.config.get("platform_id", "") or "").strip()
        if configured:
            return configured
        try:
            all_platforms = self.context.get_all_platforms()
            if not all_platforms:
                return "aiocqhttp"
            if isinstance(all_platforms, dict):
                return next(iter(all_platforms.keys()))
            first = all_platforms[0]
            for attr in ("platform_name", "name"):
                value = getattr(first, attr, None)
                if isinstance(value, str) and value:
                    return value
            meta = getattr(first, "meta", None)
            if callable(meta):
                value = getattr(meta(), "name", None)
                if isinstance(value, str) and value:
                    return value
        except Exception as exc:
            logger.debug(f"[NitterTweets] platform auto-detect failed: {exc}")
        return "aiocqhttp"

    @staticmethod
    def _parse_target_to_umo(target: str, default_platform: str) -> str | None:
        if ":GroupMessage:" in target or ":FriendMessage:" in target:
            return target

        parts = target.split(":")
        if len(parts) == 2:
            kind, ident = parts[0].strip().lower(), parts[1].strip()
            if not ident:
                return None
            if kind == "group":
                return f"{default_platform}:GroupMessage:{ident}"
            if kind == "private":
                return f"{default_platform}:FriendMessage:{ident}"
            return None

        if len(parts) == 3:
            platform, kind, ident = (
                parts[0].strip(),
                parts[1].strip().lower(),
                parts[2].strip(),
            )
            if not platform or not ident:
                return None
            if kind == "group":
                return f"{platform}:GroupMessage:{ident}"
            if kind == "private":
                return f"{platform}:FriendMessage:{ident}"
            return None

        if len(parts) == 1 and target.isdigit():
            return f"{default_platform}:GroupMessage:{target}"
        return None

    def _parse_daily_times(self) -> list[tuple[int, int]]:
        raw_times = self.config.get("daily_check_times", []) or []
        if isinstance(raw_times, str):
            raw_times = re.split(r"[\n,，]+", raw_times)

        times: list[tuple[int, int]] = []
        for raw in raw_times:
            value = str(raw).strip().replace("：", ":")
            if not value:
                continue
            try:
                hour_s, minute_s = value.split(":", 1)
                hour, minute = int(hour_s), int(minute_s)
            except (TypeError, ValueError):
                logger.warning(f"[NitterTweets] invalid daily_check_times entry: {raw!r}")
                continue
            if 0 <= hour < 24 and 0 <= minute < 60:
                times.append((hour, minute))
            else:
                logger.warning(f"[NitterTweets] daily_check_times out of range: {raw!r}")
        return times
