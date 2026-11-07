"""Exercise dashboard history rendering without a running AstrBot account."""

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
assert.equal(HISTORY_STATUS_OPTIONS.find(o => o.value === 'success').text, '已送达');
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
