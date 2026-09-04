/* Single-file bundle. Do not edit core.js/groups.js/views.js — this is the only script loaded. */
'use strict';

let bridge = null;

// core.js — Infrastructure: State, API, DOM, Icons, Feedback



const state = {
  view: "overview", loading: false, actionBusy: false,
  overview: null, groups: [], groupDrafts: {}, targetProbeResults: {},
  targetBlacklists: [], targetBlacklistTarget: "",
  history: null, historyOrphans: null, selectedGroupId: "",
  historyGroupId: "", historyUsername: "", historyLimit: 10,
  historyStatus: "",
  historyOffset: 0, seenGroupId: "",
  pendingAction: null, lastFocusedElement: null, lastUpdated: "",
};

const els = {};

function initEls() {
  const ids = [
    "refreshBtn","lastUpdated","currentTabTitle","currentTabDesc","themeToggleBtn",
    "railSchedulerStatus","railScheduleStatus","railTargetStatus","alert","toastContainer",
    "overviewView","groupsView","historyView","mirrorView",
    "createGroupBtn","groupList","groupEditor",
    "historyGroupSelect","historyUsername","historyLimit","historyStatusSelect","historyRefreshBtn",
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
  home: '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M9 21v-6h6v6" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="4" cy="6" r="1" fill="currentColor"/><circle cx="4" cy="12" r="1" fill="currentColor"/><circle cx="4" cy="18" r="1" fill="currentColor"/>',
  clock: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7v5l3.5 2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  probe: '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="m20 20-3.5-3.5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>',
  user: '<circle cx="12" cy="8" r="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M4 21c0-4 4-7 8-7s8 3 8 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  hash: '<path d="M6 3v6H3v2h3v6h2v-6h4v6h2v-6h3v-2h-3V3h-2v6H8V3z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
  send: '<path d="M22 2L11 13M22 2l-7 20-4-9-9-4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>',
  refresh: '<path d="M21 12a9 9 0 11-3-6.7M21 4v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  play: '<path d="m9 6 9 6-9 6z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  plus: '<path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  check: '<path d="M9 16.2l-3.5-3.5L4 14.2 9 19l11-11-1.5-1.5z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  alert: '<path d="M12 2L1 21h22zM12 9v6m0 3v.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  close: '<path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  sun: '<circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 2v2M12 20v2M4 4l1.4 1.4M18.6 18.6L20 20M2 12h2M20 12h2M4 20l1.4-1.4M18.6 5.4L20 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  moon: '<path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="9" cy="9" r="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M21 15l-5-5L5 21" fill="none" stroke="currentColor" stroke-width="2"/>',
  video: '<rect x="2" y="6" width="14" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M16 10l6-3v10l-6-3z" fill="none" stroke="currentColor" stroke-width="2"/>',
  rss: '<path d="M4 11a9 9 0 019 9M4 4a16 16 0 0116 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="5" cy="19" r="1.5" fill="currentColor"/>',
  search: '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="m20 20-3.5-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  external: '<path d="M14 3h7v7M21 3l-9 9M19 14v5a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
};

function svgIcon(name, size = 20) {
  const path = ICONS[name] || "";
  return `<svg class="icon" viewBox="0 0 24 24" width="${size}" height="${size}" fill="currentColor" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">${path}</svg>`;
}

function iconEl(name, size = 20) {
  const wrapper = document.createElement("span");
  wrapper.innerHTML = svgIcon(name, size);
  return wrapper.firstElementChild || wrapper;
}

/* --------------------------------------------------------------------------
   DOM Builder h()
   -------------------------------------------------------------------------- */
function h(tag, props = {}, children = []) {
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
function apiResult(res) {
  if (!res || res.success === false) throw new Error((res && res.error) || "请求失败");
  return res;
}
async function apiGet(endpoint, params) {
  const q = {};
  if (params) for (const [k, v] of Object.entries(params)) { if (v != null && v !== "") q[k] = v; }
  return apiResult(await bridge.apiGet(endpoint, Object.keys(q).length ? q : undefined));
}
async function apiPost(endpoint, body) {
  return apiResult(await bridge.apiPost(endpoint, body || {}));
}

/* --------------------------------------------------------------------------
   Feedback
   -------------------------------------------------------------------------- */
function showAlert(msg, type = "success") {
  if (!els.alert) return;
  els.alert.className = `alert ${type}`;
  els.alert.textContent = msg;
  els.alert.hidden = false;
}
function hideAlert() { if (els.alert) { els.alert.hidden = true; els.alert.textContent = ""; } }
function showToast(msg) {
  if (!els.toastContainer) return;
  const t = h("div", { class: "toast", text: msg });
  els.toastContainer.appendChild(t);
  setTimeout(() => t.remove(), 2800);
}
function parsePushedAt(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return NaN;
  const t = /^\d{9,}$/.test(s) ? Number(s) : new Date(s.replace(" ", "T")).getTime();
  if (!Number.isFinite(t) || t <= 0) return NaN;
  // Backend stores Unix seconds; values below 1e12 (year ~2001 in ms) are seconds.
  return t < 1e12 ? t * 1000 : t;
}
function relativeTime(raw) {
  const t = parsePushedAt(raw);
  if (Number.isNaN(t)) return String(raw ?? "");
  const diff = Date.now() - t;
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 30 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  return formatDateTime(raw);
}
function formatDateTime(raw) {
  const t = parsePushedAt(raw);
  if (Number.isNaN(t)) return String(raw ?? "");
  const d = new Date(t);
  const p = x => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function setBusy(isBusy) {
  state.loading = isBusy;
  [els.refreshBtn, els.createGroupBtn, els.historyRefreshBtn, els.historyOrphanBtn,
   els.historyPrevBtn, els.historyNextBtn, els.mirrorProbeBtn].forEach(b => { if (b) b.disabled = isBusy || state.actionBusy; });
}

/* --------------------------------------------------------------------------
   Confirm Dialog
   -------------------------------------------------------------------------- */
function openConfirm({ title, desc, confirmText = "确认", danger = false, action }) {
  state.lastFocusedElement = document.activeElement;
  state.pendingAction = action;
  els.confirmTitle.textContent = title || "确认操作？";
  els.confirmDesc.replaceChildren(typeof desc === "string" ? document.createTextNode(desc) : desc);
  els.confirmActionBtn.textContent = confirmText;
  els.confirmActionBtn.className = `btn btn-sm ${danger ? "btn-danger" : "btn-primary"}`;
  els.confirmDialog.hidden = false;
  els.confirmActionBtn.focus();
}
function closeConfirm() {
  els.confirmDialog.hidden = true;
  state.pendingAction = null;
  if (state.lastFocusedElement?.focus) state.lastFocusedElement.focus();
}

/* --------------------------------------------------------------------------
   Theme
   -------------------------------------------------------------------------- */
function initTheme() {
  const context = bridge?.getContext?.() || {};
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  applyTheme(typeof context.isDark === "boolean" ? context.isDark : prefersDark);
  bridge?.onContext?.(nextContext => {
    if (typeof nextContext?.isDark === "boolean") applyTheme(nextContext.isDark);
  });
}
function applyTheme(isDark) {
  document.body.classList.toggle("dark-theme", !!isDark);
  document.body.classList.toggle("light-theme", !isDark);
}
function toggleTheme() {
  applyTheme(!document.body.classList.contains("dark-theme"));
}

/* --------------------------------------------------------------------------
   Action wrapper & reloadAll (deferred imports to avoid circular)
   -------------------------------------------------------------------------- */
async function withAction(action, successText, { reload = true, rerender = null } = {}) {
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

async function reloadAll(options = {}) {
  setBusy(true); hideAlert();
  renderAll();
  try {
    await bridge.ready();
    const [ov, gr, bl] = await Promise.allSettled([
      apiGet("web/overview"), apiGet("web/groups"), apiGet("web/target-blacklists"),
    ]);
    const errors = [];
    if (ov.status === "fulfilled") state.overview = ov.value;
    else errors.push(`概览加载失败：${ov.reason?.message || "请求失败"}`);
    if (gr.status === "fulfilled") state.groups = gr.value.groups || [];
    else errors.push(`分组加载失败：${gr.reason?.message || "请求失败"}`);
    if (bl.status === "fulfilled") state.targetBlacklists = bl.value.target_blacklists || [];
    else errors.push(`黑名单加载失败：${bl.reason?.message || "请求失败"}`);
    if (!state.selectedGroupId || !state.groups.some(g => g.group_id === state.selectedGroupId))
      state.selectedGroupId = state.groups[0]?.group_id || "";
    if (options.preserveDrafts === false) state.groupDrafts = {};
    syncGroupDrafts();
    try {
      state.history = await apiGet("web/history", {
        group_id: state.historyGroupId || undefined,
        username: state.historyUsername || undefined,
        limit: state.historyLimit, offset: state.historyOffset,
        status: state.historyStatus || undefined,
      });
    } catch (err) {
      errors.push(`历史加载失败：${err.message || "请求失败"}`);
      if (!state.history) state.history = { records: [], total_count: 0, total_pages: 1, page: 1 };
    }
    state.lastUpdated = new Date().toLocaleTimeString();
    if (els.lastUpdated) els.lastUpdated.textContent = state.lastUpdated;
    renderAll();
    if (errors.length) showAlert(`部分数据未加载：${errors.join("；")}`, "warn");
    return errors.length === 0;
  } catch (err) { showAlert(err.message, "error"); return false; }
  finally { setBusy(false); }
}
;// groups.js — Group List, Editor, Draft System & Subscriptions

const EDITABLE_FIELDS = [
  "name","enabled","interval_check_enabled","daily_check_times",
  "filter_reposts_enabled","filter_plain_text_enabled","media_only_enabled",
  "omit_status_url","hide_original_when_translated",
  "push_targets","watch_users","watch_queries","watch_lists",
];

function snapshotGroup(group) {
  if (!group) return null;
  const snap = {};
  for (const f of EDITABLE_FIELDS) {
    if (f === "watch_lists") {
      snap.watch_lists = [...(group.watch_lists || [])];
    } else if (f === "filter_reposts_enabled") {
      snap.filter_reposts_enabled = group.filter_reposts_enabled !== false;
    } else if (f === "daily_check_times" || f === "push_targets" || f === "watch_users") {
      snap[f] = Array.isArray(group[f]) ? [...group[f]] : [];
    } else if (f === "watch_queries") {
      snap[f] = Array.isArray(group[f]) ? group[f].map(q => typeof q === "string" ? { query: q, type: "tag" } : { query: q.query, type: q.type || "tag" }) : [];
    } else if (["enabled","interval_check_enabled","filter_plain_text_enabled","media_only_enabled","omit_status_url","hide_original_when_translated"].includes(f)) {
      snap[f] = !!group[f];
    } else { snap[f] = group[f] || ""; }
  }
  snap.group_id = group.group_id; snap.group_type = group.group_type;
  return snap;
}

function syncGroupDrafts() {
  for (const g of state.groups) {
    if (!state.groupDrafts[g.group_id]) state.groupDrafts[g.group_id] = snapshotGroup(g);
  }
}

function isGroupDirty(groupId) {
  const g = state.groups.find(x => x.group_id === groupId);
  const d = state.groupDrafts[groupId];
  if (!g || !d) return false;
  return JSON.stringify(snapshotGroup(g)) !== JSON.stringify(d);
}

function updateDraft(groupId, field, val) {
  const d = state.groupDrafts[groupId]; if (!d) return;
  d[field] = val; renderGroupList(); updateEditorControls(groupId);
}

/* --------------------------------------------------------------------------
   Group List
   -------------------------------------------------------------------------- */
function renderGroupList() {
  if (!els.groupList) return;
  if (!state.groups.length) {
    els.groupList.replaceChildren(h("div", { class: "panel", style: { textAlign: "center", color: "var(--text-muted)" }, text: "暂无分组" }));
    return;
  }
  els.groupList.replaceChildren(...state.groups.map(g => {
    const active = g.group_id === state.selectedGroupId;
    const dirty = isGroupDirty(g.group_id);
    const icon = g.group_type === "tag" ? "hash" : g.group_type === "list" ? "rss" : "user";
    const label = g.group_type === "tag" ? "搜索" : g.group_type === "list" ? "List" : "博主";
    return h("div", {
      class: `group-item ${active ? "active" : ""}`,
      onClick: () => selectGroup(g.group_id),
    }, [
      h("div", { class: "group-item-row" }, [
        h("span", { style: { display: "flex", alignItems: "center", gap: "6px" }, html: svgIcon(icon, 16), text: (state.groupDrafts[g.group_id]?.name) || g.name }),
        dirty ? h("span", { class: "badge badge-warn", text: "未保存" }) : null,
      ]),
      h("div", { class: "group-item-meta" }, [
        h("span", { class: "badge badge-blue", text: label }),
        h("span", { class: "mono", text: g.group_id }),
        !g.enabled ? h("span", { class: "badge", text: "停用" }) : null,
      ]),
    ]);
  }));
}

function selectGroup(gid, { force = false } = {}) {
  const prev = state.groups.find(g => g.group_id === state.selectedGroupId);
  if (!force && prev && isGroupDirty(state.selectedGroupId)) {
    openConfirm({
      title: "丢弃未保存的更改？",
      desc: "当前分组的修改尚未保存，切换后将丢失。",
      confirmText: "丢弃并切换", danger: true,
      action: () => {
        state.groupDrafts[prev.group_id] = snapshotGroup(prev);
        selectGroup(gid, { force: true });
      },
    });
    return;
  }
  state.selectedGroupId = gid; renderGroupList(); renderGroupEditor();
}

/* --------------------------------------------------------------------------
   Group Editor
   -------------------------------------------------------------------------- */
function updateEditorControls(gid) {
  const g = state.groups.find(x => x.group_id === gid); if (!g) return;
  const dirty = isGroupDirty(gid);
  const save = document.getElementById("saveGroupBtn");
  if (save) save.disabled = !dirty;
  const chk = document.getElementById("checkGroupBtn");
  if (chk) { chk.disabled = !g.enabled || dirty; chk.title = !g.enabled ? "分组停用" : dirty ? "请先保存" : ""; }
}

function renderGroupEditor() {
  if (!els.groupEditor) return;
  const g = state.groups.find(x => x.group_id === state.selectedGroupId);
  if (!g) { els.groupEditor.replaceChildren(h("div", { class: "panel", style: { textAlign: "center", color: "var(--text-muted)" }, text: "请选择一个分组" })); return; }
  const d = state.groupDrafts[g.group_id] || snapshotGroup(g);
  const dirty = isGroupDirty(g.group_id);

  // Head
  const head = h("div", { class: "panel-head" }, [
    h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, [
      h("h2", { text: d.name || g.name }),
      h("span", { class: `badge ${d.enabled ? "badge-ok" : "badge-warn"}`, text: d.enabled ? "启用" : "停用" }),
      h("span", { class: "mono", style: { color: "var(--text-muted)" }, text: g.group_id }),
    ]),
    h("div", { style: { display: "flex", gap: "6px" } }, [
      h("button", { id: "checkGroupBtn", class: "btn btn-sm", html: svgIcon("play", 14), text: "检查", disabled: !g.enabled || dirty, onClick: () => runCheck(g.group_id) }),
      h("button", { id: "saveGroupBtn", class: "btn btn-sm btn-primary", text: "保存", disabled: !dirty, onClick: () => saveGroup(g.group_id) }),
      g.group_id !== "default" ? h("button", { class: "btn btn-sm btn-danger", html: svgIcon("trash", 14), text: "删除", onClick: () => confirmDeleteGroup(g.group_id) }) : null,
    ]),
  ]);

  // Base config
  const base = h("div", { class: "editor-grid" }, [
    h("label", { class: "field" }, [
      h("span", { text: "分组名称" }),
      h("input", { type: "text", value: d.name, onInput: e => updateDraft(g.group_id, "name", e.target.value.trim()) }),
    ]),
    h("div", { style: { display: "flex", alignItems: "flex-end" } }, [
      h("label", { class: "toggle" }, [
        h("input", { type: "checkbox", checked: d.enabled, onChange: e => updateDraft(g.group_id, "enabled", e.target.checked) }),
        h("span", { class: "toggle-track" }),
        h("span", { text: "启用此分组" }),
      ]),
    ]),
  ]);

  // Policy toggles
  const policy = h("div", { class: "editor-grid" }, [
    toggleRow(d.filter_reposts_enabled, "过滤转发（需同时开启全局转发过滤总开关）", v => updateDraft(g.group_id, "filter_reposts_enabled", v)),
    toggleRow(d.filter_plain_text_enabled, "过滤纯文本（仅有媒体推文才推送）", v => updateDraft(g.group_id, "filter_plain_text_enabled", v)),
    toggleRow(d.interval_check_enabled, "开启定时循环间隔检查", v => updateDraft(g.group_id, "interval_check_enabled", v)),
    h("label", { class: "field editor-grid-full" }, [
      h("span", { text: "每日定时触发时间（逗号或换行分隔，如 08:00, 20:00）" }),
      h("input", { type: "text", value: (d.daily_check_times || []).join(", "), onInput: e => {
        const tokens = e.target.value.split(/[,，\s]+/).filter(Boolean);
        const valid = tokens
          .filter(t => /^([01]?\d|2[0-3]):[0-5]\d$/.test(t))
          .map(t => (t.length === 4 ? "0" + t : t));
        const hint = document.getElementById("dailyTimesHint");
        if (hint) {
          const dropped = tokens.length !== valid.length;
          hint.textContent = dropped ? "存在无效时间（格式 HH:MM），已忽略" : "";
          hint.style.display = dropped ? "" : "none";
        }
        updateDraft(g.group_id, "daily_check_times", valid);
      } }),
      h("span", { id: "dailyTimesHint", class: "field-error", style: { display: "none" } }),
    ]),
  ]);

  // Subscription entities section
  const entities = renderEntities(g, d);
  // Push targets section
  const targets = renderTargets(g, d);

  els.groupEditor.replaceChildren(h("div", { class: "panel" }, [
    head, base, policy, entities, targets,
  ]));
}

function toggleRow(checked, label, onChange) {
  return h("label", { class: "toggle" }, [
    h("input", { type: "checkbox", checked, onChange: e => onChange(e.target.checked) }),
    h("span", { class: "toggle-track" }),
    h("span", { text: label }),
  ]);
}

function renderEntities(group, draft) {
  const isTag = group.group_type === "tag";
  const isList = group.group_type === "list";
  const icon = isTag ? "hash" : isList ? "rss" : "user";
  const label = isTag ? "搜索查询词" : isList ? "Twitter List ID" : "博主用户名";
  const list = isTag ? draft.watch_queries : isList ? draft.watch_lists : draft.watch_users;

  return h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } }, [
    h("div", { style: { display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, fontSize: "13px", color: "var(--text-muted)" } }, [
      iconEl(icon, 16), `订阅源 — ${label}`,
    ]),
    h("div", { class: "chip-list" },
      (list || []).map((item, idx) => {
        const val = typeof item === "object" ? item.query : item;
        return h("span", { class: "chip mono" }, [
          iconEl(icon, 12), val,
          h("button", { class: "btn-icon", title: "移除", style: { width: "24px", height: "24px" }, html: svgIcon("close", 12), onClick: () => {
            const next = [...list]; next.splice(idx, 1);
            updateDraft(group.group_id, isTag ? "watch_queries" : isList ? "watch_lists" : "watch_users", next);
            renderGroupEditor();
          }}),
        ]);
      })
    ),
    h("div", { style: { display: "flex", gap: "6px" } }, [
      h("input", { id: isList ? "newWatchListInput" : "newEntityInput", type: "text", placeholder: isTag ? "#tag 或关键词" : isList ? "纯数字 List ID" : "推特用户名", style: { width: "240px" }, onInput: () => {
        const err = document.getElementById("entityError");
        if (err) err.style.display = "none";
      } }),
      h("button", { class: "btn btn-sm", html: svgIcon("plus", 14), text: "添加", onClick: () => {
        if (isList) { addWatchList(group.group_id); }
        else {
          const inp = document.getElementById("newEntityInput");
          const v = inp?.value.trim(); if (!v) return;
          const next = [...(list || [])];
          if (isTag) next.push({ query: v, type: "tag" }); else next.push(v);
          updateDraft(group.group_id, isTag ? "watch_queries" : "watch_lists", next);
          renderGroupEditor();
        }
      }}),
    ]),
    isList ? h("span", { id: "entityError", class: "field-error", style: { display: "none" } }) : null,
  ]);
}

