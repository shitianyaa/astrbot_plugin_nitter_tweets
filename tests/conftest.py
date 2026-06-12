from __future__ import annotations

import sys
import types

# ── astrbot mock (needed by group_config imports) ──
if "astrbot.api" not in sys.modules:
    astrbot_mod = types.ModuleType("astrbot")
    api_mod = types.ModuleType("astrbot.api")

    class _Logger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass

    api_mod.logger = _Logger()
    sys.modules["astrbot"] = astrbot_mod
    sys.modules["astrbot.api"] = api_mod

from group_config import GroupConfig, PushTargetParseResult, WatchUsersInfo


def make_group_config(**overrides) -> GroupConfig:
    """Create a GroupConfig with sensible test defaults."""
    return GroupConfig(
        group_id="default",
        name="默认分组",
        watch_users_info=WatchUsersInfo(raw_count=0),
        push_targets_info=PushTargetParseResult(),
        **overrides,
    )
