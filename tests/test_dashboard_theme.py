"""Check host theme updates, preview switching and first-frame theme selection."""

import json
from pathlib import Path

from test_dashboard_history import run_node

ROOT = Path(__file__).resolve().parents[1]


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