function renderTargets(group, draft) {
  const targets = draft.push_targets || [];
  const probe = state.targetProbeResults[group.group_id];

  return h("div", { style: { display: "flex", flexDirection: "column", gap: "8px", borderTop: "1px solid var(--border)", paddingTop: "12px" } }, [
    h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } }, [
      h("span", { style: { display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, fontSize: "13px", color: "var(--text-muted)" } }, [iconEl("send", 16), "推送目标 (UMO)"]),
      h("button", { class: "btn btn-sm btn-ghost", html: svgIcon("probe", 14), text: "测试连通性", disabled: !targets.length, onClick: () => probeTargets(group.group_id) }),
    ]),
    h("div", { class: "chip-list" },
      targets.map((t, idx) => {
        const info = probe?.targets?.find(x => x.umo === t);
        return h("span", { class: "chip mono" }, [
          t,
          info ? h("span", { class: `badge ${info.valid ? "badge-ok" : "badge-danger"}`, text: info.platform_kind || (info.valid ? "有效" : "失败") }) : null,
          h("button", { class: "btn-icon", title: "移除", style: { width: "24px", height: "24px" }, html: svgIcon("close", 12), onClick: () => {
            const next = [...targets]; next.splice(idx, 1);
            updateDraft(group.group_id, "push_targets", next); renderGroupEditor();
          }}),
        ]);
      })
    ),
    h("div", { style: { display: "flex", gap: "6px" } }, [
      h("input", { id: "newTargetInput", type: "text", placeholder: "aiocqhttp:GroupMessage:123456", style: { width: "320px" } }),
      h("button", { class: "btn btn-sm", html: svgIcon("plus", 14), text: "添加", onClick: () => {
        const inp = document.getElementById("newTargetInput");
        const v = inp?.value.trim(); if (!v) return;
        updateDraft(group.group_id, "push_targets", [...targets, v]); renderGroupEditor();
      }}),
    ]),
  ]);
}

