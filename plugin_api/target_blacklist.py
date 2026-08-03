from __future__ import annotations

from typing import Any

try:
    from ..config import config_set
    from ..config.subscriptions import save_subscription_config
except ImportError:
    from config import config_set
    from config.subscriptions import save_subscription_config


class WebAPITargetBlacklistMixin:
    """目标级作者黑名单的 WebUI API。"""

    async def build_target_blacklists(self) -> dict[str, Any]:
        info = self.scheduler.config_reader.parse_target_blocked_users()
        return self._ok(
            target_blacklists=[
                {
                    "target_umo": target,
                    "blocked_users": list(users),
                    "blocked_count": len(users),
                }
                for target, users in sorted(info.blocked_users.items())
            ],
            invalid_targets=list(info.invalid_targets),
            invalid_users={
                target: list(users) for target, users in info.invalid_users.items()
            },
        )

    async def update_target_blacklist(self, data: dict[str, Any]) -> dict[str, Any]:
        reader = self.scheduler.config_reader
        raw_target = str(data.get("target_umo") or data.get("target") or "")
        target = reader.parse_target_to_umo(
            raw_target.strip().replace("：", ":"), reader.platform()
        )
        if not target:
            return self._error("推送目标格式无效，请填写完整 UMO")

        raw_users = data.get("blocked_users", data.get("users", []))
        users: list[str] = []
        invalid: list[str] = []
        seen: set[str] = set()
        for raw_user in reader.config_list(raw_users):
            parsed = reader.parse_watch_users([raw_user])
            if parsed.invalid_entries:
                invalid.extend(parsed.invalid_entries)
                continue
            for username in parsed.users:
                key = username.casefold()
                if key not in seen:
                    seen.add(key)
                    users.append(username)
        if invalid:
            return self._error("无效博主用户名：" + ", ".join(invalid[:5]))

        async with self.scheduler._target_blacklist_lock:
            info = reader.parse_target_blocked_users()
            previous = {key: list(value) for key, value in info.blocked_users.items()}
            next_mapping = {key: list(value) for key, value in previous.items()}
            if users:
                next_mapping[target] = users
            else:
                next_mapping.pop(target, None)
            config_set(self.config, "target_blocked_users", next_mapping)
            save_error = save_subscription_config(self.config)
            if save_error:
                config_set(self.config, "target_blocked_users", previous)
                return self._error(f"配置保存失败：{save_error}")
        return self._ok(target_umo=target, blocked_users=users)
