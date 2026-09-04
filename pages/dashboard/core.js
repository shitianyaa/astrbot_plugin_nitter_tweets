// core.js - Shared Infrastructure, State, DOM & Dialogs
export const bridge = window.AstrBotPluginPage;

export const state = {
  view: "overview",
  loading: false,
  actionBusy: false,
  overview: null,
  groups: [],
  groupDrafts: {},
  targetProbeResults: {},
  targetBlacklists: [],
  targetBlacklistTarget: "",

  history: null,
  historyOrphans: null,
  selectedGroupId: "",

  historyGroupId: "",
  historyUsername: "",
  historyLimit: 10,
  historyOffset: 0,
  seenGroupId: "",
  pendingAction: null,
  lastFocusedElement: null,
  lastUpdated: "",
};

export const els = {};

export function initEls() {
  els.tabs = document.querySelectorAll(".tab");
  els.views = document.querySelectorAll(".view");
  els.refreshBtn = document.getElementById("refreshBtn");
  els.lastUpdated = document.getElementById("lastUpdated");
  els.currentTabTitle = document.getElementById("currentTabTitle");
  els.currentTabDesc = document.getElementById("currentTabDesc");
  els.themeToggleBtn = document.getElementById("themeToggleBtn");
  els.railSchedulerStatus = document.getElementById("railSchedulerStatus");
  els.railScheduleStatus = document.getElementById("railScheduleStatus");
  els.railTargetStatus = document.getElementById("railTargetStatus");
  els.alert = document.getElementById("alert");
  els.toastContainer = document.getElementById("toastContainer");
  
  els.overviewView = document.getElementById("overviewView");
  els.groupsView = document.getElementById("groupsView");
  els.historyView = document.getElementById("historyView");
  els.mirrorView = document.getElementById("mirrorView");

  els.createGroupBtn = document.getElementById("createGroupBtn");
  els.groupList = document.getElementById("groupList");
  els.groupEditor = document.getElementById("groupEditor");

  els.historyGroupSelect = document.getElementById("historyGroupSelect");
  els.historyUsername = document.getElementById("historyUsername");
  els.historyLimit = document.getElementById("historyLimit");
  els.historyRefreshBtn = document.getElementById("historyRefreshBtn");
  els.historyOrphanBtn = document.getElementById("historyOrphanBtn");
  els.historyPrevBtn = document.getElementById("historyPrevBtn");
  els.historyNextBtn = document.getElementById("historyNextBtn");
  els.historyPageLabel = document.getElementById("historyPageLabel");
  els.historyOrphanResult = document.getElementById("historyOrphanResult");
  els.historyContent = document.getElementById("historyContent");

  els.mirrorForm = document.getElementById("mirrorForm");
  els.mirrorUsername = document.getElementById("mirrorUsername");
  els.mirrorQuery = document.getElementById("mirrorQuery");
  els.mirrorListId = document.getElementById("mirrorListId");
  els.mirrorLimit = document.getElementById("mirrorLimit");
  els.mirrorInstance = document.getElementById("mirrorInstance");
  els.mirrorProbeBtn = document.getElementById("mirrorProbeBtn");
  els.instanceList = document.getElementById("instanceList");
  els.mirrorResult = document.getElementById("mirrorResult");

  els.clearCacheBtn = document.getElementById("clearCacheBtn");
  els.clearSeenBtn = document.getElementById("clearSeenBtn");
  els.seenGroupSelect = document.getElementById("seenGroupSelect");
  els.cacheResult = document.getElementById("cacheResult");
  els.seenResult = document.getElementById("seenResult");

  els.confirmDialog = document.getElementById("confirmDialog");
  els.confirmTitle = document.getElementById("confirmTitle");
  els.confirmDesc = document.getElementById("confirmDesc");
  els.cancelConfirmBtn = document.getElementById("cancelConfirmBtn");
  els.confirmActionBtn = document.getElementById("confirmActionBtn");
}

/* --------------------------------------------------------------------------
   Lightweight DOM Builder (h)
   -------------------------------------------------------------------------- */
export function h(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, val] of Object.entries(props)) {
    if (val === null || val === undefined || val === false) continue;
    if (key === "class" || key === "className") {
      node.className = val;
    } else if (key === "style" && typeof val === "object") {
      Object.assign(node.style, val);
    } else if (key === "text" || key === "textContent") {
      node.textContent = String(val);
    } else if (key.startsWith("on") && typeof val === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), val);
    } else if (key === "dataset" && typeof val === "object") {
      Object.assign(node.dataset, val);
    } else {
      node.setAttribute(key, val === true ? "" : String(val));
    }
  }
  const childNodes = Array.isArray(children) ? children : [children];
  for (const child of childNodes) {
    if (child === null || child === undefined || child === false) continue;
    if (typeof child === "string" || typeof child === "number") {
      node.appendChild(document.createTextNode(String(child)));
    } else if (child instanceof Node) {
      node.appendChild(child);
    }
  }
  return node;
}

/* --------------------------------------------------------------------------
   API Helpers
   -------------------------------------------------------------------------- */
export function apiResult(res) {
  if (!res || res.success === false) {
    throw new Error((res && res.error) || "请求失败");
  }
  return res;
}

export async function apiGet(endpoint, params) {
  const query = {};
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") query[k] = v;
    }
  }
  return apiResult(await bridge.apiGet(endpoint, Object.keys(query).length ? query : undefined));
}

