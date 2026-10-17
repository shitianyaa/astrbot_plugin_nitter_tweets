"""P-03 registration/reload proofs using AstrBot's actual tool manager and Context."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.provider.func_tool_manager import FunctionToolManager, sp
from astrbot.core.star.context import Context

from command_handlers.llm_tools import (
    NITTER_TOOL_NAMES,
    build_llm_tools,
    register_llm_tools,
    unregister_llm_tools,
)


@pytest.fixture
def runtime(monkeypatch):
    manager = FunctionToolManager()
    context = Context.__new__(Context)
    context.provider_manager = SimpleNamespace(llm_tools=manager)
    persistent = []

    def get(key, default=None, **_kwargs):
        assert key == "inactivated_llm_tools"
        return list(persistent)

    def put(key, values, **_kwargs):
        assert key == "inactivated_llm_tools"
        persistent[:] = list(values)

    async def get_async(scope, scope_id, key, default=None):
        assert (scope, scope_id, key) == ("global", "global", "inactivated_llm_tools")
        return list(persistent)

    async def put_async(scope, scope_id, key, values):
        assert (scope, scope_id, key) == ("global", "global", "inactivated_llm_tools")
        persistent[:] = list(values)

    monkeypatch.setattr(sp, "get", get)
    monkeypatch.setattr(sp, "put", put)
    monkeypatch.setattr(sp, "get_async", get_async)
    monkeypatch.setattr(sp, "put_async", put_async)
    return context, manager, persistent


def make_plugin(context, enabled=True):
    return SimpleNamespace(
        context=context,
        config={"llm_tools_enabled": enabled},
        fetch_backend="mix",
        nitter=None,
        fxtwitter=None,
        _llm_tools=(),
        _llm_query_controller=None,
    )


def test_default_off_does_not_install_tools_or_break_unload(runtime):
    ctx, manager, _ = runtime
    p = make_plugin(ctx, enabled=False)
    register_llm_tools(p)
    assert all(manager.get_func(name) is None for name in NITTER_TOOL_NAMES)
    unregister_llm_tools(p)
    assert manager.func_list == []


def test_actual_context_registers_exactly_four_tools_idempotently(runtime):
    ctx, manager, _ = runtime
    p = make_plugin(ctx)
    register_llm_tools(p)
    assert len(p._llm_tools) == 4
    assert all(isinstance(t, FunctionTool) for t in p._llm_tools)
    assert set(NITTER_TOOL_NAMES) == {t.name for t in manager.func_list}
    assert all(t.handler_module_path for t in p._llm_tools)
    original = list(p._llm_tools)
    register_llm_tools(p)
    assert list(p._llm_tools) == original
    assert len(manager.func_list) == 4
    unregister_llm_tools(p)
    assert not manager.func_list
    assert all(t.plugin is None for t in original)


def test_foreign_name_collision_does_not_replace_tool(runtime):
    ctx, manager, _ = runtime
    foreign = build_llm_tools(make_plugin(ctx))[0]
    manager.func_list.append(foreign)
    p = make_plugin(ctx)
    with pytest.raises(RuntimeError, match="already registered"):
        register_llm_tools(p)
    assert manager.get_func(foreign.name) is foreign
    assert len(manager.func_list) == 1


def test_unregister_never_removes_other_owner_replacement(runtime):
    ctx, manager, _ = runtime
    p = make_plugin(ctx)
    register_llm_tools(p)
    owned = p._llm_tools[0]
    replacement = build_llm_tools(make_plugin(ctx))[0]
    manager.remove_func(owned.name)
    manager.func_list.append(replacement)
    unregister_llm_tools(p)
    assert manager.get_func(owned.name) is replacement
    assert owned.plugin is None
    assert len(manager.func_list) == 1


@pytest.mark.asyncio
async def test_inactive_webui_setting_survives_targeted_reload(runtime):
    ctx, manager, persistent = runtime
    p = make_plugin(ctx)
    register_llm_tools(p)
    toolname = NITTER_TOOL_NAMES[0]
    assert await manager.deactivate_llm_tool_async(toolname)
    assert persistent == [toolname]
    assert manager.get_func(toolname).active is False
    unregister_llm_tools(p)

    reloaded = make_plugin(ctx)
    register_llm_tools(reloaded)
    assert manager.get_func(toolname).active is False
    assert all(manager.get_func(name).active for name in NITTER_TOOL_NAMES[1:])
    assert await manager.activate_llm_tool_async(toolname, {}) is True
    assert not persistent
    unregister_llm_tools(reloaded)

    last = make_plugin(ctx)
    register_llm_tools(last)
    assert manager.get_func(toolname).active is True
    unregister_llm_tools(last)


def test_partial_registration_failure_removes_only_own_added_tools(runtime):
    ctx, manager, _ = runtime
    real_add = ctx.add_llm_tools

    def failing_add(*tools):
        real_add(tools[0])
        raise RuntimeError("failed after first tool")

    ctx.add_llm_tools = failing_add
    p = make_plugin(ctx)
    with pytest.raises(RuntimeError, match="failed after first"):
        register_llm_tools(p)
    assert manager.func_list == []
    assert not p._llm_tools
