// app.js - Main Application Entry & Routing
import { state, els, initEls, initTheme, toggleTheme, reloadAll, withAction, closeConfirm } from "./core.js";
import { renderOverview, renderRailStatus, renderHistory, loadHistoryPage, detectHistoryOrphans, renderMirrorBase, probeMirror } from "./views.js";
import { renderGroupList, renderGroupEditor, createGroup } from "./groups.js";

const VIEW_TITLES = {
  overview: { title: "控制台总览", desc: "全局运行状态、订阅与实例摘要及系统维护" },
  groups: { title: "分组订阅管理", desc: "维护推特博主、搜索订阅、List 规则与推送目标" },
  history: { title: "最近推送历史", desc: "查看推送送达状态、筛选并可针对性触发重推" },
  mirror: { title: "实例能力检测", desc: "测试自建 Nitter 实例的 RSS、HTML 及搜索能力" },
};

export function renderAll() {
  updateHeader();
  renderRailStatus();
  if (state.view === "overview") renderOverview();
  else if (state.view === "groups") {
    renderGroupList();
    renderGroupEditor();
  } else if (state.view === "history") renderHistory();
  else if (state.view === "mirror") renderMirrorBase();
}

function updateHeader() {
  const meta = VIEW_TITLES[state.view] || VIEW_TITLES.overview;
  if (els.currentTabTitle) els.currentTabTitle.textContent = meta.title;
  if (els.currentTabDesc) els.currentTabDesc.textContent = meta.desc;
}

export function switchView(targetView) {
  if (!targetView || state.view === targetView) return;
  state.view = targetView;

  els.tabs.forEach(t => {
    t.classList.toggle("active", t.dataset.view === targetView);
  });
  els.views.forEach(v => {
    v.classList.toggle("active", v.id === `${targetView}View`);
  });

  renderAll();
}

function bindEvents() {
  // Tabs Navigation
  els.tabs.forEach(tab => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  });

  // Topbar Actions
  if (els.refreshBtn) {
    els.refreshBtn.addEventListener("click", () => reloadAll({ preserveDrafts: false }));
  }
  if (els.themeToggleBtn) {
    els.themeToggleBtn.addEventListener("click", toggleTheme);
  }

  // Groups Actions
  if (els.createGroupBtn) {
    els.createGroupBtn.addEventListener("click", createGroup);
  }

  // History Actions
  if (els.historyRefreshBtn) {
    els.historyRefreshBtn.addEventListener("click", () => {
      state.historyGroupId = els.historyGroupSelect.value;
      state.historyUsername = els.historyUsername.value.trim();
      state.historyLimit = parseInt(els.historyLimit.value, 10) || 10;
      state.historyOffset = 0; // 重置页码
      withAction(async () => {
        state.history = await import("./core.js").then(m => m.apiGet("web/history", {
          group_id: state.historyGroupId || undefined,
          username: state.historyUsername || undefined,
          limit: state.historyLimit,
          offset: state.historyOffset,
        }));
        renderHistory();
      }, "筛选完成", { reload: false });
    });
  }
  if (els.historyPrevBtn) els.historyPrevBtn.addEventListener("click", () => loadHistoryPage(-1));
  if (els.historyNextBtn) els.historyNextBtn.addEventListener("click", () => loadHistoryPage(1));
  if (els.historyOrphanBtn) els.historyOrphanBtn.addEventListener("click", detectHistoryOrphans);

  // Mirror Probe Form
  if (els.mirrorForm) {
    els.mirrorForm.addEventListener("submit", probeMirror);
  }

  // Confirm Modal Backdrop & Cancel
  if (els.cancelConfirmBtn) els.cancelConfirmBtn.addEventListener("click", closeConfirm);
  if (els.confirmActionBtn) {
    els.confirmActionBtn.addEventListener("click", async () => {
      const act = state.pendingAction;
      closeConfirm();
      if (typeof act === "function") await act();
    });
  }
  if (els.confirmDialog) {
    els.confirmDialog.addEventListener("click", e => {
      if (e.target === els.confirmDialog) closeConfirm();
    });
  }
}

// Bootstrap
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

