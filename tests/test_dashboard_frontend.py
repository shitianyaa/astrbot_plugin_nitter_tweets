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

        self.assertIn("checkGroup", source)
        self.assertIn("group.enabled", source)
        self.assertIn("分组停用时不能立即检查", source)



    def test_overview_uses_compact_three_panel_layout(self):
        source = APP_JS.read_text(encoding="utf-8")
        style = (ROOT / "pages" / "dashboard" / "style.css").read_text(
            encoding="utf-8"
        )
        body = _function_body(source, "renderOverview")

        self.assertIn("overview-panels", body)
        self.assertIn(".overview-panels", style)
        self.assertIn("repeat(3, minmax(0, 1fr))", style)
        self.assertIn("align-items: start", style)

    def test_dashboard_does_not_assign_innerhtml(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertNotIn(".innerHTML =", source)

    def test_external_links_are_filtered_to_http_protocols(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        safe_body = _function_body(source, "safeUrl")
        link_body = _function_body(source, "externalLink")
        history_body = _function_body(source, "renderHistory")

        self.assertIn('url.protocol === "http:"', safe_body)
        self.assertIn('url.protocol === "https:"', safe_body)
        self.assertIn("safeUrl(", link_body)
        self.assertIn("externalLink(", history_body)
        self.assertNotIn("renderPending", source)
        self.assertNotIn('data-view="pending"', html)


    def test_clipboard_fallback_textarea_is_not_tabbable(self):
        body = _function_body(APP_JS.read_text(encoding="utf-8"), "copyText")

        self.assertIn('"aria-hidden": "true", tabindex: "-1"', body)
        self.assertIn('input.style.pointerEvents = "none"', body)

    def test_group_dependent_controls_are_disabled_without_groups(self):
        body = _function_body(APP_JS.read_text(encoding="utf-8"), "setBusy")

        self.assertIn("const noGroups = !state.groups.length;", body)
        self.assertIn("const groupDependentButtons =", body)
        self.assertIn("groupDependentButtons.includes(button)", body)
        self.assertIn("noGroups", body)

    def test_reload_renders_dynamic_controls_after_busy_state_clears(self):
        body = _function_body(APP_JS.read_text(encoding="utf-8"), "reloadAll")

        self.assertLess(
            body.index("setBusy(false);"),
            body.index("renderAll();"),
        )

    def test_action_reload_happens_after_action_busy_state_clears(self):
        body = _function_body(APP_JS.read_text(encoding="utf-8"), "withAction")

        self.assertLess(
            body.index("state.actionBusy = false;", body.index("const successMessage =")),
            body.index("const reloaded = await reloadAll();"),
        )

    def test_non_reload_actions_rerender_dynamic_controls_after_busy_clears(self):
        body = _function_body(APP_JS.read_text(encoding="utf-8"), "withAction")

        self.assertIn("options.rerender", body)
        self.assertLess(
            body.index("state.actionBusy = false;", body.index("const successMessage =")),
            body.index("options.rerender();"),
        )
        self.assertLess(
            body.index("setBusy(false);", body.index("const successMessage =")),
            body.index("options.rerender();"),
        )

    def test_history_pager_buttons_join_busy_state(self):
        source = APP_JS.read_text(encoding="utf-8")
        busy_body = _function_body(source, "setBusy")
        bind_body = _function_body(source, "bindEvents")

        self.assertIn("els.historyPrevBtn", busy_body)
        self.assertIn("els.historyNextBtn", busy_body)
        self.assertIn("if (state.loading || state.actionBusy) return;", bind_body)

    def test_group_draft_updates_do_not_rerender_active_editor(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = _function_body(source, "updateGroupDraft")

        self.assertIn("renderGroupList();", body)
        self.assertIn("syncGroupEditorControls(groupId);", body)
        self.assertNotIn("renderGroupEditor();", body)

    def test_api_get_passes_params_without_mutating_endpoint(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = _function_body(source, "apiGet")

        self.assertIn("bridge.apiGet(endpoint,", body)
        self.assertIn("entries.length ? query : undefined", body)
        self.assertNotIn("endpointWithQuery", source)

    def test_manual_refresh_discards_unsaved_group_drafts_after_confirmation(self):
        source = APP_JS.read_text(encoding="utf-8")
        refresh_body = _function_body(source, "refreshDashboard")
        reload_body = _function_body(source, "reloadAll")
        bind_body = _function_body(source, "bindEvents")

        self.assertIn("hasDirtyGroup()", refresh_body)
        self.assertIn("window.confirm", refresh_body)
        self.assertIn("preserveDrafts: false", refresh_body)
        self.assertIn("state.groupDrafts = {};", reload_body)
        self.assertIn("refreshDashboard", bind_body)

    def test_checkbox_changes_still_refresh_editor_labels(self):
        body = _function_body(APP_JS.read_text(encoding="utf-8"), "bindEvents")

        self.assertIn('target.dataset.fieldType === "checkbox"', body)
        self.assertIn("renderGroupEditor();", body)

    def test_checkbox_controls_are_not_stretched_by_text_input_styles(self):
        style = (ROOT / "pages" / "dashboard" / "style.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('input:not([type="checkbox"])', style)
        self.assertIn('.toggle-field input[type="checkbox"]', style)
        self.assertIn(".replay-target-option input[type=\"checkbox\"]", style)
        self.assertNotIn("input,\nselect {", style)

    def test_watch_user_chips_can_delete_single_account(self):
        source = APP_JS.read_text(encoding="utf-8")
        editor_body = _function_body(source, "renderGroupEditor")
        section_body = _function_body(source, "buildWatchUserSection")
        confirm_body = _function_body(source, "confirmDeleteWatchUser")

        self.assertIn("buildWatchUserSection(group)", editor_body)
        self.assertIn("deleteWatchUser", section_body)
        self.assertIn("deleteWatchUserGroup", section_body)
        self.assertIn("confirmDeleteWatchUser", source)
        self.assertIn("web/subscriptions/delete", confirm_body)
        self.assertIn("entries: username", confirm_body)

    def test_group_attention_items_are_rendered(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = _function_body(source, "renderGroupList")

        self.assertIn("group.attention_items", body)
        self.assertIn("group-list-alerts", body)
        self.assertIn("attention-badge", source)
        self.assertIn("item.title", source)

    def test_group_invalid_and_duplicate_watch_users_are_rendered(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = _function_body(source, "renderGroupEditor")

        self.assertIn("group.invalid_watch_users", body)
        self.assertIn("group.duplicate_watch_users", body)
        self.assertIn("无效关注账号", body)
        self.assertIn("重复关注项", body)

    def test_groups_view_uses_top_switcher_layout(self):
        source = INDEX_HTML.read_text(encoding="utf-8")
        style = (ROOT / "pages" / "dashboard" / "style.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="groupSwitcher"', source)
        self.assertIn('id="groupList"', source)
        self.assertIn('id="groupEditor"', source)
        self.assertIn('id="createGroupBtn"', source)
        self.assertIn(".groups-layout", style)
        self.assertIn(".group-switcher", style)
        self.assertIn(".group-list", style)
        self.assertIn("overflow-x: auto", style)
        self.assertNotIn('class="group-sidebar"', source)

    def test_create_group_dialog_does_not_accept_group_id(self):
        source = APP_JS.read_text(encoding="utf-8")
        style = (ROOT / "pages" / "dashboard" / "style.css").read_text(
            encoding="utf-8"
        )
        body = _function_body(source, "createGroup")

        self.assertIn("openConfirm", body)
        self.assertIn("name: nameInput.value.trim()", body)
        self.assertNotIn("idInput", body)
        self.assertNotIn("group_id:", body)
        self.assertNotIn("分组 ID", body)
        self.assertIn(".confirm-form", style)

    def test_dashboard_removes_generic_plugin_page_kicker(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertNotIn("AstrBot Plugin Page", source)

    def test_dashboard_uses_design_concept_shell_without_static_mock_wiring(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        app_source = APP_JS.read_text(encoding="utf-8")

        self.assertIn('class="rail"', html)
        self.assertIn('class="brand-logo"', html)
        self.assertIn('class="main"', html)
        self.assertIn('id="currentTabTitle"', html)
        self.assertIn('id="currentTabDesc"', html)
        self.assertIn('id="railSchedulerStatus"', html)
        self.assertIn('data-view="overview"', html)
        self.assertIn("window.AstrBotPluginPage", app_source)
        self.assertNotIn('data-tab="overview"', html)
        self.assertNotIn('id="view-overview"', html)

    def test_dashboard_design_does_not_depend_on_remote_fonts(self):
        html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("fonts.gstatic.com", html)

    def test_theme_toggle_uses_safe_storage_and_matching_icons(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        style = (ROOT / "pages" / "dashboard" / "style.css").read_text(
            encoding="utf-8"
        )
        init_body = _function_body(source, "initTheme")
        toggle_body = _function_body(source, "toggleTheme")

        self.assertIn("safeStorageGet", source)
        self.assertIn("safeStorageSet", source)
        self.assertNotIn("localStorage.getItem", init_body)
        self.assertNotIn("localStorage.setItem", toggle_body)
        self.assertIn('class="sun-icon"', html)
        self.assertIn('class="moon-icon"', html)
        self.assertIn(".sun-icon", style)
        self.assertIn(".moon-icon", style)

    def test_group_editor_tracks_dirty_state(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = _function_body(source, "saveGroupEdits")
        snapshot_body = _function_body(source, "snapshotEditableGroup")

        self.assertIn("groupDrafts", source)
        self.assertIn("isGroupDirty", source)
        self.assertIn("snapshotEditableGroup", body)
        self.assertIn("push_targets", snapshot_body)

    def test_dirty_group_disables_check_and_publish_actions(self):
        source = APP_JS.read_text(encoding="utf-8")
        editor_body = _function_body(source, "renderGroupEditor")

        self.assertIn("isGroupDirty(group.group_id)", editor_body)
        self.assertIn("请先保存更改", editor_body)
        self.assertIn("disabled: !group.enabled || dirty || state.loading || state.actionBusy", editor_body)


    def test_immediate_check_requires_confirmation(self):
        source = APP_JS.read_text(encoding="utf-8")
        run_body = _function_body(source, "runGroupCheck")

        self.assertIn("openConfirm", run_body)
        self.assertIn("将使用当前已保存配置", run_body)
        self.assertIn("可能立即推送", run_body)
        self.assertIn('apiPost("web/check"', run_body)

    def test_push_target_chips_are_editable(self):
        source = APP_JS.read_text(encoding="utf-8")
        editor_body = _function_body(source, "renderGroupEditor")
        target_body = _function_body(source, "buildPushTargetEditor")

        self.assertIn("buildPushTargetEditor(group, draft)", editor_body)
        self.assertIn("deletePushTarget", target_body)
        self.assertIn("confirmDeletePushTarget", source)
        self.assertNotIn("editPushTarget", target_body)
        self.assertNotIn("chip-delete", target_body)
        self.assertNotIn("savePushTarget", target_body)

    def test_push_targets_can_be_probed_without_saving(self):
        source = APP_JS.read_text(encoding="utf-8")
        target_body = _function_body(source, "buildPushTargetEditor")
        probe_body = _function_body(source, "probePushTargets")
        bind_body = _function_body(source, "bindEvents")

        self.assertIn("probePushTargets", source)
        self.assertIn("probePushTargets", target_body)
        self.assertIn('apiPost("web/targets/probe"', probe_body)
        self.assertIn("pushTargetList(groupId)", probe_body)
        self.assertIn("targetProbeResults", source)
        self.assertIn("renderTargetProbeResults", source)
        self.assertIn("target.dataset.probePushTargets", bind_body)

    def test_history_empty_state_explains_new_history_only(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = _function_body(source, "renderHistory")

        self.assertIn("新版本启用后成功送达", body)

    def test_recent_push_history_view_is_wired(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        pager_body = _function_body(source, "renderHistoryPager")

        self.assertIn('data-view="history"', html)
        self.assertIn('id="historyView"', html)
        self.assertIn('id="historyPrevBtn"', html)
        self.assertIn('id="historyNextBtn"', html)
        self.assertIn('id="historyPageLabel"', html)
        self.assertIn('id="historyLimit" type="number" min="1" max="50" value="10"', html)
        self.assertIn("最近推送", html)
        self.assertIn('apiGet("web/history"', source)
        self.assertIn('apiPost("web/history/replay"', source)
        self.assertIn("historyOffset", source)
        self.assertIn("offset: state.historyOffset", source)
        self.assertIn("next_offset", source)
        self.assertIn("prev_offset", source)
        self.assertIn("replayHistory", source)
        self.assertIn("total_pages", pager_body)
        self.assertIn("${page} / ${totalPages}", pager_body)
        self.assertNotIn("第 ${page} 页", pager_body)

    def test_recent_push_history_can_detect_and_delete_orphan_groups(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        render_body = _function_body(source, "renderHistoryOrphans")
        detect_body = _function_body(source, "detectHistoryOrphans")
        delete_body = _function_body(source, "confirmDeleteHistoryOrphan")

        self.assertIn('id="historyOrphanBtn"', html)
        self.assertIn('id="historyOrphanResult"', html)
        self.assertIn('apiGet("web/history/orphans"', detect_body)
        self.assertIn("payload.orphans", render_body)
        self.assertIn("data-delete-history-orphan", render_body)
        self.assertIn('apiPost("web/history/orphans/delete"', delete_body)
        self.assertIn('confirm: "DELETE"', delete_body)

    def test_recent_push_history_groups_targets_and_replays_selected_targets(self):
        source = APP_JS.read_text(encoding="utf-8")
        render_body = _function_body(source, "renderHistory")
        chips_body = _function_body(source, "historyTargetChips")
        replay_body = _function_body(source, "replayHistory")

        self.assertIn("historyTargetChips", render_body)
        self.assertIn("row.target_umos", chips_body)
        self.assertIn("replay_target_options", replay_body)
        self.assertIn("data-replay-target", replay_body)
        self.assertIn("target_umos: selectedTargets", replay_body)

    def test_recent_push_history_shows_partial_delivery_failures(self):
        source = APP_JS.read_text(encoding="utf-8")
        render_body = _function_body(source, "renderHistory")
        status_body = _function_body(source, "historyDeliveryStatus")

        self.assertIn("historyDeliveryStatus", source)
        self.assertIn("historyDeliveryStatus(row)", render_body)
        self.assertIn("row.delivery_status", status_body)
        self.assertIn("row.delivery_error", status_body)
        self.assertIn("媒体失败", source)

    def test_confirm_dialog_has_accessible_focus_management(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        open_body = _function_body(source, "openConfirm")
        close_body = _function_body(source, "closeConfirm")
        trap_body = _function_body(source, "trapConfirmFocus")
        bind_body = _function_body(source, "bindEvents")

        self.assertIn('aria-labelledby="confirmTitle"', html)
        self.assertIn('aria-describedby="confirmDesc"', html)
        self.assertIn("state.lastFocusedElement = document.activeElement", open_body)
        self.assertIn('document.body.classList.add("dialog-open")', open_body)
        self.assertIn("focusable[0].focus()", open_body)
        self.assertIn('document.body.classList.remove("dialog-open")', close_body)
        self.assertIn("state.lastFocusedElement.focus()", close_body)
        self.assertIn("trapConfirmFocus", bind_body)
        self.assertIn('event.key !== "Tab"', trap_body)
        self.assertIn("event.preventDefault()", trap_body)

    def test_replay_confirm_button_tracks_selected_targets(self):
        source = APP_JS.read_text(encoding="utf-8")
        replay_body = _function_body(source, "replayHistory")

        self.assertIn("updateReplayConfirmState", replay_body)
        self.assertIn("change", replay_body)
        self.assertIn("querySelectorAll(\"[data-replay-target]:checked\")", replay_body)
        self.assertIn("els.confirmActionBtn.disabled = selectedCount <= 0", replay_body)

    def test_clear_all_seen_posts_explicit_confirmation(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        clear_body = _function_body(source, "confirmClearSeen")

        self.assertIn('confirm: groupId ? "" : "CLEAR_ALL"', clear_body)
        self.assertIn("全部分组", clear_body)
        self.assertIn("清理推送记录", html)
        self.assertIn("清理推送记录？", clear_body)

    def test_group_editor_renders_global_fields_as_read_only_context(self):
        body = _function_body(APP_JS.read_text(encoding="utf-8"), "renderGroupEditor")

        self.assertIn("继承全局", body)
        self.assertIn("check_interval_minutes", body)

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

        for forbidden in ("接收位置", "订阅目标", "seen记录", "seen 记录", "去重记录"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
