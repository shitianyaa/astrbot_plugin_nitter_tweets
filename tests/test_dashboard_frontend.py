from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "pages" / "dashboard" / "app.js"
INDEX_HTML = ROOT / "pages" / "dashboard" / "index.html"


def _function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.index(marker)
    brace_start = source.index(") {", start) + 2
    depth = 0
    for index in range(brace_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1 : index]
    raise AssertionError(f"function body not found: {name}")


class DashboardFrontendSourceTest(unittest.TestCase):
    def test_action_success_message_is_shown_after_reload(self):
        body = _function_body(APP_JS.read_text(encoding="utf-8"), "withAction")

        self.assertIn("const successMessage =", body)
        self.assertLess(
            body.index("await reloadAll();"),
            body.index('showAlert(successMessage, "success");'),
        )

    def test_action_does_not_overwrite_reload_failure_alert(self):
        source = APP_JS.read_text(encoding="utf-8")
        reload_body = _function_body(source, "reloadAll")
        action_body = _function_body(source, "withAction")

        self.assertIn("return true;", reload_body)
        self.assertIn("return false;", reload_body)
        self.assertIn("const reloaded = await reloadAll();", action_body)
        self.assertLess(
            action_body.index("if (reloaded === false)"),
            action_body.index('showAlert(successMessage, "success");'),
        )

    def test_disabled_group_check_button_is_disabled(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("data-check-group=", source)
        self.assertIn("group.enabled", source)
        self.assertIn("分组停用时不能立即检查", source)

    def test_pending_summary_shows_queue_time_bounds(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("oldest_created_at", source)
        self.assertIn("newest_created_at", source)
        self.assertIn("最早", source)
        self.assertIn("最新", source)

    def test_pending_summary_shows_account_breakdown(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = _function_body(source, "renderPending")

        self.assertIn("item.user_counts", body)
        self.assertIn("summary-users", body)
        self.assertIn("账号", body)

    def test_group_dependent_controls_are_disabled_without_groups(self):
        body = _function_body(APP_JS.read_text(encoding="utf-8"), "setBusy")

        self.assertIn("const noGroups = !state.groups.length;", body)
        self.assertIn("const groupDependentButtons =", body)
        self.assertIn("groupDependentButtons.includes(button)", body)
        self.assertIn("noGroups", body)

    def test_group_attention_items_are_rendered(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = _function_body(source, "renderGroups")

        self.assertIn("group.attention_items", body)
        self.assertIn("group-alerts", body)
        self.assertIn("attention-badge", body)
        self.assertIn("item.title", body)

    def test_group_invalid_and_duplicate_watch_users_are_rendered(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = _function_body(source, "renderGroups")

        self.assertIn("group.invalid_watch_users", body)
        self.assertIn("group.duplicate_watch_users", body)
        self.assertIn("无效关注账号", body)
        self.assertIn("重复关注项", body)

    def test_cache_cleanup_result_shows_media_breakdown(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = _function_body(source, "confirmClearCache")

        self.assertIn("removed_images", body)
        self.assertIn("removed_videos", body)
        self.assertIn("removed_other", body)
        self.assertIn("removed_empty_dirs", body)
        self.assertIn("skipped_dirs", body)

    def test_dashboard_avoids_confusing_terms(self):
        source = "\n".join(
            [
                APP_JS.read_text(encoding="utf-8"),
                INDEX_HTML.read_text(encoding="utf-8"),
            ]
        )

        for forbidden in ("接收位置", "订阅目标", "seen记录", "seen 记录"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