export async function apiPost(endpoint, body) {
  return apiResult(await bridge.apiPost(endpoint, body || {}));
}

/* --------------------------------------------------------------------------
   Feedback & Notifications
   -------------------------------------------------------------------------- */
export function showAlert(msg, type = "success") {
  if (!els.alert) return;
  els.alert.className = `alert ${type}`;
  els.alert.textContent = msg;
  els.alert.hidden = false;
}

export function hideAlert() {
  if (!els.alert) return;
  els.alert.hidden = true;
  els.alert.textContent = "";
}

export function showToast(msg) {
  if (!els.toastContainer) return;
  const t = h("div", { class: "toast", text: msg });
  els.toastContainer.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(`已复制: ${text}`);
  } catch {
    showToast("复制失败");
  }
}

export function setBusy(isBusy) {
  state.loading = isBusy;
  const btns = [
    els.refreshBtn, els.createGroupBtn, els.historyRefreshBtn,
    els.historyOrphanBtn, els.historyPrevBtn, els.historyNextBtn,
    els.mirrorProbeBtn, els.clearCacheBtn, els.clearSeenBtn
  ];
  btns.forEach(b => { if (b) b.disabled = isBusy || state.actionBusy; });
}

/* --------------------------------------------------------------------------
   Confirm Dialog
   -------------------------------------------------------------------------- */
export function openConfirm({ title, desc, confirmText = "确认", danger = false, action }) {
  if (!els.confirmDialog) return;
  state.lastFocusedElement = document.activeElement;
  state.pendingAction = action;

  els.confirmTitle.textContent = title || "确认操作？";
  els.confirmDesc.replaceChildren(typeof desc === "string" ? document.createTextNode(desc) : desc);
  els.confirmActionBtn.textContent = confirmText;
  els.confirmActionBtn.className = `button ${danger ? "danger" : "primary"}`;

  els.confirmDialog.hidden = false;
  els.confirmActionBtn.focus();
}

export function closeConfirm() {
  if (!els.confirmDialog) return;
  els.confirmDialog.hidden = true;
  state.pendingAction = null;
  if (state.lastFocusedElement && state.lastFocusedElement.focus) {
    state.lastFocusedElement.focus();
  }
}

/* --------------------------------------------------------------------------
   Action Execution Wrapper
   -------------------------------------------------------------------------- */
export async function withAction(action, successText, { reload = true, rerender = null } = {}) {
  state.actionBusy = true;
  setBusy(true);
  hideAlert();
  try {
    const res = await action();
    state.actionBusy = false;
    if (reload) {
      const ok = await reloadAll();
      if (!ok) return res;
    } else if (typeof rerender === "function") {
      setBusy(false);
      rerender();
    }
    showAlert(successText || (res && res.message) || "操作完成", "success");
    return res;
  } catch (err) {
    showAlert(err.message || "操作失败", "error");
    return null;
  } finally {
    state.actionBusy = false;
    setBusy(false);
  }
}

/* --------------------------------------------------------------------------
   Theme & Storage
   -------------------------------------------------------------------------- */
export function initTheme() {
  const saved = localStorage.getItem("nitter-dashboard-theme");
  if (saved === "dark") {
    document.body.classList.add("dark-theme");
    document.body.classList.remove("light-theme");
  } else if (saved === "light") {
    document.body.classList.add("light-theme");
    document.body.classList.remove("dark-theme");
  }
}

export function toggleTheme() {
  const isDark = document.body.classList.contains("dark-theme") || 
    (!document.body.classList.contains("light-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
  if (isDark) {
    document.body.classList.remove("dark-theme");
    document.body.classList.add("light-theme");
    localStorage.setItem("nitter-dashboard-theme", "light");
  } else {
    document.body.classList.remove("light-theme");
    document.body.classList.add("dark-theme");
    localStorage.setItem("nitter-dashboard-theme", "dark");
  }
}

/* --------------------------------------------------------------------------
   Full Reload
   -------------------------------------------------------------------------- */
import { syncGroupDrafts } from "./groups.js";
import { renderAll } from "./app.js";

export async function reloadAll(options = {}) {
  setBusy(true);
  hideAlert();
  try {
    await bridge.ready();
    const [overview, groupsRes, blacklistsRes] = await Promise.all([
      apiGet("web/overview"),
      apiGet("web/groups"),
      apiGet("web/target-blacklists")
    ]);
    state.overview = overview;
    state.groups = groupsRes.groups || [];
    state.targetBlacklists = blacklistsRes.target_blacklists || [];

    if (!state.selectedGroupId || !state.groups.some(g => g.group_id === state.selectedGroupId)) {
      state.selectedGroupId = state.groups[0] ? state.groups[0].group_id : "";
    }

    if (options.preserveDrafts === false) {
      state.groupDrafts = {};
    }
    syncGroupDrafts();

    // 默认加载一次历史
    state.history = await apiGet("web/history", {
      group_id: state.historyGroupId || undefined,
      username: state.historyUsername || undefined,
      limit: state.historyLimit,
      offset: state.historyOffset
    });

    state.lastUpdated = new Date().toLocaleTimeString();
    if (els.lastUpdated) els.lastUpdated.textContent = state.lastUpdated;

    setBusy(false);
    renderAll();
    return true;
  } catch (err) {
    showAlert(err.message || "加载控制台数据失败", "error");
    return false;
  } finally {
    setBusy(false);
  }
}