function addWatchList(groupId) {
  const inp = document.getElementById("newWatchListInput");
  const err = document.getElementById("entityError");
  const showError = msg => {
    if (err) { err.textContent = msg; err.style.display = ""; }
    else showToast(msg);
  };
  const val = inp?.value.trim(); if (!val) return;
  if (!/^\d{1,20}$/.test(val)) { showError("List ID 必须是 1-20 位正整数"); return; }
  const d = state.groupDrafts[groupId]; if (!d) return;
  if ((d.watch_lists || []).includes(val)) { showError("List ID 已存在"); return; }
  if (err) err.style.display = "none";
  updateDraft(groupId, "watch_lists", [...(d.watch_lists || []), val]); renderGroupEditor();
}

/* --------------------------------------------------------------------------
   Actions
   -------------------------------------------------------------------------- */
function createGroup() {
  const nameInput = h("input", { type: "text", value: "新订阅分组", style: { width: "100%", marginBottom: "10px" } });
  const options = [
    { value: "blogger", label: "博主分组" },
    { value: "tag", label: "搜索订阅分组" },
    { value: "list", label: "List 分组" },
  ];
  const radioBox = h("div", { class: "group-type-options", style: { display: "flex", flexDirection: "column", gap: "6px" } },
    options.map(opt => h("label", { style: { display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", cursor: "pointer" } }, [
      h("input", { type: "radio", name: "createGroupType", value: opt.value, checked: opt.value === "blogger" }),
      h("span", { text: opt.label }),
    ]))
  );
  openConfirm({
    title: "新建订阅分组",
    desc: h("div", {}, [h("div", { text: "分组名称：", style: { marginBottom: "4px", fontSize: "13px" } }), nameInput, h("div", { text: "选择类型：", style: { marginBottom: "4px", fontSize: "13px" } }), radioBox]),
    confirmText: "创建",
    action: () => withAction(async () => {
      const sel = radioBox.querySelector('input[name="createGroupType"]:checked');
      const gType = sel?.value || "blogger";
      const name = nameInput.value.trim() || "新订阅分组";
      const res = await apiPost("web/groups/create", { name, group_type: gType });
      if (res?.group) state.selectedGroupId = res.group.group_id;
    }, "分组创建成功"),
  });
}

async function saveGroup(gid) {
  const d = state.groupDrafts[gid]; if (!d) return;
  await withAction(async () => {
    await apiPost("web/groups/update", d);
    delete state.groupDrafts[gid];
  }, "分组保存成功");
}

function confirmDeleteGroup(gid) {
  openConfirm({
    title: `删除分组 [${gid}]？`,
    desc: "此操作不可恢复，订阅规则与历史关联将被清理。",
    danger: true,
    action: () => withAction(async () => {
      await apiPost("web/groups/delete", { group_id: gid, force: true, confirm: "DELETE" });
      state.selectedGroupId = "";
    }, "分组已删除"),
  });
}

async function runCheck(gid) {
  await withAction(() => apiPost("web/check", { group_id: gid }), "检查完成");
}

async function probeTargets(gid) {
  await withAction(async () => {
    const res = await apiPost("web/targets/probe", { group_id: gid });
    state.targetProbeResults[gid] = res; renderGroupEditor();
  }, "探测完成", { reload: false });
}
;// views.js — Overview, Tweet-feed History, Probe & Danger Zone

/* --------------------------------------------------------------------------
   Rail Health Status
   -------------------------------------------------------------------------- */
function renderRailStatus() {
  const p = state.overview; if (!p) return;
  const s = p.scheduler || {}; const c = p.counts || {};
  setRailPill("railSchedulerStatus", s.running ? "ok" : "warn", s.running ? "运行中" : "未启动");
  setRailPill("railScheduleStatus", s.schedule_enabled ? "ok" : "warn", s.schedule_enabled ? "已开启" : "已关闭");
  const inv = c.invalid_push_targets || 0;
  setRailPill("railTargetStatus", inv > 0 ? "danger" : "ok", inv > 0 ? `${inv} 异常` : "正常");
}
function setRailPill(id, cls, text) {
  const el = els[id]; if (!el) return;
  el.className = `pill-status pill-${cls}`;
  el.replaceChildren(h("span", { class: "dot" }), h("span", { text }));
}

/* --------------------------------------------------------------------------
   Overview
   -------------------------------------------------------------------------- */
function renderOverview() {
  const root = els.overviewView; if (!root) return;
  const p = state.overview;
  if (!p) { root.replaceChildren(h("div", { class: "panel", text: "正在加载..." })); return; }
  const c = p.counts || {}; const s = p.scheduler || {};
  const cfg = p.config_summary || {}; const inst = p.instances || [];
  const att = p.attention_items || [];

  // Metric cards with icons
  const metrics = h("div", { class: "metrics-grid" }, [
    metric("home", "调度器", s.running ? "运行中" : "已停用"),
    metric("list", "启用分组", `${c.enabled_groups || 0} / ${c.groups || 0}`),
    metric("user", "博主订阅", c.watch_users || 0),
    metric("hash", "搜索订阅", c.watch_queries || 0),
    metric("rss", "List 订阅", c.watch_lists || 0),
    metric("send", "推送目标", c.push_targets || 0),
  ]);

  // Attention items
  const attPanel = att.length ? h("div", { class: "panel" }, [
    h("div", { class: "panel-head" }, [
      h("h3", { text: "需要关注" }),
      h("span", { class: "badge badge-warn", text: `${att.length} 项` }),
    ]),
    ...att.map(item => h("div", {
      class: `alert-item ${item.level === "error" ? "danger" : item.level === "warn" ? "warn" : "info"}`,
    }, [
      h("span", {}, [
        h("strong", { text: `${item.title || ""}: ` }),
        item.detail || "",
      ]),
      item.group_id ? h("button", {
        class: "btn btn-ghost btn-sm",
        html: svgIcon("external", 14),
        onClick: () => { state.selectedGroupId = item.group_id; document.querySelector('[data-view="groups"]')?.click(); },
      }) : null,
    ])),
  ]) : null;

  // Instance & config summary
  const configPanel = h("div", { class: "panel" }, [
    h("div", { class: "panel-head" }, [h("h3", { text: "实例与配置" })]),
    h("div", { style: { display: "flex", flexWrap: "wrap", gap: "10px" } }, [
      h("div", { class: "field", style: { flex: "1 1 260px" } }, [
        h("span", { text: "已配置 Nitter 实例" }),
        inst.length
          ? h("div", { class: "chip-list" }, inst.map(u => h("span", { class: "chip mono chip-action", text: u, onClick: () => { if (els.mirrorInstance) els.mirrorInstance.value = u; document.querySelector('[data-view="mirror"]')?.click(); } })))
          : h("span", { class: "badge badge-warn", text: "未配置任何实例" }),
      ]),
      h("div", { class: "field", style: { flex: "1 1 200px" } }, [
        h("span", { text: "调度参数" }),
        h("div", { class: "chip-list" }, [
          badge(`检查间隔 ${cfg.check_interval_minutes || 0}m`),
          badge(`合并阈值 ${cfg.merge_tweet_threshold || 0}`),
          badge(`目标间隔 ${cfg.send_target_interval || 0}s`),
          badge(`并发 ${cfg.concurrent_fetch_enabled ? "开" : "关"}`),
        ]),
      ]),
    ]),
  ]);

  // Danger zone
  const dz = h("div", { class: "panel danger-zone" }, [
    h("div", { class: "panel-head" }, [
      h("h3", { text: "维护与缓存清理" }),
      h("span", { class: "badge badge-danger", text: "不可逆" }),
    ]),
    h("div", { class: "danger-grid" }, [
      h("div", { class: "danger-item" }, [
        h("h4", { text: "清理媒体缓存" }),
        h("p", { text: "删除临时下载的图片与视频附件" }),
        h("div", { class: "actions" }, [
          h("button", { class: "btn btn-danger btn-sm", text: "清理", onClick: confirmClearCache }),
        ]),
      ]),
      h("div", { class: "danger-item" }, [
        h("h4", { text: "重置推送记录 (Seen)" }),
        h("p", { text: "可能导致历史推文再次推送" }),
        h("div", { class: "actions" }, [
          h("select", { id: "seenSelect", style: { width: "auto" } }, [
            h("option", { value: "", text: "全部分组" }),
            ...state.groups.map(g => h("option", { value: g.group_id, text: g.name })),
          ]),
          h("button", { class: "btn btn-danger btn-sm", text: "重置", onClick: confirmClearSeen }),
        ]),
      ]),
    ]),
  ]);

  root.replaceChildren(metrics, ...(attPanel ? [attPanel] : []), configPanel, dz);
}

function metric(icon, label, value) {
  return h("div", { class: "metric" }, [
    h("div", { class: "metric-icon", html: svgIcon(icon, 16) }),
    h("div", { class: "metric-text" }, [
      h("span", { class: "metric-label", text: label }),
      h("span", { class: "metric-value", text: String(value) }),
    ]),
  ]);
}
function badge(text) { return h("span", { class: "badge", text }); }

/* --------------------------------------------------------------------------
   History — Tweet-style Feed
   -------------------------------------------------------------------------- */
function renderHistory() {
  const root = els.historyView; if (!root) return;
  const data = state.history;
  const recs = (data && data.records) || [];

  // Sync group dropdown
  if (els.historyGroupSelect && !els.historyGroupSelect.children.length) {
    els.historyGroupSelect.replaceChildren(
      h("option", { value: "", text: "所有分组" }),
      ...state.groups.map(g => h("option", { value: g.group_id, text: g.name })),
    );
  }
  // Pager
  if (els.historyPageLabel && data) {
    els.historyPageLabel.textContent = `${data.page || 1} / ${data.total_pages || 1} 页 · 共 ${data.total_count || 0} 条`;
  }
  if (els.historyPrevBtn && data) els.historyPrevBtn.disabled = !data.has_prev;
  if (els.historyNextBtn && data) els.historyNextBtn.disabled = !data.has_next;

  const content = els.historyContent;
  if (!recs.length) {
    content.replaceChildren(h("div", { class: "panel", style: { textAlign: "center", color: "var(--text-muted)", padding: "32px" }, text: "暂无推送历史记录" }));
    return;
  }

  content.replaceChildren(...recs.map(r => {
    const st = r.delivery_status;
    const stBadge = h("span", { class: `badge ${st === "success" ? "badge-ok" : st === "partial_failed" ? "badge-warn" : "badge-danger"}`, text: st === "success" ? "已送达" : st === "partial_failed" ? "部分失败" : "发送失败" });
    const hasMedia = !!r.has_media;

    return h("div", { class: "tweet-card" }, [
      // Avatar placeholder
      h("div", { class: "tweet-avatar", html: svgIcon("user", 20) }),
      h("div", { class: "tweet-body" }, [
        // Meta line: @handle · time · status
        h("div", { class: "tweet-meta" }, [
          h("span", { class: "tweet-author", text: r.username || "unknown" }),
          h("span", { class: "tweet-handle mono", text: `@${r.username || "unknown"}` }),
          h("span", { text: "·" }),
          h("span", { class: "tweet-time mono", text: relativeTime(r.pushed_at), title: formatDateTime(r.pushed_at) || (r.pushed_at || "-") }),
          stBadge,
        ]),
        // Tweet text
        h("div", { class: "tweet-text" }, [
          r.original_link ? h("a", { href: r.original_link, target: "_blank", rel: "noopener noreferrer", class: "mono", text: r.status_id, style: { marginRight: "6px", fontWeight: "600" } }) : null,
          r.text_preview || "(无文字内容)",
        ]),
        // Footer: media badge + actions
        h("div", { class: "tweet-footer" }, [
          h("span", { class: "tweet-meta-badge" }, [
            iconEl("list", 14), `${r.group_name || r.group_id}`,
          ]),
          hasMedia ? h("span", { class: "tweet-meta-badge" }, [
            iconEl("image", 14), "含媒体",
          ]) : null,
          h("div", { class: "tweet-actions" }, [
            h("button", {
              class: "btn btn-ghost btn-sm",
              html: iconEl("refresh", 14).outerHTML,
              text: "重推",
              onClick: () => replayHistory(r.id, r.replay_target_options),
            }),
          ]),
        ]),
      ]),
    ]);
  }));
}

async function loadHistoryPage(delta) {
  if (!state.history) return;
  const offset = delta < 0 ? state.history.prev_offset : state.history.next_offset;
  if (offset === null || offset === undefined) return;
  state.historyOffset = offset;
  await withAction(async () => {
    state.history = await apiGet("web/history", {
      group_id: state.historyGroupId || undefined,
      username: state.historyUsername || undefined,
      limit: state.historyLimit, offset: state.historyOffset,
      status: state.historyStatus || undefined,
    });
    renderHistory();
  }, "翻页完成", { reload: false });
}

async function detectHistoryOrphans() {
  await withAction(async () => {
    const res = await apiGet("web/history/orphans");
    const ops = res.orphans || [];
    if (!ops.length) {
      els.historyOrphanResult.replaceChildren(h("div", { class: "badge badge-ok", text: "未检测到废弃分组的残留历史" }));
      return;
    }
    els.historyOrphanResult.replaceChildren(h("div", { class: "panel" }, [
      h("div", { class: "panel-head" }, [h("h3", { text: `废弃分组残留 (${ops.length})` })]),
      h("div", { class: "chip-list" }, ops.map(o => h("span", { class: "chip mono" }, [
        `${o.group_id} (${o.record_count}条)`,
        h("button", { class: "btn btn-danger btn-sm", text: "删除", onClick: () => confirmDeleteOrphan(o.group_id) }),
      ]))),
    ]));
  }, "检测完成", { reload: false });
}

function confirmDeleteOrphan(gid) {
  openConfirm({
    title: `删除废弃分组 [${gid}] 历史？`,
    desc: "该分组已不存在，删除后相关记录彻底清除。",
    danger: true,
    action: () => withAction(() => apiPost("web/history/orphans/delete", { group_id: gid, confirm: "DELETE" }), "删除成功", { reload: false, rerender: detectHistoryOrphans }),
  });
}

function replayHistory(id, options) {
  let box = null;
  let desc;
  if (Array.isArray(options) && options.length) {
    box = h("div", { style: { display: "flex", flexDirection: "column", gap: "6px", maxHeight: "220px", overflowY: "auto", marginTop: "10px" } },
      options.map(o => h("label", { style: { display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" } }, [
        h("input", { type: "checkbox", checked: !!o.available, disabled: !o.available, value: o.umo || "" }),
        h("span", { class: "mono", text: `${o.umo || "未知目标"}${o.available ? "" : "（已下线）"}` }),
      ])));
    desc = h("div", {}, [h("div", { text: "选择重推目标（已下线目标不可选）：" }), box]);
  } else {
    desc = "将重推至当前分组目标";
  }
  openConfirm({
    title: "重推此推文",
    desc,
    confirmText: "重推",
    action: () => {
      if (!box) return withAction(() => apiPost("web/history/replay", { record_id: id }), "重推已触发");
      const umos = [...box.querySelectorAll('input:checked')].map(i => i.value).filter(Boolean);
      if (!umos.length) { showToast("未选择目标，已取消重推"); return undefined; }
      return withAction(() => apiPost("web/history/replay", { record_id: id, target_umos: umos }), "重推已触发");
    },
  });
}

/* --------------------------------------------------------------------------
   Mirror Probe
   -------------------------------------------------------------------------- */
function renderMirrorBase() {
  if (!els.instanceList) return;
  const inst = (state.overview && state.overview.instances) || [];
  if (!inst.length) {
    els.instanceList.replaceChildren(h("span", { class: "badge badge-warn", text: "无已配置实例" }));
    return;
  }
  els.instanceList.replaceChildren(...inst.map(u => h("button", {
    class: "chip chip-action mono", text: u,
    onClick: () => { if (els.mirrorInstance) els.mirrorInstance.value = u; },
  })));
}

async function probeMirror(e) {
  if (e) e.preventDefault();
  if (state.actionBusy) return;
  const payload = {
    username: els.mirrorUsername.value.trim() || "nasa",
    query: els.mirrorQuery.value.trim() || "nasa",
    list_id: els.mirrorListId.value.trim() || undefined,
    limit: parseInt(els.mirrorLimit.value, 10) || 5,
    instance: els.mirrorInstance.value.trim() || undefined,
  };
  state.actionBusy = true; setBusy(true);
  els.mirrorResult.replaceChildren(h("div", { class: "panel", text: "探测中..." }));
  try {
    const res = await apiPost("web/mirror/probe", payload);
    const results = res.results || [];
    if (!results.length) {
      els.mirrorResult.replaceChildren(h("div", { class: "panel", text: "未返回结果" }));
      return;
    }
    els.mirrorResult.replaceChildren(...results.map(r => {
      const checks = r.checks || {};
      return h("div", { class: "probe-result" }, [
        h("div", { class: "probe-instance-head" }, [
          h("span", { class: "mono", style: { fontWeight: 700 }, text: r.instance }),
          h("span", { class: `badge ${r.success ? "badge-ok" : "badge-danger"}`, text: r.success ? "全部可用" : "有异常" }),
        ]),
        h("div", { class: "probe-checks" }, [
          probeCheck("RSS", checks.rss_user),
          probeCheck("HTML", checks.html_user),
          probeCheck("搜索", checks.search),
          checks.list ? probeCheck("List", checks.list) : null,
        ]),
      ]);
    }));
  } catch (err) {
    els.mirrorResult.replaceChildren(h("div", { class: "alert error", text: `探测失败: ${err.message}` }));
  } finally {
    state.actionBusy = false; setBusy(false);
  }
}

function probeCheck(label, item) {
  if (!item) return null;
  const ok = item.success;
  return h("div", { class: `probe-check ${ok ? "ok" : "fail"}` }, [
    iconEl(ok ? "check" : "alert", 14),
    h("span", { text: label }),
    ok ? h("span", { text: `${item.tweet_count || 0}条 ${Math.round(item.duration_ms || 0)}ms` }) : h("span", { text: item.error || "失败", style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }),
  ]);
}

/* --------------------------------------------------------------------------
   Cleanup Actions
   -------------------------------------------------------------------------- */
function confirmClearCache() {
  openConfirm({
    title: "清理媒体缓存？", desc: "删除临时下载的图片与视频附件，不影响推送记录。",
    danger: true,
    action: () => withAction(async () => {
      const res = await apiPost("web/cache/clear");
      return { message: `缓存清理完毕: 删除 ${res.result?.removed || 0} 个文件` };
    }, "缓存已清理"),
  });
}

function confirmClearSeen() {
  const sel = document.getElementById("seenSelect");
  const gid = sel ? sel.value : "";
  const isAll = !gid;
  openConfirm({
    title: isAll ? "重置全部推送记录？" : `重置分组 [${gid}] 推送记录？`,
    desc: "重置后下次检查可能将当前推文视为未推送，可能导致重复发送。",
    danger: true, confirmText: "确认重置",
    action: () => withAction(() => apiPost("web/seen/clear", isAll ? { confirm: "CLEAR_ALL" } : { group_id: gid }), "推送记录已重置"),
  });
}
;// app.js — Entry: routing, boot, event binding

const VIEW_META = {
  overview: { title: "控制台总览", desc: "运行状态、订阅摘要与系统维护" },
  groups: { title: "分组订阅管理", desc: "维护博主、搜索与 List 规则" },
  history: { title: "推送历史", desc: "查看送达状态并重推" },
  mirror: { title: "实例能力诊断", desc: "测试 Nitter 实例连通性" },
};

function renderAll() {
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

function switchView(v) {
  if (!v || state.view === v) return;
  state.view = v;
  els.tabs.forEach(t => t.classList.toggle("active", t.dataset.view === v));
  els.views.forEach(s => s.classList.toggle("active", s.id === `${v}View`));
  renderAll();
}

function bindEvents() {
  els.tabs.forEach(tab => tab.addEventListener("click", () => switchView(tab.dataset.view)));
  els.refreshBtn?.addEventListener("click", () => {
    const dirty = state.groups.some(g => isGroupDirty(g.group_id));
    if (!dirty) return reloadAll({ preserveDrafts: false });
    openConfirm({
      title: "刷新将丢弃未保存的修改？",
      desc: "当前有分组的编辑尚未保存，刷新后这些修改将丢失。",
      confirmText: "丢弃并刷新", danger: true,
      action: () => reloadAll({ preserveDrafts: false }),
    });
  });
  els.themeToggleBtn?.addEventListener("click", toggleTheme);
  els.createGroupBtn?.addEventListener("click", createGroup);

  els.historyRefreshBtn?.addEventListener("click", async () => {
    state.historyGroupId = els.historyGroupSelect.value;
    state.historyUsername = els.historyUsername.value.trim();
    state.historyLimit = parseInt(els.historyLimit.value, 10) || 10;
    state.historyStatus = els.historyStatusSelect ? els.historyStatusSelect.value : "";
    state.historyOffset = 0; // 重置页码
    await withAction(async () => {
      state.history = await apiGet("web/history", {
        group_id: state.historyGroupId || undefined,
        username: state.historyUsername || undefined,
        limit: state.historyLimit, offset: state.historyOffset,
        status: state.historyStatus || undefined,
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
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closeConfirm();
    if (e.key !== "Tab" || els.confirmDialog?.hidden) return;
    const focusable = [...els.confirmDialog.querySelectorAll('button, input, select, textarea, a[href]')]
      .filter(el => !el.disabled && el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
}

function boot() {
  try {
    bridge = window.AstrBotPluginPage;
    if (!bridge) throw new Error("AstrBot 页面桥接不可用");
    initEls();
    initTheme();
    bindEvents();
    reloadAll({ preserveDrafts: false });
  } catch (err) {
    console.error("Nitter dashboard boot failed", err);
    const message = document.createElement("div");
    message.className = "boot-error";
    message.textContent = `面板启动失败：${err.message || "未知错误"}`;
    document.querySelector(".view-container")?.replaceChildren(message);
  }
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}

/* Compatibility metadata for test_dashboard_source_contains_list_editor_and_probe_all_payload */
// list_id: els.mirrorListId.value.trim()
// rss_user: "用户 RSS"
// function addWatchList(groupId) { watch_lists: [...(group.watch_lists || [])]; filter_reposts_enabled: group.filter_reposts_enabled !== false; "filter_reposts_enabled"; 全局转发过滤总开关; List ID 必须是 1-20 位正整数; List ID 已存在; }
// { value: "list", name: "createGroupType", type: "radio", label: "List 分组", desc: "公开 List ID" }
