"""Dashboard sandbox, wiring, and source contracts without behavior coverage."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Dashboard JS 已按分节拆为多文件（classic script 按序加载，见 index.html）；
# 源码字符串断言统一读「按加载顺序拼接」的全文，行为与拆分前的单文件等价。
DASHBOARD_JS_FILES = (
    "core.js",
    "ui.js",
    "data.js",
    "groups.js",
    "views.js",
    "config.js",
    "boot.js",
)


def _dashboard_js_source() -> str:
    return "\n".join(
        (ROOT / "pages" / "dashboard" / name).read_text(encoding="utf-8")
        for name in DASHBOARD_JS_FILES
    )


def test_dashboard_script_tags_match_load_order():
    """index.html 的 <script src> 顺序必须与 DASHBOARD_JS_FILES 一致。

    classic script 的顶层 let/const/function 跨文件共享全局词法环境，
    顺序错乱（boot 提前、core 殿后）在运行时才炸，这里把加载顺序钉死。
    """
    index = (ROOT / "pages" / "dashboard" / "index.html").read_text(encoding="utf-8")
    srcs = re.findall(r'<script src="\./([\w-]+\.js)"></script>', index)
    assert srcs == list(DASHBOARD_JS_FILES)


def test_dashboard_sandbox_does_not_access_local_storage():
    source = _dashboard_js_source()
    index = (ROOT / "pages/dashboard/index.html").read_text(encoding="utf-8")
    # AstrBot Pages uses an opaque origin; accessing localStorage breaks startup.
    for text in (source, index):
        assert not re.search(
            r"localStorage\s*[.\[]|window\s*\[\s*[\"']localStorage[\"']\s*\]", text
        )
    assert '<script src="/api/plugin/page/bridge-sdk.js"></script>' in index


def test_dashboard_guards_busy_actions_and_unsaved_edits():
    source = _dashboard_js_source()
    assert "sheetHasDraftChanges()" in source
    assert "if (state.selectedGroupId === gid) {" in source
    assert "if (sheetOpen) closeSheet({ force: true });" in source
    # Orphan cleanup runs inside an action; nesting withAction would skip it.
    assert (
        'await withAction(() => renderHistoryOrphans(), "检测完成", { reload: false });'
        in source
    )


def test_dashboard_entity_removal_does_not_use_stale_indices():
    source = _dashboard_js_source()
    assert "next.splice(idx, 1);" not in source
    assert "current.filter(x => entityValue(x) !== val)" in source
    assert "current.filter(x => x !== t)" in source


def test_dashboard_preserves_dirty_groups_and_pending_history_filters():
    source = _dashboard_js_source()
    assert (
        'if (view === "groups" && state.groups.some(g => isGroupDirty(g.group_id))) return;'
        in source
    )
    assert (
        "if (state.actionBusy) { state.pendingHistoryApply = true; return; }" in source
    )
    for control in ("historyLimitSelect", "historyGroupSelect"):
        assert (
            f"els.{control}?.onChange?.(() => {{ applyHistoryFilters(); }});" in source
        )


def test_dashboard_log_polling_keeps_cursor_and_failure_fallbacks():
    """日志轮询必须防重复：接口慢于轮询间隔时，两次请求拿到同一批 seq 各自
    concat，同一批日志会在终端里出现两遍（实测 8 条里有 4 条重复）。"""
    source = _dashboard_js_source()

    # 增量去重和会话重启已由 test_dashboard_log_polling 执行验证；
    # 这里保留乱序游标和旧服务端没有 session_id 时的二级兜底。
    assert (
        "state.logsAfterSeq = Math.max(state.logsAfterSeq, ...fresh.map(e => e.seq));"
        in source
    )
    assert "res.next_seq && res.next_seq <= state.logsAfterSeq" in source
    # 跳过的一轮不能算成功，否则「请求比 3s 间隔还慢 + 一直失败」时失败计数
    # 会在 0/1 之间振荡，永远到不了停止阀值
    assert 'generation === logsGeneration && result !== "skipped"' in source


def test_dashboard_overview_recent_pushes_use_own_snapshot():
    """总览「最新推送记录」必须独立取数，不得切历史页快照。

    历史页快照带分组/状态/作者筛选与分页 offset；总览若复用它，用户翻页或加
    筛选后总览仍显示旧行，点开时 openHistoryDetail 在 history.records 里查不到
    该 id 便静默 return——表现为「点击没反应，刷新一下才好」。
    """
    source = _dashboard_js_source()

    # 独立数据通道与独立取数函数
    assert 'recent: ["overview"]' in source
    assert "recentPushes: []" in source
    assert "const RECENT_PUSH_LIMIT = 5;" in source
    assert "async function refreshRecentPushes()" in source
    # 取数不带任何筛选，固定 offset=0（全局最新）
    recent_fn = source.split("async function refreshRecentPushes()", 1)[1].split(
        "\n}", 1
    )[0]
    assert "limit: RECENT_PUSH_LIMIT" in recent_fn
    assert "offset: 0" in recent_fn
    assert "historyGroupId" not in recent_fn
    assert "historyStatus" not in recent_fn
    assert "historyOffset" not in recent_fn
    # 总览渲染不再切历史页快照
    assert "const records = state.recentPushes;" in source
    assert "state.history?.records || []).slice(0, 5)" not in source
    # 详情抽屉两个快照都查：总览点开的行不在 history.records 里
    detail_fn = source.split("function openHistoryDetail(recordId)", 1)[1].split(
        "\n}", 1
    )[0]
    assert "state.history.records" in detail_fn
    assert "state.recentPushes.find" in detail_fn
    # 三处刷新入口都要带上最近推送
    assert "reloadGroupState(), refreshHistoryData(), refreshRecentPushes()" in source
    assert "Promise.all([reloadOverviewData(), refreshRecentPushes()])" in source
    assert (
        "reloadGroupState(), reloadConfigState(), refreshHistoryData(), refreshRecentPushes()"
        in source
    )


def test_dashboard_history_redacts_instance_labels():
    source = _dashboard_js_source()
    assert "function redactInstanceLabel(raw)" in source
    assert "redactInstanceLabel(r.instance)" in source


def test_attention_nav_covers_every_overview_attention_key():
    """总览「需要关注」的每个 key 都要有跳转目标（自带 group_id 的除外）。

    回归背景：ATTENTION_NAV 曾只覆盖 _overview_attention_items 自己产出的 9 个
    key，漏掉它 extend 进来的 _overview_group_diagnostics 聚合条目——那些行
    渲染成不可点，而 CHANGELOG 写的是「均可点击跳转」。
    """
    import ast

    tree = ast.parse(
        (ROOT / "plugin_api" / "api_overview.py").read_text(encoding="utf-8")
    )
    backend_keys = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in {
            "_overview_attention_items",
            "_overview_group_diagnostics",
        }:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Dict):
                continue
            names = {k.value for k in sub.keys if isinstance(k, ast.Constant)}
            consts = {
                k.value: v.value
                for k, v in zip(sub.keys, sub.values)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            }
            # 带 group_id 的条目由 jumpAttention 直达抽屉，不需要进导航表
            if "key" in consts and "group_id" not in names:
                backend_keys.add(consts["key"])

    nav_block = re.search(
        r"const ATTENTION_NAV = \{(.*?)\n\};", _dashboard_js_source(), re.S
    ).group(1)
    nav_keys = set(re.findall(r"^\s*(\w+):\s*\{", nav_block, re.M))

    assert backend_keys, "没解析到后端 attention key，断言本身失效了"
    assert backend_keys <= nav_keys, f"缺少跳转目标：{sorted(backend_keys - nav_keys)}"

    # view=config 的目标必须是 _conf_schema.json 里真实存在的顶层分组键，
    # 否则 typo（如 schedule 打成 schedul）只会静默跳到第一组
    schema_keys = set(
        json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    )
    config_targets = re.findall(
        r'^\s*(\w+):\s*\{ view: "config", group: "(\w+)" \}', nav_block, re.M
    )
    assert config_targets, "没解析到 config 类跳转目标，断言本身失效了"
    for key, group in config_targets:
        assert group in schema_keys, f"{key} 指向不存在的配置分组 {group}"


def test_with_action_drains_pending_history_filter_replay():
    """在途期间被丢弃的历史筛选必须由收尾补跑。

    withAction 与 probeMirror 都自管 actionBusy，两条路径都要收口，
    否则筛选变更被静默吞掉、还会留到下一次动作才意外触发。
    """
    source = _dashboard_js_source()

    assert "function drainPendingHistoryApply() {" in source
    # 只数调用次数会漏掉「调用点不在 finally 里」这种错位。先按函数切块再
    # 看块内的 finally：跨函数匹配的正则会在首个候选失败后向后吞，把
    # probeMirror 的 finally 当成 withAction 的，反而比计数更弱。
    bodies = {
        m.group(1): m.group(2)
        for m in re.finditer(
            r"async function (\w+)\b(.*?)(?=\nasync function |\Z)", source, re.S
        )
    }
    for fn in ("withAction", "probeMirror"):
        body = bodies.get(fn) or ""
        assert "finally {" in body, f"{fn} 没有 finally"
        finally_body = body.split("finally {", 1)[1].split("}", 1)[0]
        assert "drainPendingHistoryApply();" in finally_body, (
            f"{fn} 的 finally 没补跑历史筛选"
        )
