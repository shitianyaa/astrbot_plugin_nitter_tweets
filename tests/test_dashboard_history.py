"""Dashboard history presentation and host/preview theme behavior."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_node(script):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for dashboard behavior checks")
    result = subprocess.run(
        [node],
        input=script,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_history_labels_and_statuses():
    source = (ROOT / "pages/dashboard/views.js").read_text(encoding="utf-8")
    run_node(
        r"""
const assert = require('node:assert/strict');
const state = { historySelection: new Set() };
function h(tag, props = {}, children = []) { return { tag, props, children: children.filter(Boolean) }; }
function relativeTime() { return '刚刚'; }
function formatDateTime() { return '2026-11-06 00:30:26'; }
function svgIcon() { return ''; }
function find(node, predicate) {
  if (predicate(node)) return node;
  for (const child of node.children || []) { const match = find(child, predicate); if (match) return match; }
}
"""
        + source
        + r"""
assert.equal(historySourceLabel('scheduled'), '定时轮询');
assert.equal(historySourceLabel('scheduled', true), '定时轮询 (scheduled)');
assert.equal(historySourceLabel('replay'), '历史重推');
assert.equal(historySourceLabel('replay', true), '历史重推 (replay)');
for (const unknown of ['future_source', '__proto__', 'constructor']) {
  assert.equal(historySourceLabel(unknown), unknown);
}
assert.equal(historySourceLabel(''), '-');
assert.deepEqual(HISTORY_STATUS_OPTIONS, [
  { value: '', text: '全部状态' }, { value: 'success', text: '已送达' },
  { value: 'partial_failed', text: '部分失败' }, { value: 'failed', text: '发送失败' },
]);
for (const [delivery_status, label, color] of [
  ['success', '已送达', 'ready'], ['partial_failed', '部分失败', 'warn'], ['failed', '发送失败', 'error'],
]) {
  const row = historyRow({ id: 7, username: 'author', source: 'scheduled', delivery_status });
  const status = find(row, n => n.props?.text === label);
  assert.ok(status.props.class.split(/\s+/).includes(color));
  assert.ok(find(row, n => n.props?.text === '定时轮询'));
}
"""
    )


def test_history_header_and_filtered_page_numbering():
    source = (ROOT / "pages/dashboard/views.js").read_text(encoding="utf-8")
    run_node(
        r"""
const assert = require('node:assert/strict');
const state = { historySelection: new Set(), groups: [] };
const els = { historyView: {}, historyContent: { replaceChildren(node) { this.tree = node; } } };
function h(tag, props = {}, children = []) { return { tag, props, children: children.filter(Boolean) }; }
function relativeTime() { return '刚刚'; }
function formatDateTime() { return '2026-11-06 00:30:26'; }
function svgIcon() { return ''; }
"""
        + source
        + r"""
for (const offset of [0, 20, 50, 150]) {
  state.history = { offset, records: [1, 2].map(id => ({ id, delivery_status: 'success' })) };
  renderHistory();
  const table = els.historyContent.tree;
  assert.equal(table.props.role, 'table');
  assert.deepEqual(table.children[0].children.map(n => n.props.text), [
    '选择', '序号', '推文内容', '状态', '投递信息', '来源', '操作',
  ]);
  assert.ok(table.children[0].children.every(n => n.props.role === 'columnheader'));
  assert.equal(table.children[0].children[3].props.class, 'history-status');
  const rows = table.children[1].children;
  assert.ok(rows.every(r => r.children[3].props.class === 'history-status'));
  assert.deepEqual(rows.map(r => r.children[1].props.text), [offset + 1, offset + 2]);
  assert.ok(rows.every(r => r.children.length === 7 && r.children.every(c => c.props.role === 'cell')));
}
state.history = { offset: 0, records: [] };
renderHistory();
assert.equal(els.historyContent.tree.children[1].children[0].children[0].props.text, '暂无推送历史记录');
"""
    )


def test_host_theme_updates_cannot_be_pinned_by_plugin():
    source = (ROOT / "pages/dashboard/ui.js").read_text(encoding="utf-8")
    theme = source[source.index("function initTheme()") :]
    run_node(
        r"""
const assert = require('node:assert/strict');
const classes = new Set(['dark-theme']);
const document = { documentElement: { classList: {
  contains: name => classes.has(name),
  toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
} } };
const window = { parent: {} };
let context = {}, callback;
const bridge = { getContext: () => context, onContext: fn => { callback = fn; } };
const els = { themeToggleBtn: {}, themeLabel: {} };
"""
        + theme
        + r"""
initTheme();
assert.ok(classes.has('dark-theme'), 'preserve URL-selected theme before host arrives');
assert.equal(els.themeToggleBtn.hidden, true);
callback({ isDark: false });
assert.ok(classes.has('light-theme'));
toggleTheme();
assert.ok(classes.has('light-theme'), 'embedded theme must follow host');
callback({ isDark: true });
assert.ok(classes.has('dark-theme'));
callback({ locale: 'zh-CN' });
assert.ok(classes.has('dark-theme'), 'unrelated context must not reset theme');
context = { isDark: false };
window.parent = window;
initTheme();
assert.equal(els.themeToggleBtn.hidden, false);
toggleTheme();
assert.ok(classes.has('dark-theme'), 'standalone preview still switches');
callback({ isDark: false });
assert.ok(classes.has('light-theme'), 'preview switching must not block future host updates');
"""
    )


def test_first_frame_uses_host_url_before_system_preference():
    source = (ROOT / "pages/dashboard/index.html").read_text(encoding="utf-8")
    inline = source.split("<script>", 1)[1].split("</script>", 1)[0]
    run_node(
        r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
"""
        + "const inline = "
        + json.dumps(inline)
        + r""";
for (const [search, systemDark, expected] of [
  ['?theme=dark', false, true], ['?theme=light', true, false], ['', true, true], ['', false, false],
]) {
  const classes = new Set();
  vm.runInNewContext(inline, {
    URLSearchParams,
    window: { location: { search }, matchMedia: () => ({ matches: systemDark }) },
    document: { documentElement: { classList: { toggle: (name, on) => on ? classes.add(name) : classes.delete(name) } } },
  });
  assert.equal(classes.has('dark-theme'), expected);
  assert.equal(classes.has('light-theme'), !expected);
}
"""
    )
