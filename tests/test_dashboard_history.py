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
        [node], input=script, text=True, capture_output=True, timeout=15
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
  assert.ok(status.props.class.includes(color));
  assert.ok(find(row, n => n.props?.text === '定时轮询'));
}
"""
    )
