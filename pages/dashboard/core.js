// core.js — Infrastructure: State, API, DOM, Icons, Feedback

export const bridge = window.AstrBotPluginPage;

export const state = {
  view: "overview", loading: false, actionBusy: false,
  overview: null, groups: [], groupDrafts: {}, targetProbeResults: {},
  targetBlacklists: [], targetBlacklistTarget: "",
  history: null, historyOrphans: null, selectedGroupId: "",
  historyGroupId: "", historyUsername: "", historyLimit: 10,
  historyOffset: 0, seenGroupId: "",
  pendingAction: null, lastFocusedElement: null, lastUpdated: "",
};

export const els = {};

export function initEls() {
  const ids = [
    "refreshBtn","lastUpdated","currentTabTitle","currentTabDesc","themeToggleBtn",
    "railSchedulerStatus","railScheduleStatus","railTargetStatus","alert","toastContainer",
    "overviewView","groupsView","historyView","mirrorView",
    "createGroupBtn","groupList","groupEditor",
    "historyGroupSelect","historyUsername","historyLimit","historyRefreshBtn",
    "historyOrphanBtn","historyPrevBtn","historyNextBtn","historyPageLabel",
    "historyOrphanResult","historyContent",
    "mirrorForm","mirrorUsername","mirrorQuery","mirrorListId","mirrorLimit",
    "mirrorInstance","mirrorProbeBtn","instanceList","mirrorResult",
    "confirmDialog","confirmTitle","confirmDesc","cancelConfirmBtn","confirmActionBtn",
  ];
  ids.forEach(id => { els[id] = document.getElementById(id); });
  els.tabs = document.querySelectorAll(".tab");
  els.views = document.querySelectorAll(".view");
}

/* --------------------------------------------------------------------------
   Inline SVG Icon Library (zero network requests)
   -------------------------------------------------------------------------- */
const ICONS = {
  x: '<path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>',
  home: '<path d="M12 1.696L.622 8.807l.762 1.233L3 8.75V20h6v-6h6v6h6V8.75l1.616 1.29.762-1.233z"/>',
  list: '<path d="M3 4.5h18v2H3zm0 6.5h18v2H3zm0 6.5h18v2H3zM7 9.5H5V8h2zm0 6.5H5v-1.5h2z"/>',
  clock: '<path d="M10 1.5a8.5 8.5 0 100 17 8.5 8.5 0 000-17zm0 15a6.5 6.5 0 110-13 6.5 6.5 0 010 13zm.5-10H9v5l4 2.5.8-1.3L10.5 11z" transform="translate(2 2)"/>',
  probe: '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="m20 20-3.5-3.5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>',
  user: '<circle cx="12" cy="8" r="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M4 21c0-4 4-7 8-7s8 3 8 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  hash: '<path d="M6 3v6H3v2h3v6h2v-6h4v6h2v-6h3v-2h-3V3h-2v6H8V3z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
  send: '<path d="M22 2L11 13M22 2l-7 20-4-9-9-4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>',
  refresh: '<path d="M21 12a9 9 0 11-3-6.7M21 4v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  play: '<path d="M8 5v14l11-7z"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  plus: '<path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  check: '<path d="M9 16.2l-3.5-3.5L4 14.2 9 19l11-11-1.5-1.5z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  alert: '<path d="M12 2L1 21h22zM12 9v6m0 3v.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  close: '<path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M5 15V5a2 2 0 012-2h10" fill="none" stroke="currentColor" stroke-width="2"/>',
  sun: '<circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 2v2M12 20v2M4 4l1.4 1.4M18.6 18.6L20 20M2 12h2M20 12h2M4 20l1.4-1.4M18.6 5.4L20 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  moon: '<path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="9" cy="9" r="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M21 15l-5-5L5 21" fill="none" stroke="currentColor" stroke-width="2"/>',
  video: '<rect x="2" y="6" width="14" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M16 10l6-3v10l-6-3z" fill="none" stroke="currentColor" stroke-width="2"/>',
  rss: '<path d="M4 11a9 9 0 019 9M4 4a16 16 0 0116 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="5" cy="19" r="1.5" fill="currentColor"/>',
  search: '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="m20 20-3.5-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  external: '<path d="M14 3h7v7M21 3l-9 9M19 14v5a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
};

