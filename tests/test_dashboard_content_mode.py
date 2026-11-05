"""Run the real dashboard content selector and payload functions in Node."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_content_dropdown_preserves_draft_and_payload():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for dashboard behavior checks")
    source = (
        Path(__file__).resolve().parents[1] / "pages/dashboard/groups.js"
    ).read_text(encoding="utf-8")
    snapshot = source[
        source.index("const EDITABLE_FIELDS") : source.index("/* 输入校验")
    ]
    payload = source[
        source.index("function buildGroupPayload") : source.index(
            "function syncGroupDrafts"
        )
    ]
    selector = source[
        source.index("  const contentSelect = createSelect") : source.index(
            '  const body = h("div", { class: "vstack" }'
        )
    ]
    harness = r"""
const assert = require("node:assert/strict");
let callback;
let options;
function createSelect(params) { options = params.options; return { onChange(fn) { callback = fn; } }; }
let writes = 0;
function updateDraft(groupId, key, value) { assert.equal(groupId, "group"); writes++; d[key] = value; }
const gid = "group";
"""
    scenarios = r"""
const d = snapshotGroup({ group_id: gid, media_only_enabled: true });
assert.equal(d.media_only_enabled, "仅媒体（保留作者）");
assert.equal(snapshotGroup({ media_only_enabled: false }).media_only_enabled, "完整推文");
SELECTOR
assert.equal(writes, 0);
assert.deepEqual(options.map(o => o.value), ["完整推文", "仅媒体（保留作者）", "仅媒体（不含文字）"]);
callback("仅媒体（不含文字）");
assert.equal(writes, 1);
assert.equal(buildGroupPayload(d).media_only_enabled, "仅媒体（不含文字）");
assert.equal(snapshotGroup(buildGroupPayload(d)).media_only_enabled, "仅媒体（不含文字）");
""".replace("SELECTOR", selector)
    result = subprocess.run(
        [node],
        input=harness + snapshot + payload + scenarios,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
