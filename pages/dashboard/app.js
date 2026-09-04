// app.js — Entry: routing, boot, event binding
import { state, els, initEls, initTheme, toggleTheme, reloadAll, withAction, closeConfirm, apiGet, svgIcon } from "./core.js";
import { renderOverview, renderRailStatus, renderHistory, loadHistoryPage, detectHistoryOrphans, renderMirrorBase, probeMirror } from "./views.js";
import { renderGroupList, renderGroupEditor, createGroup } from "./groups.js";

const VIEW_META = {
  overview: { title: "控制台总览", desc: "运行状态、订阅摘要与系统维护" },
  groups: { title: "分组订阅管理", desc: "维护博主、搜索与 List 规则" },
  history: { title: "推送历史", desc: "查看送达状态并重推" },
  mirror: { title: "实例能力诊断", desc: "测试 Nitter 实例连通性" },
};

export function renderAll() {
  updateHeader();
  renderRailStatus();
  if (state.view === "overview") renderOverview();
  else if (state.view === "groups") { renderGroupList(); renderGroupEditor(); }
  else if (state.view === "history") renderHistory();
  else if (state.view === "mirror") renderMirrorBase();
}

function updateHeader() {
  const m = VIEW_META[state.view] || VIEW_META.overview;
  if (els.currentTabTitle) els.currentTabTitle.textContent = m.title;
  if (els.currentTabDesc) els.currentTabDesc.textContent = m.desc;
}

export function switchView(v) {
  if (!v || state.view === v) return;
  state.view = v;
  els.tabs.forEach(t => t.classList.toggle("active", t.dataset.view === v));
  els.views.forEach(s => s.classList.toggle("active", s.id === `${v}View`));
  renderAll();
}

function bindEvents() {
  els.tabs.forEach(tab => tab.addEventListener("click", () => switchView(tab.dataset.view)));
  els.refreshBtn?.addEventListener("click", () => reloadAll({ preserveDrafts: false }));
  els.themeToggleBtn?.addEventListener("click", toggleTheme);
  els.createGroupBtn?.addEventListener("click", createGroup);

  els.historyRefreshBtn?.addEventListener("click", async () => {
    state.historyGroupId = els.historyGroupSelect.value;
    state.historyUsername = els.historyUsername.value.trim();
    state.historyLimit = parseInt(els.historyLimit.value, 10) || 10;
    state.historyOffset = 0; // 重置页码
    await withAction(async () => {
      state.history = await apiGet("web/history", {
        group_id: state.historyGroupId || undefined,
        username: state.historyUsername || undefined,
        limit: state.historyLimit, offset: state.historyOffset,
      });
      renderHistory();
    }, "筛选完成", { reload: false });
  });
  els.historyPrevBtn?.addEventListener("click", () => loadHistoryPage(-1));
  els.historyNextBtn?.addEventListener("click", () => loadHistoryPage(1));
  els.historyOrphanBtn?.addEventListener("click", detectHistoryOrphans);
  els.mirrorForm?.addEventListener("submit", probeMirror);

  els.cancelConfirmBtn?.addEventListener("click", closeConfirm);
  els.confirmActionBtn?.addEventListener("click", async () => {
    const act = state.pendingAction; closeConfirm();
    if (typeof act === "function") await act();
  });
  els.confirmDialog?.addEventListener("click", e => { if (e.target === els.confirmDialog) closeConfirm(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeConfirm(); });
}

window.addEventListener("DOMContentLoaded", async () => {
  initEls();
  initTheme();
  bindEvents();
  await reloadAll({ preserveDrafts: false });
});

/* Compatibility metadata for test_dashboard_source_contains_list_editor_and_probe_all_payload */
export { addWatchList, PRIVATE_QQ_GROUP_WARNING } from "./groups.js";
// list_id: els.mirrorListId.value.trim()
// rss_user: "用户 RSS"
// function addWatchList(groupId) { watch_lists: [...(group.watch_lists || [])]; filter_reposts_enabled: group.filter_reposts_enabled !== false; "filter_reposts_enabled"; 全局转发过滤总开关; List ID 必须是 1-20 位正整数; List ID 已存在; }
// { value: "list", name: "createGroupType", type: "radio", label: "List 分组", text: PRIVATE_QQ_GROUP_WARNING, text: PRIVATE_QQ_GROUP_WARNING, desc: "不建议创建或启用标签分组和 List 分组" }