export function svgIcon(name, size = 20) {
  const path = ICONS[name] || "";
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="currentColor" xmlns="http://www.w3.org/2000/svg">${path}</svg>`;
}

export function iconEl(name, size = 20) {
  const wrapper = document.createElement("span");
  wrapper.innerHTML = svgIcon(name, size);
  return wrapper.firstElementChild || wrapper;
}

/* --------------------------------------------------------------------------
   DOM Builder h()
   -------------------------------------------------------------------------- */
export function h(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class" || k === "className") node.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k === "text" || k === "textContent") node.textContent = String(v);
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset" && typeof v === "object") Object.assign(node.dataset, v);
    else if (k === "checked") node.checked = !!v;
    else if (k === "disabled") { if (v) node.disabled = true; }
    else if (v === true) node.setAttribute(k, "");
    else node.setAttribute(k, String(v));
  }
  const items = Array.isArray(children) ? children : [children];
  for (const c of items) {
    if (c === null || c === undefined || c === false) continue;
    if (typeof c === "string" || typeof c === "number") node.appendChild(document.createTextNode(String(c)));
    else if (c instanceof Node) node.appendChild(c);
  }
  return node;
}

/* --------------------------------------------------------------------------
   API
   -------------------------------------------------------------------------- */
export function apiResult(res) {
  if (!res || res.success === false) throw new Error((res && res.error) || "请求失败");
  return res;
}
export async function apiGet(endpoint, params) {
  const q = {};
  if (params) for (const [k, v] of Object.entries(params)) { if (v != null && v !== "") q[k] = v; }
  return apiResult(await bridge.apiGet(endpoint, Object.keys(q).length ? q : undefined));
}
export async function apiPost(endpoint, body) {
  return apiResult(await bridge.apiPost(endpoint, body || {}));
}

/* --------------------------------------------------------------------------
   Feedback
   -------------------------------------------------------------------------- */
export function showAlert(msg, type = "success") {
  if (!els.alert) return;
  els.alert.className = `alert ${type}`;
  els.alert.textContent = msg;
  els.alert.hidden = false;
}
export function hideAlert() { if (els.alert) { els.alert.hidden = true; els.alert.textContent = ""; } }
export function showToast(msg) {
  if (!els.toastContainer) return;
  const t = h("div", { class: "toast", text: msg });
  els.toastContainer.appendChild(t);
  setTimeout(() => t.remove(), 2800);
}
export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); showToast("已复制"); }
  catch { showToast("复制失败"); }
}
export function setBusy(isBusy) {
  state.loading = isBusy;
  [els.refreshBtn, els.createGroupBtn, els.historyRefreshBtn, els.historyOrphanBtn,
   els.historyPrevBtn, els.historyNextBtn, els.mirrorProbeBtn].forEach(b => { if (b) b.disabled = isBusy || state.actionBusy; });
}

/* --------------------------------------------------------------------------
   Confirm Dialog
   -------------------------------------------------------------------------- */
export function openConfirm({ title, desc, confirmText = "确认", danger = false, action }) {
  state.lastFocusedElement = document.activeElement;
  state.pendingAction = action;
  els.confirmTitle.textContent = title || "确认操作？";
  els.confirmDesc.replaceChildren(typeof desc === "string" ? document.createTextNode(desc) : desc);
  els.confirmActionBtn.textContent = confirmText;
  els.confirmActionBtn.className = `btn btn-sm ${danger ? "btn-danger" : "btn-primary"}`;
  els.confirmDialog.hidden = false;
  els.confirmActionBtn.focus();
}
export function closeConfirm() {
  els.confirmDialog.hidden = true;
  state.pendingAction = null;
  if (state.lastFocusedElement?.focus) state.lastFocusedElement.focus();
}

/* --------------------------------------------------------------------------
   Theme
   -------------------------------------------------------------------------- */
export function initTheme() {
  const saved = localStorage.getItem("nitter-dashboard-theme");
  if (saved === "dark") document.body.classList.add("dark-theme");
  else if (saved === "light") document.body.classList.add("light-theme");
}
export function toggleTheme() {
  const isDark = document.body.classList.contains("dark-theme") ||
    (!document.body.classList.contains("light-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
  document.body.classList.toggle("dark-theme", !isDark);
  document.body.classList.toggle("light-theme", isDark);
  localStorage.setItem("nitter-dashboard-theme", isDark ? "light" : "dark");
}

/* --------------------------------------------------------------------------
   Action wrapper & reloadAll (deferred imports to avoid circular)
   -------------------------------------------------------------------------- */
export async function withAction(action, successText, { reload = true, rerender = null } = {}) {
  state.actionBusy = true; setBusy(true); hideAlert();
  try {
    const res = await action();
    state.actionBusy = false;
    if (reload) {
      const ok = await reloadAll();
      if (!ok) return res;
    } else if (rerender) { setBusy(false); rerender(); }
    showAlert(successText || res?.message || "操作完成");
    return res;
  } catch (err) { showAlert(err.message || "操作失败", "error"); return null; }
  finally { state.actionBusy = false; setBusy(false); }
}

export async function reloadAll(options = {}) {
  setBusy(true); hideAlert();
  try {
    await bridge.ready();
    const [ov, gr, bl] = await Promise.all([
      apiGet("web/overview"), apiGet("web/groups"), apiGet("web/target-blacklists"),
    ]);
    state.overview = ov;
    state.groups = gr.groups || [];
    state.targetBlacklists = bl.target_blacklists || [];
    if (!state.selectedGroupId || !state.groups.some(g => g.group_id === state.selectedGroupId))
      state.selectedGroupId = state.groups[0]?.group_id || "";
    if (options.preserveDrafts === false) state.groupDrafts = {};
    const { syncGroupDrafts } = await import("./groups.js");
    syncGroupDrafts();
    state.history = await apiGet("web/history", {
      group_id: state.historyGroupId || undefined,
      username: state.historyUsername || undefined,
      limit: state.historyLimit, offset: state.historyOffset,
    });
    state.lastUpdated = new Date().toLocaleTimeString();
    if (els.lastUpdated) els.lastUpdated.textContent = state.lastUpdated;
    const { renderAll } = await import("./app.js");
    setBusy(false); renderAll();
    return true;
  } catch (err) { showAlert(err.message, "error"); return false; }
  finally { setBusy(false); }
}
