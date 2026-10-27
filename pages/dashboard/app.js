/* Single-file bundle. Do not split into separate scripts — this is the only script the host loads. */
'use strict';

let bridge = null;

/* ==========================================================================
   1. State & 数据通道
   store 核心：数据变更经 markData(channels) 广播，按通道标记受影响视图为脏；
   激活视图立即冲刷，未激活视图等切换时冲刷（flushView）——视图容器常驻，
   切换不再整树重建，数据未变的视图不再重渲。
   ========================================================================== */

const state = {
  view: "overview", loading: false, actionBusy: false,
  busyLabel: "",
  overview: null, groups: [], groupDrafts: {}, targetProbeResults: {},
  config: null, configError: false,
  configDraft: {}, configSearch: "", configActive: "", configSaving: false, providers: [],
  targetBlacklists: [], targetBlacklistTarget: "",
  history: null, selectedGroupId: "",
  historyGroupId: "", historyUsername: "", historyLimit: 10,
  historyStatus: "", historySelection: new Set(),
  historyOffset: 0,
  pendingAction: null, lastFocusedElement: null,
  statusNotice: null, statusNoticeClosed: false, bannerOffset: "",
  // 诊断终端：插件日志环缓冲（web/logs），只在 mirror 视图可见时轮询
  logs: [], logsAfterSeq: 0, logsMax: 0, logsTimer: 0,
  // 右侧抽屉 / ⌘K 面板 / 新建弹窗的焦点恢复锚点
  sheetReturnFocus: null, cmdkReturnFocus: null, createGroupReturnFocus: null,
};

const els = {};

/* 六个视图容器常驻 DOM；初始全脏，boot 后只冲刷激活视图，其余首次切换时渲染 */
const viewDirty = new Set(["overview", "groups", "history", "mirror", "storage", "config"]);

/* 数据通道 → 受影响视图 */
const CHANNEL_VIEWS = {
  overview: ["overview", "mirror", "storage"],
  groups: ["groups", "overview"],
  history: ["history"],
  config: ["config"],
  logs: ["mirror"],
};

function markDirtyView(view) {
  viewDirty.add(view);
  if (view === state.view) flushView(view);
}

function markData(...channels) {
  for (const ch of channels) {
    for (const v of CHANNEL_VIEWS[ch] || []) markDirtyView(v);
    if (ch === "overview") { renderRailStatus(); renderTabCounts(); }
    if (ch === "groups") syncHistoryGroupOptions();
  }
}

/* 页签右侧计数徽标：分组数 / 历史总数 / 实例数 / 缓存体积 / 配置分组数 */
function renderTabCounts() {
  const p = state.overview || {};
  const c = p.counts || {};
  const mt = p.maintenance || {};
  if (els.tabCountGroups) els.tabCountGroups.textContent = String(c.groups ?? state.groups.length ?? 0);
  if (els.tabCountHistory) els.tabCountHistory.textContent = String(p.push_stats?.total ?? state.history?.total_count ?? 0);
  if (els.tabCountInstances) els.tabCountInstances.textContent = String((p.instances || []).length);
  if (els.tabCountStorage) els.tabCountStorage.textContent = mt.cache ? formatBytes(mt.cache.bytes) : "0 MB";
  if (els.tabCountConfig) els.tabCountConfig.textContent = String((state.config?.groups || []).length);
}

function initEls() {
  const ids = [
    "refreshBtn","themeToggleBtn","themeLabel",
    "railSchedulerStatus","noticeStack","toastContainer",
    "overviewView","groupsView","historyView","mirrorView","storageView","configView",
    "tabCountGroups","tabCountHistory","tabCountInstances","tabCountStorage","tabCountConfig",
    "cmdkBtn","groupsTitle","historyTitle","storageContent","cleanCacheBtn",
    "createGroupBtn","groupsGrid",
    "historyGroupSelect","historyUsername","historyLimit","historyStatusSelect","historyRefreshBtn",
    "historyOrphanBtn","historyPrevBtn","historyNextBtn","historyPageLabel",
    "historyOrphanResult","historyContent","historySelectAllBtn","historyBatchBar",
    "mirrorForm","mirrorUsername","mirrorQuery","mirrorListId","mirrorLimit",
    "mirrorInstance","mirrorProbeBtn","instanceList","mirrorResult",
    "confirmDialog","confirmTitle","confirmDesc","cancelConfirmBtn","confirmActionBtn",
    "sheetScrim","detailSheet","sheetTitle","sheetCloseBtn","sheetBody","sheetFooter",
    "cmdkOverlay","cmdkInput","cmdkList",
    "createGroupModal","createGroupTitle","createGroupName","createGroupType",
    "createGroupSubmitBtn","createGroupCancelBtn","createGroupCloseBtn",
  ];
  ids.forEach(id => { els[id] = document.getElementById(id); });
  els.tabs = document.querySelectorAll(".tab");
  els.views = document.querySelectorAll(".view");
}

/* 吸顶坐标实测合帧：ResizeObserver/resize 触发的一帧内只读一次布局。
   顶部导航壳（品牌栏 + 页签）是唯一的吸顶元素，其高度即吸附让位高度。 */
function initStickyOffsets() {
  const shell = document.querySelector(".nav-shell");
  if (!shell) return;
  let frame = 0;
  const sync = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const h = Math.ceil(shell.getBoundingClientRect().height);
      document.documentElement.style.setProperty("--topheader-height", `${h}px`);
    });
  };
  sync();
  window.addEventListener("resize", scheduleBannerSync);
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(sync).observe(shell);
  } else {
    window.addEventListener("resize", sync);
  }
}

/* ==========================================================================
   2. Inline SVG Icon Library (zero network requests)
   ========================================================================== */
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
  ban: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="m5.5 5.5 13 13" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>',
  sun: '<circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 2v2M12 20v2M4 4l1.4 1.4M18.6 18.6L20 20M2 12h2M20 12h2M4 20l1.4-1.4M18.6 5.4L20 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="9" cy="9" r="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M21 15l-5-5L5 21" fill="none" stroke="currentColor" stroke-width="2"/>',
  video: '<rect x="2" y="6" width="14" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M16 10l6-3v10l-6-3z" fill="none" stroke="currentColor" stroke-width="2"/>',
  rss: '<path d="M4 11a9 9 0 019 9M4 4a16 16 0 0116 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="5" cy="19" r="1.5" fill="currentColor"/>',
  search: '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="m20 20-3.5-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  external: '<path d="M14 3h7v7M21 3l-9 9M19 14v5a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  chevron: '<path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2" ry="2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
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

/* ==========================================================================
   3. DOM Builder h()
   ========================================================================== */
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

/* ==========================================================================
   4. API
   ========================================================================== */
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

/* ==========================================================================
   5. Feedback（通知栈 / toast / 时间与体积格式化）
   ========================================================================== */
/* 顶部通知栈：所有提示都进同一个栈，垂直排列，互不重叠。
   结果提示停留 NOTICE_TTL 后自动移除；进行中提示不挂计时，跟随动作生命周期。 */
const NOTICE_TTL = 4000;
const NOTICE_MAX = 4;
const NOTICE_CLASS = {
  status: "action-status",
  success: "alert success",
  warn: "alert warn",
  error: "alert error",
};

function noticeKey(kind, text) { return `${kind}\u0000${text}`; }

function armNoticeTimer(node, ttl) {
  if (node._noticeTimer) { clearTimeout(node._noticeTimer); node._noticeTimer = null; }
  if (!ttl) return;   // ttl=0：生命周期驱动的通知（进行中提示），不挂自动消失计时
  node._noticeTimer = setTimeout(() => dismissNotice(node), ttl);
}

function pushNotice(kind, text, ttl = NOTICE_TTL) {
  if (!els.noticeStack) return null;
  const type = NOTICE_CLASS[kind] ? kind : "success";
  // 同一条提示重复出现时只刷新停留时长，不叠加重复项
  const key = noticeKey(type, text);
  const dup = Array.from(els.noticeStack.children).find(n => n.dataset.key === key);
  if (dup) { armNoticeTimer(dup, ttl); return dup; }

  const node = h("div", {
    class: NOTICE_CLASS[type], role: type === "error" ? "alert" : null, dataset: { key, kind: type },
  }, [
    h("span", { class: "feedback-message", text }),
    h("button", {
      class: "feedback-close", type: "button", title: "关闭", "aria-label": "关闭提示",
      onclick: () => dismissNotice(node), text: "×",
    }),
  ]);
  els.noticeStack.appendChild(node);
  while (els.noticeStack.children.length > NOTICE_MAX) {
    dismissNotice(els.noticeStack.firstElementChild);
  }
  armNoticeTimer(node, ttl);
  scheduleBannerSync();
  return node;
}

function dismissNotice(node) {
  if (!node) return;
  if (node._noticeTimer) { clearTimeout(node._noticeTimer); node._noticeTimer = null; }
  node.remove();
  if (node === state.statusNotice) {
    // 手动关闭或到点消失后，本次动作内不再重建
    state.statusNotice = null;
    state.statusNoticeClosed = true;
  }
  scheduleBannerSync();
}

function clearNotices(kinds) {
  if (!els.noticeStack) return;
  const wanted = new Set(kinds);
  Array.from(els.noticeStack.children)
    .filter(n => wanted.has(n.dataset.kind))
    .forEach(dismissNotice);
}

/* 进行中提示跟随动作生命周期：actionBusy 上升时创建，动作结束时移除或被结果
   原地改写；不挂自动消失计时，长动作的顶部指示不会中途消失 */
function syncStatusNotice() {
  const text = state.actionBusy ? (state.busyLabel || "正在加载…") : "";
  if (!text) {
    if (state.statusNotice) dismissNotice(state.statusNotice);
    state.statusNoticeClosed = false;
    return;
  }
  if (state.statusNotice) {
    const message = state.statusNotice.querySelector(".feedback-message");
    if (message && message.textContent !== text) message.textContent = text;
    state.statusNotice.dataset.key = noticeKey("status", text);
    scheduleBannerSync();
    return;
  }
  if (state.statusNoticeClosed) return;
  state.statusNotice = pushNotice("status", text, 0);
}

/* 通知栈高度随条数与换行变化，用实测高度驱动内容预留与历史工具栏吸顶偏移；
   连续出入栈经 rAF 合帧，一帧只做一次“读布局 → 写变量” */
let bannerFrame = 0;
function scheduleBannerSync() {
  if (bannerFrame) return;
  bannerFrame = requestAnimationFrame(() => { bannerFrame = 0; syncBannerOffset(); });
}
function syncBannerOffset() {
  const height = els.noticeStack ? Math.ceil(els.noticeStack.getBoundingClientRect().height) : 0;
  const offset = height ? `${height + 8}px` : "0px";
  if (state.bannerOffset === offset) return;
  state.bannerOffset = offset;
  document.documentElement.style.setProperty("--banner-offset", offset);
}
/* 结果提示出现时，直接把进行中提示原地改写成结果，避免“移除 + 新增”两次跳动 */
function promoteStatusNotice(kind, text, ttl = NOTICE_TTL) {
  const node = state.statusNotice;
  const message = node && node.querySelector(".feedback-message");
  if (!message) return null;
  node.className = NOTICE_CLASS[kind];
  if (kind === "error") node.setAttribute("role", "alert");
  else node.removeAttribute("role");
  node.dataset.kind = kind;
  node.dataset.key = noticeKey(kind, text);
  message.textContent = text;
  armNoticeTimer(node, ttl);
  state.statusNotice = null;
  state.statusNoticeClosed = true;   // 本次动作内不再重建进行中提示
  scheduleBannerSync();
  return node;
}

function showAlert(msg, type = "success") {
  const kind = NOTICE_CLASS[type] ? type : "success";
  if (state.statusNotice && promoteStatusNotice(kind, msg)) return;
  pushNotice(kind, msg);
}
function hideAlert() {
  clearNotices(["success", "warn", "error"]);
}
function showToast(msg) {
  if (!els.toastContainer) return;
  const t = h("div", { class: "toast", text: msg });
  els.toastContainer.appendChild(t);
  setTimeout(() => t.remove(), 2800);
}
function parsePushedAt(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return NaN;
  // 后端时间戳含小数（time.time() 浮点秒），正则要允许小数点
  const t = /^\d{9,}(\.\d+)?$/.test(s) ? Number(s) : new Date(s.replace(" ", "T")).getTime();
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
function formatBytes(n) {
  if (!Number.isFinite(n) || n <= 0) return "0 KB";
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

/* ==========================================================================
   6. Select（自绘下拉,替代原生 select 的割裂观感）
   ========================================================================== */
let openDropdown = null;

function createSelect({ id = "", value = "", options = [] } = {}) {
  const root = h("div", { class: "dd" });
  if (id) root.id = id;
  let current = String(value ?? "");
  let opts = options.map(o => ({ value: String(o.value), text: o.text }));
  let onChange = null;

  const labelEl = h("span", { class: "dd-label" });
  const trigger = h("button", {
    type: "button", class: "dd-trigger", "aria-haspopup": "listbox", "aria-expanded": "false",
  }, [labelEl, h("span", { class: "dd-caret", html: svgIcon("chevron", 14) })]);
  const list = h("div", { class: "dd-list", role: "listbox", hidden: true });
  root.append(trigger, list);

  const labelOf = v => (opts.find(o => o.value === v) || { text: v }).text;
  function syncTrigger() { labelEl.textContent = labelOf(current); }
  function renderList() {
    list.replaceChildren(...opts.map(o => h("button", {
      type: "button",
      class: `dd-option${o.value === current ? " selected" : ""}`,
      role: "option",
      "aria-selected": o.value === current ? "true" : "false",
      text: o.text,
      onClick: () => { pick(o.value); close(true); },
    })));
  }
  function pick(v) {
    const changed = v !== current;
    current = v;
    syncTrigger();
    renderList();
    if (changed && typeof onChange === "function") onChange(current);
  }
  function onDocClick(e) { if (!root.contains(e.target)) close(); }
  function open() {
    if (openDropdown && openDropdown !== api) openDropdown._close();
    renderList();
    list.hidden = false;
    root.classList.add("open");
    trigger.setAttribute("aria-expanded", "true");
    document.addEventListener("click", onDocClick, true);
    openDropdown = api;
    (list.querySelector(".dd-option.selected") || list.firstElementChild)?.focus();
  }
  function close(restoreFocus = false) {
    if (list.hidden) return;
    list.hidden = true;
    root.classList.remove("open");
    trigger.setAttribute("aria-expanded", "false");
    document.removeEventListener("click", onDocClick, true);
    if (openDropdown === api) openDropdown = null;
    if (restoreFocus) trigger.focus();
  }
  trigger.addEventListener("click", e => {
    e.preventDefault();
    if (list.hidden) open();
    else close();
  });
  trigger.addEventListener("keydown", e => {
    if (["ArrowDown", "ArrowUp"].includes(e.key)) { e.preventDefault(); open(); }
    else if (["Enter", " "].includes(e.key)) { e.preventDefault(); if (list.hidden) open(); else close(); }
  });
  list.addEventListener("keydown", e => {
    const items = [...list.querySelectorAll(".dd-option")];
    const idx = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[Math.min(idx + 1, items.length - 1)]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[Math.max(idx - 1, 0)]?.focus(); }
    else if (e.key === "Escape") { e.preventDefault(); close(true); }
    else if (e.key === "Tab") close();
  });

  const api = { _close: close };
  Object.defineProperty(root, "value", {
    get: () => current,
    set: v => pick(String(v ?? "")),
  });
  root.setOptions = next => {
    opts = next.map(o => ({ value: String(o.value), text: o.text }));
    if (!opts.some(o => o.value === current)) current = opts[0]?.value ?? "";
    syncTrigger();
    if (!list.hidden) renderList();
  };
  root.onChange = fn => { onChange = fn; };
  syncTrigger();
  return root;
}

function setBusy(isBusy) {
  state.loading = isBusy;
  const busy = isBusy || state.actionBusy;
  [els.refreshBtn, els.createGroupBtn, els.historyRefreshBtn, els.historyOrphanBtn,
   els.historyPrevBtn, els.historyNextBtn, els.mirrorProbeBtn, els.historySelectAllBtn].forEach(b => { if (b) b.disabled = busy; });
  document.querySelectorAll("[data-busy-control]").forEach(control => { control.disabled = busy; });
  document.body.classList.toggle("ui-busy", busy);
  syncStatusNotice();
}

/* ==========================================================================
   7. Confirm Dialog
   ========================================================================== */
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

/* ==========================================================================
   7b. Sheet（右侧详情抽屉）
   分组编辑与推文详情共用同一抽屉：内容由调用方构造后传入，抽屉本身只负责
   开合、遮罩、Escape 关闭与焦点圈/焦点恢复。
   ========================================================================== */
let sheetOpen = false;

function openSheet({ title, body, footer = [], onClose = null }) {
  if (!els.detailSheet) return;
  if (!sheetOpen) state.sheetReturnFocus = document.activeElement;
  sheetOpen = true;
  els.sheetTitle.textContent = title || "详情";
  els.sheetBody.replaceChildren(...(Array.isArray(body) ? body : [body]));
  els.sheetFooter.replaceChildren(...(Array.isArray(footer) ? footer.filter(Boolean) : [footer].filter(Boolean)));
  els.detailSheet._onClose = onClose;
  els.detailSheet.hidden = false;
  // 先解除 hidden 再加 open，否则首帧拿不到过渡起点
  requestAnimationFrame(() => {
    els.detailSheet.classList.add("open");
    els.sheetScrim?.classList.add("open");
  });
  const focusTarget = els.sheetBody.querySelector("input, select, textarea, button") || els.sheetCloseBtn;
  focusTarget?.focus?.();
}

function closeSheet({ restoreFocus = true } = {}) {
  if (!els.detailSheet || !sheetOpen) return;
  sheetOpen = false;
  const onClose = els.detailSheet._onClose;
  els.detailSheet._onClose = null;
  els.detailSheet.classList.remove("open");
  els.sheetScrim?.classList.remove("open");
  const finish = () => { if (!sheetOpen) els.detailSheet.hidden = true; };
  els.detailSheet.addEventListener("transitionend", finish, { once: true });
  // 无过渡（prefers-reduced-motion / 隐藏窗口）时兜底
  setTimeout(finish, 320);
  if (typeof onClose === "function") onClose();
  if (restoreFocus && state.sheetReturnFocus?.focus) state.sheetReturnFocus.focus();
  state.sheetReturnFocus = null;
}

/* 抽屉内焦点圈：Tab 到首尾时回绕，避免焦点跑到被遮住的页面上 */
function trapFocus(container, e) {
  const focusable = [...container.querySelectorAll('button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])')]
    .filter(el => !el.disabled && el.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

/* ==========================================================================
   7c. ⌘K 命令面板
   命令表由视图元信息 + 当前分组 + 全局动作动态生成；↑↓ 选择、Enter 执行、
   Escape 关闭。只做前端可达动作，不新增后端能力。
   ========================================================================== */
let cmdkItems = [];
let cmdkIndex = 0;
let cmdkOpen = false;

function buildCmdkItems() {
  const items = Object.entries(VIEW_META).map(([view, meta]) => ({
    title: `切换到${meta.title}`,
    sub: "视图",
    run: () => switchView(view),
  }));
  for (const g of state.groups) {
    const count = g.group_type === "tag"
      ? (g.watch_queries || []).length
      : g.group_type === "list" ? (g.watch_lists || []).length : (g.watch_users || []).length;
    const unit = g.group_type === "tag" ? "关键词" : g.group_type === "list" ? "列表" : "博主";
    items.push({
      title: `编辑分组：${g.name}`,
      sub: `${count} ${unit}`,
      run: () => { switchView("groups"); selectGroup(g.group_id); },
    });
  }
  items.push({ title: "刷新全部数据", sub: "动作", run: () => reloadAll({ preserveDrafts: false }) });
  items.push({ title: "清理媒体缓存", sub: "动作", run: () => { switchView("overview"); confirmClearCache(); } });
  return items;
}

function renderCmdk(query = "") {
  const q = query.trim().toLowerCase();
  const filtered = cmdkItems.filter(it => !q || it.title.toLowerCase().includes(q) || it.sub.toLowerCase().includes(q));
  if (cmdkIndex >= filtered.length) cmdkIndex = 0;
  if (!filtered.length) {
    els.cmdkList.replaceChildren(h("div", { class: "pal-empty", text: "没有匹配的命令" }));
    return;
  }
  els.cmdkList.replaceChildren(...filtered.map((it, i) => h("div", {
    class: `pal-item ${i === cmdkIndex ? "selected" : ""}`,
    role: "button",
    tabindex: "-1",
    onClick: () => { closeCmdk(); it.run(); },
  }, [
    h("span", { text: it.title }),
    h("span", { class: "pal-sub", text: it.sub }),
  ])));
  // 只滚动当前项，不动整页
  els.cmdkList.children[cmdkIndex]?.scrollIntoView({ block: "nearest" });
}

function openCmdk() {
  if (!els.cmdkOverlay || cmdkOpen) return;
  cmdkOpen = true;
  state.cmdkReturnFocus = document.activeElement;
  cmdkItems = buildCmdkItems();
  cmdkIndex = 0;
  els.cmdkInput.value = "";
  renderCmdk("");
  els.cmdkOverlay.classList.add("open");
  els.cmdkInput.focus();
}

function closeCmdk() {
  if (!els.cmdkOverlay || !cmdkOpen) return;
  cmdkOpen = false;
  els.cmdkOverlay.classList.remove("open");
  if (state.cmdkReturnFocus?.focus) state.cmdkReturnFocus.focus();
  state.cmdkReturnFocus = null;
}

/* ==========================================================================
   7d. 诊断终端（真实插件日志）
   数据来自 web/logs 的内存环缓冲，只含插件自身经安全辅助函数发出的事件。
   轮询只在实例诊断视图可见时运行，切走即停。
   ========================================================================== */
const LOG_POLL_MS = 3000;

function logTime(ts) {
  const d = new Date((ts || 0) * 1000);
  const pad = n => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function renderTerminal(container, entries, { title = "probe.sh", empty = "暂无日志事件" } = {}) {
  if (!container) return;
  container.classList.add("mac-terminal");
  const lines = [];
  for (const entry of entries) {
    const level = entry.level || "info";
    for (const text of entry.lines || []) {
      lines.push(h("div", { class: "term-line" }, [
        h("span", { class: "term-time", text: logTime(entry.ts) }),
        h("span", { class: `term-tag ${level}`, text: level.toUpperCase() }),
        h("span", { class: "term-msg", text }),
      ]));
    }
  }
  container.replaceChildren(
    h("div", { class: "mac-terminal-bar" }, [
      h("div", { class: "mac-dots" }, [
        h("span", { class: "mac-dot red" }),
        h("span", { class: "mac-dot yellow" }),
        h("span", { class: "mac-dot green" }),
      ]),
      h("span", { class: "mac-terminal-title", text: title }),
      h("span", { class: "mac-terminal-status" }, [
        h("span", { class: "mac-status-indicator" }),
        h("span", { text: "实时" }),
      ]),
    ]),
    h("div", { class: "mac-terminal-body" }, lines.length ? lines : [h("div", { class: "term-empty", text: empty })]),
  );
  // 新日志追加后滚到底，便于追踪最新事件
  const body = container.querySelector(".mac-terminal-body");
  if (body) body.scrollTop = body.scrollHeight;
}

/* ==========================================================================
   7e. 错误追踪终端（macOS 仿苹果黑曜石终端）
   专用于推文发送失败时的 ActionFailed 等错误追踪，支持状态提取、高亮与一键复制。
   ========================================================================== */
function renderErrorTerminal(rawError, { title = "delivery_error.log", status = "FAILED" } = {}) {
  const str = String(rawError || "");
  let retcode = "";
  const m = str.match(/retcode[=:]\s*(\d+)/i);
  if (m) retcode = m[1];
  const exitStatus = retcode ? `EXIT ${retcode}` : status;

  const copyBtn = h("button", {
    class: "mac-copy-btn",
    type: "button",
    title: "复制完整错误信息",
    html: `${svgIcon("copy", 11)}<span>复制</span>`,
    onClick: async (e) => {
      e.stopPropagation();
      let copied = false;
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(str);
          copied = true;
        }
      } catch (_) {}
      if (!copied) {
        const ta = document.createElement("textarea");
        ta.value = str;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); copied = true; } catch (_) {}
        document.body.removeChild(ta);
      }
      if (copied) {
        copyBtn.innerHTML = `${svgIcon("check", 11)}<span>已复制</span>`;
        copyBtn.classList.add("copied");
        setTimeout(() => {
          copyBtn.innerHTML = `${svgIcon("copy", 11)}<span>复制</span>`;
          copyBtn.classList.remove("copied");
        }, 1800);
      }
    },
  });

  const bar = h("div", { class: "mac-terminal-bar" }, [
    h("div", { class: "mac-dots" }, [
      h("span", { class: "mac-dot red" }),
      h("span", { class: "mac-dot yellow" }),
      h("span", { class: "mac-dot green" }),
    ]),
    h("span", { class: "mac-terminal-title mono", text: title }),
    h("div", { class: "mac-terminal-actions" }, [
      copyBtn,
      h("span", { class: "mac-terminal-status-badge bad" }, [
        h("span", { class: "status-dot red" }),
        h("span", { text: exitStatus }),
      ]),
    ]),
  ]);

  const body = h("div", { class: "mac-terminal-body mac-error-body" });
  let msgMatch = str.match(/message=['"]([^'"]+)['"]/);
  let mainMsg = msgMatch ? msgMatch[1] : "";

  const lines = [
    h("div", { class: "term-line prompt-line" }, [
      h("span", { class: "term-prompt", text: "$" }),
      h("span", { class: "term-cmd", text: "bot.send_forward_msg --verbose" }),
    ]),
  ];

  if (retcode || mainMsg) {
    lines.push(
      h("div", { class: "term-line error-highlight-line" }, [
        h("span", { class: "term-tag critical", text: exitStatus }),
        h("span", { class: "term-msg term-error-msg", text: mainMsg || str }),
      ])
    );
  }

  lines.push(
    h("div", { class: "term-line raw-log-line" }, [
      h("span", { class: "term-msg mono", text: str }),
    ])
  );

  body.replaceChildren(...lines);
  return h("div", { class: "mac-terminal mac-error-terminal" }, [bar, body]);
}

async function reloadLogs({ reset = false } = {}) {
  if (reset) { state.logs = []; state.logsAfterSeq = 0; }
  const res = await apiGet("web/logs", { after_seq: state.logsAfterSeq || undefined });
  const incoming = res.entries || [];
  state.logsMax = res.max_entries || state.logsMax;
  if (incoming.length) {
    state.logs = state.logs.concat(incoming);
    state.logsAfterSeq = incoming[incoming.length - 1].seq;
    // 前端与后端同上限，避免长时间停留后无限增长
    if (state.logsMax && state.logs.length > state.logsMax) {
      state.logs = state.logs.slice(-state.logsMax);
    }
  }
  markData("logs");
}

function startLogPolling() {
  stopLogPolling();
  state.logsTimer = setInterval(() => {
    reloadLogs().catch(() => stopLogPolling());
  }, LOG_POLL_MS);
}

function stopLogPolling() {
  if (state.logsTimer) { clearInterval(state.logsTimer); state.logsTimer = 0; }
}

/* ==========================================================================
   8. Theme
   ========================================================================== */
/* 主题切换只在本次会话内生效，不做持久化：AstrBot Plugin Pages 的 iframe 使用
   sandbox="allow-scripts allow-forms allow-downloads"（无 allow-same-origin），
   opaque origin 下浏览器存储任何访问都抛 SecurityError，曾拖垮整页启动
   （529ee81，见 Progress/2026-09-04.md）。跨会话主题由宿主 WebUI 负责，
   onContext 会把宿主的主题推送下来。故页面内禁止访问浏览器存储。 */
let themePinned = false; // 用户手动切换后不再接受宿主主题推送

function initTheme() {
  const context = bridge?.getContext?.() || {};
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  // 优先级：宿主主题 > 系统偏好
  applyTheme(typeof context.isDark === "boolean" ? context.isDark : prefersDark);
  bridge?.onContext?.(nextContext => {
    if (!themePinned && typeof nextContext?.isDark === "boolean") applyTheme(nextContext.isDark);
  });
}
function applyTheme(isDark) {
  // 主题类挂在 <html> 上：深色变量的唯一出处是 :root.dark-theme
  document.documentElement.classList.toggle("dark-theme", !!isDark);
  document.documentElement.classList.toggle("light-theme", !isDark);
  // 顶栏按钮文案与原型一致：当前深色时提示切到亮色，反之亦然
  if (els.themeLabel) els.themeLabel.textContent = isDark ? "亮色模式" : "暗色模式";
}
function toggleTheme() {
  const next = !document.documentElement.classList.contains("dark-theme");
  themePinned = true;
  applyTheme(next);
}

/* ==========================================================================
   9. 数据加载：作用域化刷新（替代“任何动作都全量 reload”）
   reloadAll 只用于 boot 与手动刷新；动作收尾按当前视图刷新对应数据，
   内容保留在原地（stale-while-revalidate），不再先清屏再等数据。
   ========================================================================== */
async function reloadOverviewData() {
  state.overview = await apiGet("web/overview");
  markData("overview");
}

/* 分组 + 黑名单 + 概览一起拉（目标黑名单随 targets 区块展示，概览驱动健康徽标
   与顶部 pill）；count/attention 变化联动总览与历史下拉 */
async function reloadGroupState() {
  const [groups, blacklists, overview] = await Promise.all([
    apiGet("web/groups"), apiGet("web/target-blacklists"), apiGet("web/overview"),
  ]);
  state.groups = groups.groups || [];
  state.targetBlacklists = blacklists.target_blacklists || [];
  state.overview = overview;
  if (!state.selectedGroupId || !state.groups.some(g => g.group_id === state.selectedGroupId)) {
    state.selectedGroupId = state.groups[0]?.group_id || "";
  }
  syncGroupDrafts();
  markData("groups");
  markData("overview");
}

async function reloadConfigState() {
  const cf = await apiGet("web/config/schema");
  state.config = cf;
  state.configError = false;
  try {
    const pv = await apiGet("web/config/providers");
    state.providers = pv.providers || [];
  } catch (err) {
    // Provider 下拉数据源:失败静默降级为空列表(仅支持"留空 = 自动选择")
    state.providers = [];
  }
  buildConfigIndex();
  markData("config");
}

async function refreshHistoryData() {
  const data = await apiGet("web/history", {
    group_id: state.historyGroupId || undefined,
    username: state.historyUsername || undefined,
    limit: state.historyLimit, offset: state.historyOffset,
    status: state.historyStatus || undefined,
  });
  state.history = data;
  state.historySelection.clear();
  markData("history");
  return data;
}

async function refreshViewData(view) {
  try {
    if (view === "groups") {
      // 分组增删会联动清理历史，概览计数也随之变化：两路并行刷新
      const results = await Promise.allSettled([reloadGroupState(), refreshHistoryData()]);
      const failed = results.find(r => r.status === "rejected");
      if (failed) throw failed.reason;
      return true;
    }
    if (view === "config") { await reloadConfigState(); return true; }
    if (view === "history") { await refreshHistoryData(); return true; }
    await reloadOverviewData();
    return true;
  } catch (err) {
    showAlert(`数据刷新失败：${err.message || "请求失败"}`, "warn");
    return false;
  }
}

async function withAction(action, successText, { reload = true, rerender = null } = {}) {
  if (state.actionBusy) return null;
  state.actionBusy = true; setBusy(true); hideAlert();
  try {
    const res = await action();
    if (reload) {
      state.busyLabel = "正在刷新…";
      setBusy(true);
      const ok = await refreshViewData(state.view);
      if (!ok) return res;
    } else if (rerender) await rerender();
    if (successText !== false && (successText || res?.message)) {
      showAlert(successText || res?.message);
    }
    return res;
  } catch (err) { showAlert(err.message || "操作失败", "error"); return null; }
  finally { state.actionBusy = false; state.busyLabel = ""; setBusy(false); }
}

async function reloadAll(options = {}) {
  const ownBusyLabel = !state.actionBusy && !state.busyLabel;
  if (ownBusyLabel) state.busyLabel = "正在加载…";
  setBusy(true); hideAlert();
  try {
    await bridge.ready();
    if (options.preserveDrafts === false) {
      state.groupDrafts = {}; state.configDraft = {}; state.targetProbeResults = {};
      configDirtyKeys.clear();
    }
    const results = await Promise.allSettled([
      reloadGroupState(), reloadConfigState(), refreshHistoryData(),
    ]);
    const labels = ["分组加载失败", "配置加载失败", "历史加载失败"];
    const errors = [];
    results.forEach((r, i) => {
      if (r.status === "rejected") {
        if (i === 1) state.configError = true;
        errors.push(`${labels[i]}：${r.reason?.message || "请求失败"}`);
      }
    });
    renderRailStatus();
    if (errors.length) showAlert(`部分数据未加载：${errors.join("；")}`, "warn");
    return errors.length === 0;
  } catch (err) { showAlert(err.message, "error"); return false; }
  finally {
    if (ownBusyLabel) state.busyLabel = "";
    setBusy(false);
  }
}

/* ==========================================================================
   10. Groups — 列表 / 编辑器 / 草稿 / 订阅源 / 推送目标 / 黑名单
   ========================================================================== */
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
  // 服务器隔离的无效条目：随 draft 一起回写（update_group 原样落盘），
  // 否则保存任意字段都会把配置里的无效条目静默清除
  snap.invalid_push_targets = Array.isArray(group.invalid_push_targets) ? [...group.invalid_push_targets] : [];
  snap.invalid_watch_users = Array.isArray(group.invalid_watch_users) ? [...group.invalid_watch_users] : [];
  return snap;
}

/* 保存 payload：无效条目按原文随有效列表一起回写（update_group 不做 UMO 校验、
   原样落盘），落实"完整重建、保留畸形条目"的写回语义；显式删除 = 从列表移除 */
function buildGroupPayload(d) {
  return {
    ...d,
    push_targets: [...(d.push_targets || []), ...(d.invalid_push_targets || [])],
    watch_users: [...(d.watch_users || []), ...(d.invalid_watch_users || [])],
  };
}

function syncGroupDrafts() {
  for (const g of state.groups) {
    if (!state.groupDrafts[g.group_id]) state.groupDrafts[g.group_id] = snapshotGroup(g);
  }
}

/* 脏检查缓存：服务器快照 JSON 按分组对象身份缓存（state.groups 整体换新时
   自动失效）；draft JSON 按修订号缓存。元数据放 WeakMap 而非 draft 属性，
   保证 stringify 结果与 POST payload 形状不变。 */
const groupSnapJsonCache = new WeakMap();
const draftRevCache = new WeakMap();
const draftJsonCache = new WeakMap();

function draftJson(d) {
  const rev = draftRevCache.get(d) || 0;
  const cached = draftJsonCache.get(d);
  if (cached && cached.rev === rev) return cached.json;
  const json = JSON.stringify(d);
  draftJsonCache.set(d, { rev, json });
  return json;
}

function isGroupDirty(groupId) {
  const g = state.groups.find(x => x.group_id === groupId);
  const d = state.groupDrafts[groupId];
  if (!g || !d) return false;
  let snapJson = groupSnapJsonCache.get(g);
  if (snapJson === undefined) {
    snapJson = JSON.stringify(snapshotGroup(g));
    groupSnapJsonCache.set(g, snapJson);
  }
  return snapJson !== draftJson(d);
}

let groupListRenderPending = false;
/* 每键只调度一次列表重渲（rAF 合帧），列表重建成本不再随击键线性叠加 */
function scheduleGroupListRender() {
  if (groupListRenderPending) return;
  groupListRenderPending = true;
  requestAnimationFrame(() => {
    groupListRenderPending = false;
    renderGroupCards();
  });
}

function updateDraft(groupId, field, val) {
  const d = state.groupDrafts[groupId]; if (!d) return;
  d[field] = val;
  draftRevCache.set(d, (draftRevCache.get(d) || 0) + 1);
  scheduleGroupListRender();
}

/* --------------------------------------------------------------------------
   Group List（含健康徽标：服务端 attention_items + 无效条目计数）
   -------------------------------------------------------------------------- */
function groupHealthInfo(g) {
  const attention = Array.isArray(g.attention_items) ? g.attention_items : [];
  const invalidCount = (g.invalid_push_targets?.length || 0) + (g.invalid_watch_users?.length || 0);
  const count = attention.length + invalidCount;
  const titles = attention.map(i => i.title || "").filter(Boolean);
  return {
    count,
    title: count
      ? `需注意：${titles.slice(0, 2).join("、") || "存在需要处理的问题"}${titles.length > 2 ? " 等" : ""}`
      : "运行正常",
  };
}

function renderGroupCards() {
  if (!els.groupsGrid) return;
  if (!state.groups.length) {
    els.groupsGrid.replaceChildren(h("div", { class: "panel empty-note", text: "暂无分组，点击右上角新建。" }));
    return;
  }
  els.groupsGrid.replaceChildren(...state.groups.map(g => groupCard(g)));
}

function groupCard(g) {
  const d = state.groupDrafts[g.group_id] || snapshotGroup(g);
  const dirty = isGroupDirty(g.group_id);
  const isTag = g.group_type === "tag";
  const isList = g.group_type === "list";
  const typeLabel = isTag ? "关键词搜索" : isList ? "List 列表" : "博主订阅";
  // 后端 watch_queries 是 {query,type} 对象数组，chips 需要纯文本
  const sources = (isTag ? (d.watch_queries || []) : isList ? (d.watch_lists || []) : (d.watch_users || []))
    .map(v => (v && typeof v === "object" ? (v.query ?? v.value ?? "") : v))
    .filter(v => v !== "" && v != null);
  const targets = d.push_targets || [];
  const invalidTargets = d.invalid_push_targets || [];
  const intervalOn = d.interval_check_enabled !== false;
  const daily = (d.daily_check_times || []).join(", ");
  const repostFilter = d.filter_reposts_enabled ? "已开启" : "已关闭";
  const plainFilter = d.filter_plain_text_enabled ? "仅媒体" : "全部";
  const health = groupHealthInfo(g);
  const preview = sources.slice(0, 8);
  // 无效条目隔离区：tag/list 分组的无效项由后端放在 invalid_watch_queries/lists，
  // 旧代码只处理了 invalid_watch_users，这里按分组类型补齐。
  const invalidSources = isTag
    ? (d.invalid_watch_queries || [])
    : isList
      ? (d.invalid_watch_lists || [])
      : (d.invalid_watch_users || []);

  return h("div", { class: `group-card${dirty ? " dirty" : ""}` }, [
    h("div", { class: "gc-header" }, [
      h("div", { class: "gc-title" }, [
        h("span", { class: "gc-title-text", text: d.name || g.name }),
        h("span", { class: "gc-type-tag", text: typeLabel }),
        dirty ? h("span", { class: "badge badge-warn", text: "未保存" }) : null,
      ]),
      h("span", {
        class: `gc-badge ${d.enabled ? "active" : "disabled"}`,
        text: d.enabled ? "● 运行中" : "○ 已停用",
      }),
    ]),
    h("div", { class: "gc-meta-grid" }, [
      h("div", {}, [h("span", { text: "检查间隔: " }), h("span", { class: "mono", text: intervalOn ? `${g.check_interval_minutes ?? "—"} 分钟` : "已关闭" })]),
      h("div", {}, [h("span", { text: "转推过滤: " }), h("span", { class: "mono", text: repostFilter })]),
      h("div", {}, [h("span", { text: "每日定时: " }), h("span", { class: "mono", text: daily || "无" })]),
      h("div", {}, [h("span", { text: "纯文本过滤: " }), h("span", { class: "mono", text: plainFilter })]),
    ]),
    h("div", {}, [
      h("div", { class: "gc-chips-header" }, [
        h("span", { class: "row" }, [
          h("span", { class: `health-dot ${health.count ? "warn" : "ok"}`, title: health.title }),
          h("span", {
            text: isTag
              ? `搜索词（${sources.length} 个）`
              : isList ? `List（${sources.length} 个）` : `关注博主（${sources.length} 位）`,
          }),
        ]),
        h("button", {
          class: "nav-btn gc-manage-btn",
          type: "button",
          text: "+ 管理",
          onClick: () => openGroupSheet(g.group_id),
        }),
      ]),
      h("div", { class: "gc-chips", style: { marginTop: "6px" } },
        preview.length
          ? [
              ...preview.map(v => h("span", { class: "chip-entity", title: v }, [
                h("span", { text: isTag ? v : (isList ? `List:${v}` : `@${v}`) }),
              ])),
              sources.length > preview.length
                ? h("span", { class: "chip-entity more", text: `+${sources.length - preview.length} 更多` })
                : null,
              ...invalidSources.slice(0, 3).map(v => h("span", { class: "chip-entity invalid", title: "无效条目", text: v })),
            ].filter(Boolean)
          : [h("span", { class: "hint", text: "暂无订阅源" })],
      ),
    ]),
    h("div", { class: "gc-targets-box" }, [
      h("div", { class: "gc-targets-title", text: "接收目标群聊:" }),
      ...(targets.length || invalidTargets.length
        ? [
            ...targets.map(t => {
              const umo = typeof t === "string" ? t : (t?.umo || "");
              return h("div", { class: "target-row" }, [
                h("span", { text: replayTargetShortLabel(umo) }),
                h("span", { class: "mono target-umo", text: umo }),
              ]);
            }),
            ...invalidTargets.map(t => {
              const umo = typeof t === "string" ? t : (t?.umo || "");
              return h("div", { class: "target-row gone" }, [
                h("span", { text: replayTargetShortLabel(umo) }),
                h("span", { class: "mono target-umo", text: umo }),
              ]);
            }),
          ]
        : [h("div", { class: "hint", text: "未配置推送目标" })]),
    ]),
    h("div", { class: "gc-card-actions" }, [
      h("button", { class: "nav-btn", type: "button", text: "测试目标连通", onClick: () => probeTargets(g.group_id) }),
      h("button", { class: "nav-btn btn-primary", type: "button", text: "编辑详细配置", onClick: () => openGroupSheet(g.group_id) }),
    ]),
  ]);
}

function selectGroup(gid, { force = false } = {}) {
  const prev = state.groups.find(g => g.group_id === state.selectedGroupId);
  if (!force && prev && isGroupDirty(state.selectedGroupId) && sheetOpen) {
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
  state.selectedGroupId = gid;
  renderGroupCards();
}

/* --------------------------------------------------------------------------
   Group Sheet（抽屉编辑器）
   内容分区与旧左右分栏一致：基础开关 / 订阅源 / 推送目标 / 黑名单，
   差异只在容器形态（抽屉）与打开时机（点卡片进入）。
   -------------------------------------------------------------------------- */
function openGroupSheet(gid) {
  const g = state.groups.find(x => x.group_id === gid);
  if (!g) return;
  state.selectedGroupId = gid;
  const d = state.groupDrafts[gid] || snapshotGroup(g);

  const body = h("div", { class: "vstack" }, [
    // 名称 + 启停
    h("label", { class: "field" }, [
      h("span", { text: "分组名称" }),
      h("input", {
        type: "text",
        value: d.name,
        onInput: e => updateDraft(gid, "name", e.target.value.trim()),
        onChange: () => saveGroup(gid, "分组名称已保存"),
      }),
    ]),
    h("div", { class: "editor-grid" }, [
      toggleRow(d.enabled, "启用此分组", v => commitGroupField(gid, "enabled", v)),
      toggleRow(d.interval_check_enabled, "开启定时循环间隔检查", v => commitGroupField(gid, "interval_check_enabled", v)),
      toggleRow(d.filter_reposts_enabled, "过滤转发（需同时开启全局转发过滤总开关）", v => commitGroupField(gid, "filter_reposts_enabled", v)),
      toggleRow(d.filter_plain_text_enabled, "过滤纯文本（仅有媒体推文才推送）", v => commitGroupField(gid, "filter_plain_text_enabled", v)),
      toggleRow(d.media_only_enabled, "仅保留含媒体推文（图片/视频）", v => commitGroupField(gid, "media_only_enabled", v)),
      toggleRow(d.omit_status_url, "省略原推链接", v => commitGroupField(gid, "omit_status_url", v)),
      toggleRow(d.hide_original_when_translated, "翻译后隐藏原文", v => commitGroupField(gid, "hide_original_when_translated", v)),
    ]),
    h("span", { class: "hint-line", text: `间隔检查使用全局检查间隔：${g.check_interval_minutes ?? "—"} 分钟` }),
    h("label", { class: "field" }, [
      h("span", { text: "每日定时触发时间（逗号或换行分隔，如 08:00, 20:00）" }),
      h("input", {
        type: "text",
        value: (d.daily_check_times || []).join(", "),
        onInput: e => {
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
          updateDraft(gid, "daily_check_times", valid);
        },
        onChange: () => saveGroup(gid, "定时设置已保存"),
      }),
      h("span", { id: "dailyTimesHint", class: "field-error", style: { display: "none" } }),
    ]),
    // 订阅源：完整能力（chips / 无效隔离 / 批量导入 / 添加）
    renderEntities(g, d),
    // 推送目标：data-editor-section 供 rerenderTargetsSection 局部重建
    h("div", { "data-editor-section": "targets" }, renderTargets(g, d)),
  ]);

  const footer = [
    h("span", { class: "mono hint", text: g.group_id }),
    g.group_id !== "default"
      ? h("button", { class: "btn btn-sm btn-danger", type: "button", text: "删除分组", onClick: () => { closeSheet(); confirmDeleteGroup(gid); } })
      : null,
    h("button", { class: "btn btn-sm", type: "button", text: "关闭", onClick: () => closeSheet() }),
  ];

  openSheet({ title: `编辑分组 · ${d.name || g.name}`, body, footer });
}


/* targets 区块局部重建：probe/黑名单等只影响该区块的操作不必整棵重建抽屉 */
function rerenderTargetsSection(gid) {
  if (gid !== state.selectedGroupId) return;   // 请求在途时用户已切换分组，跳过过期重渲
  const g = state.groups.find(x => x.group_id === gid);
  const d = g ? (state.groupDrafts[g.group_id] || snapshotGroup(g)) : null;
  const section = els.sheetBody?.querySelector('[data-editor-section="targets"]');
  if (!g || !d || !section) { if (sheetOpen) openGroupSheet(gid); return; }
  section.replaceChildren(renderTargets(g, d));
}

function toggleRow(checked, label, onChange) {
  return h("label", { class: "toggle" }, [
    h("input", { type: "checkbox", checked, onChange: e => onChange(e.target.checked) }),
    h("span", { class: "toggle-track" }),
    h("span", { text: label }),
  ]);
}

function renderEntityChips(container, group, draft) {
  const isTag = group.group_type === "tag";
  const isList = group.group_type === "list";
  const icon = isTag ? "hash" : isList ? "rss" : "user";
  const field = isTag ? "watch_queries" : isList ? "watch_lists" : "watch_users";
  const nodes = (draft[field] || []).map((item, idx) => {
    const val = typeof item === "object" ? item.query : item;
    return h("span", { class: "chip mono" }, [
      iconEl(icon, 12), val,
      h("button", { class: "btn-icon chip-remove", title: "移除", "aria-label": `移除 ${val}`, html: svgIcon("close", 12), onClick: () => {
        if (state.actionBusy) return;
        confirmGroupMutation(group.group_id, {
          title: "移除订阅源？",
          desc: `将移除 ${val}，确认后立即保存并刷新。`,
          confirmText: "移除并保存",
          danger: true,
          successText: "订阅源已移除",
          mutate: () => {
            const next = [...(state.groupDrafts[group.group_id]?.[field] || [])];
            next.splice(idx, 1);
            updateDraft(group.group_id, field, next);
          },
        });
      }}),
    ]);
  });
  // 无效订阅源（仅博主分组的 watch_users 有隔离区）：可见、可显式移除
  if (!isTag && !isList) {
    (draft.invalid_watch_users || []).forEach((val, idx) => {
      nodes.push(h("span", { class: "chip chip-invalid mono", title: val }, [
        iconEl(icon, 12), val,
        h("span", { class: "badge badge-danger", text: "无效" }),
        h("button", { class: "btn-icon chip-remove", title: "移除", "aria-label": `移除 ${val}`, html: svgIcon("close", 12), onClick: () => {
          if (state.actionBusy) return;
          confirmGroupMutation(group.group_id, {
            title: "移除无效订阅源？",
            desc: `将从配置中移除 ${val}，确认后立即保存并刷新。`,
            confirmText: "移除并保存",
            danger: true,
            successText: "无效订阅源已移除",
            mutate: () => {
              const next = [...(state.groupDrafts[group.group_id]?.invalid_watch_users || [])];
              next.splice(idx, 1);
              updateDraft(group.group_id, "invalid_watch_users", next);
            },
          });
        }}),
      ]));
    });
  }
  container.replaceChildren(...nodes);
}

function renderEntities(group, draft) {
  const isTag = group.group_type === "tag";
  const isList = group.group_type === "list";
  const icon = isTag ? "hash" : isList ? "rss" : "user";
  const label = isTag ? "搜索查询词" : isList ? "Twitter List ID" : "博主用户名";

  const field = isTag ? "watch_queries" : isList ? "watch_lists" : "watch_users";
  const chipList = h("div", { class: "chip-list", "data-entity-chips": "true" });
  renderEntityChips(chipList, group, draft);

  return h("div", { class: "vstack" }, [
    h("div", { class: "section-head" }, [iconEl(icon, 16), `订阅源 — ${label}`]),
    chipList,
    h("div", { class: "input-action-row" }, [
      h("input", { id: isList ? "newWatchListInput" : "newEntityInput", type: "text", placeholder: isTag ? "#tag 或关键词" : isList ? "纯数字 List ID" : "推特用户名", onInput: () => {
        const err = document.getElementById("entityError");
        if (err) err.style.display = "none";
      } }),
      h("button", { class: "btn btn-sm", html: svgIcon("plus", 14), text: "添加", onClick: () => {
        if (state.actionBusy) return;
        if (isList) { addWatchList(group.group_id); }
        else {
          const inp = document.getElementById("newEntityInput");
          const v = inp?.value.trim(); if (!v) return;
          const existing = (draft[field] || []).some(item => (typeof item === "object" ? item.query : item) === v)
            || (draft.invalid_watch_users || []).includes(v);
          if (existing) { showToast("订阅源已存在"); return; }
          confirmGroupMutation(group.group_id, {
            title: "添加订阅源？",
            desc: `将添加 ${v}，确认后立即保存并刷新。`,
            confirmText: "添加并保存",
            successText: "订阅源已添加",
            mutate: () => {
              const current = state.groupDrafts[group.group_id]?.[field] || [];
              updateDraft(group.group_id, field, [...current, isTag ? { query: v, type: "tag" } : v]);
            },
          });
        }
      }}),
    ]),
    isList ? h("span", { id: "entityError", class: "field-error", style: { display: "none" } }) : null,
    (!isTag && !isList) ? renderBulkSubscriptions(group) : null,
  ]);
}

function renderBulkSubscriptions(group) {
  const area = h("textarea", { rows: 3, class: "ta-full", placeholder: "每行一个用户名，也可用逗号分隔" });
  const run = endpoint => {
    if (state.actionBusy) return;
    const entries = area.value.split(/[\n,，]+/).map(s => s.trim()).filter(Boolean);
    if (!entries.length) { showToast("请先填写用户名"); return; }
    const importing = endpoint.endsWith("/import");
    openConfirm({
      title: importing ? "确认导入订阅？" : "确认移除订阅？",
      desc: `共 ${entries.length} 个用户名，确认后立即保存并刷新。`,
      confirmText: importing ? "导入并保存" : "移除并保存",
      danger: !importing,
      action: () => withAction(async () => {
        const res = await apiPost(endpoint, { group_id: group.group_id, entries });
        delete state.groupDrafts[group.group_id];
        await reloadGroupState();
        const s = res?.summary || {};
        const notes = [
          s.invalid?.length ? `无效 ${s.invalid.length} 个` : "",
          s.duplicates?.length ? `重复 ${s.duplicates.length} 个` : "",
          s.missing?.length ? `不存在 ${s.missing.length} 个` : "",
        ].filter(Boolean);
        return { ...res, message: notes.length ? `${res.message}（${notes.join("，")}）` : res.message };
      }, undefined, { reload: false }),
    });
  };
  return h("div", { class: "subsection" }, [
    h("span", { class: "section-head", text: "批量导入 / 移除" }),
    area,
    h("div", { class: "input-action-row" }, [
      h("button", { class: "btn btn-sm", "data-busy-control": "true", text: "导入", onClick: () => run("web/subscriptions/import") }),
      h("button", { class: "btn btn-sm", "data-busy-control": "true", text: "移除", onClick: () => run("web/subscriptions/delete") }),
    ]),
  ]);
}

function renderTargets(group, draft) {
  const targets = draft.push_targets || [];
  const invalidTargets = draft.invalid_push_targets || [];
  const probe = state.targetProbeResults[group.group_id];

  return h("div", { class: "subsection" }, [
    h("div", { class: "row row-between" }, [
      h("span", { class: "section-head" }, [iconEl("send", 16), "推送目标 (UMO)"]),
      h("span", { class: "row" }, [
        probe?.summary ? h("span", {
          class: `badge ${probe.summary.invalid ? "badge-warn" : "badge-ok"}`,
          title: `平台在线 ${probe.summary.platform_found}/${probe.summary.total}，支持合并转发 ${probe.summary.supports_merged_forward}/${probe.summary.total}`,
          text: `连通性 ${probe.summary.valid}/${probe.summary.total}`,
        }) : null,
        h("button", { class: "btn btn-sm btn-ghost", html: svgIcon("probe", 14), text: "测试连通性", disabled: !targets.length && !invalidTargets.length, onClick: () => probeTargets(group.group_id) }),
      ]),
    ]),
    h("div", { class: "chip-list" },
      targets.map((t, idx) => {
        const info = probe?.targets?.find(x => x.umo === t);
        const { label, id: targetId } = replayTargetParts(t);
        return h("span", { class: "chip", title: t }, [
          h("span", { text: label }),
          targetId ? h("span", { class: "replay-target-id mono", text: replayTargetShortId(targetId) }) : null,
          info ? h("span", { class: `badge ${info.valid ? "badge-ok" : "badge-danger"}`, text: info.platform_kind || (info.valid ? "有效" : "失败") }) : null,
          h("button", { class: "btn-icon chip-remove", title: "移除", "aria-label": `移除 ${t}`, html: svgIcon("close", 12), onClick: () => {
            if (state.actionBusy) return;
            confirmGroupMutation(group.group_id, {
              title: "移除推送目标？",
              desc: `将移除 ${t}，确认后立即保存并刷新。`,
              confirmText: "移除并保存",
              danger: true,
              successText: "推送目标已移除",
              mutate: () => {
                const next = [...(state.groupDrafts[group.group_id]?.push_targets || [])];
                next.splice(idx, 1);
                updateDraft(group.group_id, "push_targets", next);
              },
            });
          }}),
        ]);
      })
    ),
    renderInvalidTargets(group, draft, probe),
    h("div", { class: "input-action-row" }, [
      h("input", { id: "newTargetInput", type: "text", placeholder: "aiocqhttp:GroupMessage:123456" }),
      h("button", { class: "btn btn-sm", html: svgIcon("plus", 14), text: "添加", onClick: () => {
        const inp = document.getElementById("newTargetInput");
        const v = inp?.value.trim(); if (!v) return;
        if (state.actionBusy) return;
        // 免确认路径用实时 draft 查重，避免保存失败重试时重复追加
        const live = state.groupDrafts[group.group_id] || draft;
        const known = new Set([...(live.push_targets || []), ...(live.invalid_push_targets || [])]);
        if (known.has(v)) { showToast("推送目标已存在"); return; }
        // 纯增量可逆操作，不走确认弹窗（移除/删除类仍保留确认）
        updateDraft(group.group_id, "push_targets", [...(live.push_targets || []), v]);
        saveGroup(group.group_id, "推送目标已添加");
      }}),
    ]),
    renderTargetBlacklist(group, draft),
  ]);
}

/* 无效推送目标：后端隔离保存的条目，在此可见、可显式移除；保存时按原文回写保留 */
function renderInvalidTargets(group, draft, probe) {
  const invalid = draft.invalid_push_targets || [];
  if (!invalid.length) return null;
  return h("div", { class: "vstack-sm" }, [
    h("span", { class: "hint", text: "无效推送目标（保存时保留原文，不会收到推送；需显式移除）" }),
    h("div", { class: "chip-list" },
      invalid.map((t, idx) => h("span", { class: "chip chip-invalid", title: t }, [
        h("span", { text: t }),
        probe?.targets?.find(x => x.umo === t.trim()) ? h("span", { class: "badge badge-danger", text: "无效" }) : null,
        h("button", { class: "btn-icon chip-remove", title: "移除", "aria-label": `移除 ${t}`, html: svgIcon("close", 12), onClick: () => {
          if (state.actionBusy) return;
          confirmGroupMutation(group.group_id, {
            title: "移除无效推送目标？",
            desc: `将从配置中移除 ${t}，确认后立即保存并刷新。`,
            confirmText: "移除并保存",
            danger: true,
            successText: "无效推送目标已移除",
            mutate: () => {
              const next = [...(state.groupDrafts[group.group_id]?.invalid_push_targets || [])];
              next.splice(idx, 1);
              updateDraft(group.group_id, "invalid_push_targets", next);
            },
          });
        }}),
      ]))
    ),
  ]);
}

function renderTargetBlacklist(group, draft) {
  const targets = draft.push_targets || [];
  const rows = Array.isArray(state.targetBlacklists) ? state.targetBlacklists : [];
  if (!targets.includes(state.targetBlacklistTarget)) state.targetBlacklistTarget = targets[0] || "";
  const selected = state.targetBlacklistTarget;
  const users = [...((rows.find(r => r.target_umo === selected) || {}).blocked_users || [])];
  const box = h("div", { class: "subsection" }, [
    h("div", { class: "section-head" }, [
      iconEl("ban", 16), "目标作者黑名单",
      h("span", { class: "hint", text: "跨分组共享，仅影响后台推送" }),
    ]),
  ]);
  if (!targets.length) {
    box.append(h("span", { class: "hint-subtle", text: "请先添加推送目标。" }));
    return box;
  }
  const select = createSelect({
    value: selected,
    options: targets.map(t => {
      const { label, id } = replayTargetParts(t);
      return { value: t, text: id ? `${label} · ${replayTargetShortId(id)}` : label };
    }),
  });
  select.onChange(v => { state.targetBlacklistTarget = v; rerenderTargetsSection(group.group_id); });
  const input = h("input", { type: "text", placeholder: "用户名或 @用户名" });
  box.append(
    h("div", { class: "input-action-row" }, [
      select, input,
      h("button", { class: "btn btn-sm", html: svgIcon("plus", 14), text: "加入", onClick: () => {
        const v = input.value.trim();
        if (!v) return;
        if (users.includes(v.replace(/^@+/, ""))) { showToast("用户名已在黑名单"); return; }
        confirmTargetBlacklist(group.group_id, selected, [...users, v.replace(/^@+/, "")], "加入黑名单？", "加入并保存", false);
      }}),
    ]),
    h("div", { class: "chip-list" }, users.length
      ? users.map(u => h("span", { class: "chip mono" }, [
          `@${u}`,
          h("button", { class: "btn-icon chip-remove", title: "移除", "aria-label": `移除 ${u}`, html: svgIcon("close", 12), onClick: () => confirmTargetBlacklist(group.group_id, selected, users.filter(x => x !== u), "移除黑名单用户？", "移除并保存", true) }),
        ]))
      : [h("span", { class: "hint-subtle", text: "黑名单为空" })]),
  );
  return box;
}

function saveTargetBlacklist(gid, target, users) {
  withAction(async () => {
    await apiPost("web/target-blacklists/update", { target_umo: target, blocked_users: users });
    const rest = state.targetBlacklists.filter(r => r.target_umo !== target);
    if (users.length) rest.push({ target_umo: target, blocked_users: [...users] });
    state.targetBlacklists = rest.sort((a, b) => a.target_umo.localeCompare(b.target_umo));
  }, "黑名单已更新", { reload: false, rerender: () => rerenderTargetsSection(gid) });
}

function confirmTargetBlacklist(gid, target, users, title, confirmText, danger) {
  openConfirm({
    title,
    desc: "确认后立即保存并刷新黑名单。",
    confirmText,
    danger,
    action: () => saveTargetBlacklist(gid, target, users),
  });
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
  confirmGroupMutation(groupId, {
    title: "添加 List 订阅？",
    desc: `将添加 List ${val}，确认后立即保存并刷新。`,
    confirmText: "添加并保存",
    successText: "List 订阅已添加",
    mutate: () => {
      const current = state.groupDrafts[groupId]?.watch_lists || [];
      updateDraft(groupId, "watch_lists", [...current, val]);
    },
  });
}

/* --------------------------------------------------------------------------
   Group Actions
   -------------------------------------------------------------------------- */
function confirmGroupMutation(gid, { title, desc, confirmText, danger = false, successText, mutate }) {
  openConfirm({
    title,
    desc,
    confirmText,
    danger,
    action: async () => {
      mutate();
      await saveGroup(gid, successText || "分组已保存");
    },
  });
}

function commitGroupField(gid, field, value) {
  updateDraft(gid, field, value);
  return saveGroup(gid, "分组设置已保存");
}

function createGroup() {
  if (!els.createGroupModal) return;
  state.createGroupReturnFocus = document.activeElement;
  els.createGroupName.value = "新订阅分组";
  // 类型选项每次重建：弹窗关闭后旧节点已不可见，重建可确保默认选中项正确
  const options = [
    { value: "blogger", label: "博主分组" },
    { value: "tag", label: "搜索订阅分组" },
    { value: "list", label: "List 分组" },
  ];
  const radioBox = h("div", { class: "group-type-options" },
    options.map(opt => h("label", { class: "group-type-option" }, [
      h("input", { type: "radio", name: "createGroupType", value: opt.value, checked: opt.value === "blogger" }),
      h("span", { text: opt.label }),
    ]))
  );
  // 选中态由 JS 同步 .selected 类（不依赖 :has，兼容较旧内核）
  const syncTypeSelection = () => radioBox.querySelectorAll(".group-type-option").forEach(l => {
    l.classList.toggle("selected", l.querySelector("input").checked);
  });
  radioBox.addEventListener("change", syncTypeSelection);
  syncTypeSelection();
  els.createGroupType.replaceChildren(radioBox);
  els.createGroupModal.classList.add("open");
  els.createGroupName.focus();
  els.createGroupName.select();
}

function closeCreateGroupModal() {
  if (!els.createGroupModal) return;
  els.createGroupModal.classList.remove("open");
  if (state.createGroupReturnFocus?.focus) state.createGroupReturnFocus.focus();
  state.createGroupReturnFocus = null;
}

async function submitCreateGroup() {
  const sel = els.createGroupType?.querySelector('input[name="createGroupType"]:checked');
  const gType = sel?.value || "blogger";
  const name = (els.createGroupName?.value || "").trim() || "新订阅分组";
  closeCreateGroupModal();
  await withAction(async () => {
    const res = await apiPost("web/groups/create", { name, group_type: gType });
    if (res?.group) state.selectedGroupId = res.group.group_id;
  }, "分组创建成功");
}

async function saveGroup(gid, successText = "分组已保存") {
  const d = state.groupDrafts[gid]; if (!d) return;
  await withAction(async () => {
    const res = await apiPost("web/groups/update", buildGroupPayload(d));
    delete state.groupDrafts[gid];
    delete state.targetProbeResults[gid];
    if (res?.group) {
      // update 响应自带最新分组（与 web/groups 同一序列化），原位替换省一次拉取
      state.groups = state.groups.map(g => (g.group_id === res.group.group_id ? res.group : g));
      try {
        state.overview = await apiGet("web/overview");
      } catch (err) {
        await reloadGroupState();
      }
    } else {
      await reloadGroupState();
    }
    syncGroupDrafts();
  }, successText, { reload: false, rerender: () => { markData("groups"); markData("overview"); } });
}

function confirmDeleteGroup(gid) {
  openConfirm({
    title: `删除分组 [${gid}]？`,
    desc: "此操作不可恢复，订阅规则与历史关联将被清理。",
    danger: true,
    action: () => withAction(async () => {
      await apiPost("web/groups/delete", { group_id: gid, force: true, confirm: "DELETE" });
      delete state.targetProbeResults[gid];
      state.selectedGroupId = "";
    }, "分组已删除"),
  });
}

async function probeTargets(gid) {
  await withAction(async () => {
    const res = await apiPost("web/targets/probe", { group_id: gid });
    state.targetProbeResults[gid] = res; rerenderTargetsSection(gid);
  }, "探测完成", { reload: false });
}

/* ==========================================================================
   11. Rail Health Status
   ========================================================================== */
/* 顶部环境徽标：调度器状态 + 失效目标提示（原侧栏三行 pill 的合并表达） */
function renderRailStatus() {
  const p = state.overview; if (!p) return;
  const s = p.scheduler || {}; const c = p.counts || {};
  const inv = c.invalid_push_targets || 0;
  const running = !!s.running && !!s.schedule_enabled;
  const el = els.railSchedulerStatus;
  if (!el) return;
  const cls = inv > 0 ? "danger" : running ? "ok" : "warn";
  const text = inv > 0
    ? `${inv} 个失效目标`
    : running ? "运行中" : (s.running ? "调度已停用" : "调度器未启动");
  el.className = `badge-env ${cls}`;
  el.replaceChildren(h("span", { class: "dot-live" }), h("span", { text }));
  // 三个旧 pill 的语义合并进徽标 title，悬停即可看到细分状态
  el.title = [
    `调度器：${s.running ? "运行中" : "未启动"}`,
    `后台检查：${s.schedule_enabled ? "已开启" : "已关闭"}`,
    `推送目标：${inv > 0 ? `${inv} 个异常` : "正常"}`,
  ].join("\n");
}

/* ==========================================================================
   12. Overview（Hero 卡 + 指标走廊 + 推送表格 + 副列运维）
   ========================================================================== */

/* 实例地址脱敏：只保留协议 + host[:port]，不带 path。
   总览与诊断页展示一律走这里，避免私有实例的路径片段出现在界面上。 */
function redactInstanceLabel(raw) {
  const text = String(raw || "").trim();
  if (!text) return "";
  const m = /^([a-z][a-z0-9+.-]*:\/\/)?([^/?#]+)(.*)$/i.exec(text);
  if (!m) return text;
  return `${m[1] || ""}${m[2]}`;
}

/* 全部分组的推送目标去重（按 UMO 字符串） */
function collectPushTargets() {
  const seen = new Set();
  const out = [];
  for (const g of state.groups) {
    for (const target of g.push_targets || []) {
      const umo = typeof target === "string" ? target : (target?.umo || "");
      if (!umo || seen.has(umo)) continue;
      seen.add(umo);
      out.push(umo);
    }
  }
  return out;
}

function renderOverview() {
  const root = els.overviewView; if (!root) return;
  const p = state.overview;
  if (!p) { root.replaceChildren(h("div", { class: "panel empty-note", text: "正在加载..." })); return; }
  const c = p.counts || {}; const s = p.scheduler || {};
  const cfg = p.config_summary || {}; const inst = p.instances || [];
  const att = p.attention_items || [];
  const stats = p.push_stats || null;
  const mt = p.maintenance || {};
  const cacheInfo = mt.cache;
  const seenInfo = mt.seen || null;

  // ---- 1. 顶部告警条：attention_items 逐条横幅（原型 attention-row） ----
  const attention = att.length
    ? h("div", { class: "attention-box" }, att.map(item => {
        const level = item.level === "error" ? "error" : (item.level === "warning" || item.level === "warn") ? "warning" : "info";
        return h("div", { class: `attention-row ${level}` }, [
          h("span", { class: "attention-title", text: item.title || "" }),
          h("span", { class: "attention-detail", text: `· ${item.detail || ""}` }),
          item.group_id
            ? h("button", {
                class: "attention-btn",
                type: "button",
                text: "前往处理",
                onClick: () => goGroupEditor(item.group_id),
              })
            : null,
        ]);
      }))
    : null;

  // ---- 2. Hero 卡：定时推送服务管道 ----
  const running = !!s.running && !!s.schedule_enabled;
  const lastCheck = s.last_check_at ? relativeTime(s.last_check_at) : "暂无记录";
  const targets = collectPushTargets();
  const targetText = targets.length
    ? targets.slice(0, 2).map(t => replayTargetShortLabel(t)).join(" · ") + (targets.length > 2 ? ` 等 ${targets.length} 个` : "")
    : "未配置";
  const primaryInstance = inst.length ? redactInstanceLabel(inst[0]) : "未配置";
  const filterOn = cfg.filter_reposts_enabled !== false;
  const hero = h("section", { class: "hero-card" }, [
    h("div", { class: "hero-main" }, [
      h("div", { class: "hero-title-row" }, [
        h("h2", { text: "定时推送服务管道" }),
        h("span", {
          class: `badge-status ${running ? "ready" : "warn"}`,
          text: running ? "正常运行中" : (s.running ? "调度已停用" : "调度器未启动"),
        }),
        h("span", { class: "branch-tag", text: `${cfg.check_interval_minutes || 0} 分钟轮询检查` }),
      ]),
      h("div", {
        class: "hero-desc",
        text: running
          ? `定时调度引擎运行正常。活跃分组已挂载 ${c.watch_users || 0} 位博主、${c.watch_queries || 0} 个搜索源与 ${c.watch_lists || 0} 个 List，通过 Nitter 实例抓取并分发。`
          : "调度引擎当前未在运行定时检查，请检查插件配置中的调度开关与分组启用状态。",
      }),
      h("div", { class: "hero-meta-grid" }, [
        h("div", { class: "meta-item" }, [
          h("span", { class: "meta-label", text: "上次检查时间" }),
          h("span", { class: "meta-value mono", text: lastCheck }),
        ]),
        h("div", { class: "meta-item" }, [
          h("span", { class: "meta-label", text: "已生效推送目标" }),
          h("span", { class: "meta-value", text: targetText, title: targets.join("\n") }),
        ]),
        h("div", { class: "meta-item" }, [
          h("span", { class: "meta-label", text: "主力解析节点" }),
          h("span", { class: "meta-value mono", text: primaryInstance, title: "路径片段已在界面脱敏" }),
        ]),
        h("div", { class: "meta-item" }, [
          h("span", { class: "meta-label", text: "全局转推过滤" }),
          h("span", { class: "meta-value", text: filterOn ? "已开启（跳过纯转推）" : "已关闭" }),
        ]),
      ]),
    ]),
    h("div", { class: "hero-actions" }, [
      h("button", { class: "btn btn-primary", type: "button", text: "查看最新推文", onClick: () => switchView("history") }),
      h("button", { class: "btn", type: "button", text: "探测节点延迟", onClick: () => switchView("mirror") }),
    ]),
  ]);

  // ---- 3. 四列指标卡 ----
  const goGroups = () => switchView("groups");
  const successRate = stats && stats.success_rate != null
    ? `${(stats.success_rate * 100).toFixed(1)}% 投递成功率`
    : "暂无投递记录";
  const metrics = h("section", { class: "metrics-row" }, [
    metricBox("历史推送总数", "SQLite 库", String(stats?.total ?? state.history?.total_count ?? 0),
      successRate, stats?.success_rate != null, () => switchView("history")),
    metricBox("活跃订阅分组", "分组规模", `${c.enabled_groups || 0} / ${c.groups || 0}`,
      `${c.watch_users || 0} 位博主 · ${c.watch_queries || 0} 个关键词 · ${c.watch_lists || 0} 个列表`, false, goGroups),
    metricBox("本地媒体缓存", "本地磁盘", cacheInfo ? formatBytes(cacheInfo.bytes) : "0 KB",
      cacheInfo && cacheInfo.files
        ? `${cacheInfo.files} 个文件（${cacheInfo.images || 0} 图 / ${cacheInfo.videos || 0} 视频）`
        : "当前无缓存文件", false, null),
    metricBox("已读去重记录", "Watermark", String(seenInfo?.total ?? 0),
      "防重复推送机制运行中", false, null),
  ]);

  // ---- 4. 最新推送记录（前 5 条）：原型单列布局，紧跟指标卡 ----
  const records = (state.history?.records || []).slice(0, 5);
  const recentSection = h("section", {}, [
    h("div", { class: "section-header", style: { marginTop: "28px" } }, [
      h("div", {}, [
        h("h3", { text: `最新推送记录（前 ${records.length || 5} 条）` }),
        h("div", { class: "section-sub", text: "点击任意记录可在右侧抽屉查看详情" }),
      ]),
      h("button", {
        class: "nav-btn",
        type: "button",
        text: `查看完整 ${state.history?.total_count ?? stats?.total ?? 0} 条记录 →`,
        onClick: () => switchView("history"),
      }),
    ]),
    records.length
      ? h("div", { class: "deploy-table" }, records.map(r => deployRow(r, { onSelect: () => openHistoryDetail(r.id) })))
      : h("div", { class: "deploy-table empty-note", text: "暂无推送记录" }),
  ]);

  root.replaceChildren(...[attention, hero, metrics, recentSection].filter(Boolean));
  renderTabCounts();
}

/* 指标卡：主值 + 一行 delta 说明；onClick 存在时整卡可点（键盘 Enter/Space 同样触发） */
function metricBox(label, sub, value, delta, deltaUp = false, onClick = null) {
  return h("div", {
    class: `metric-box${onClick ? " clickable" : ""}`,
    ...(onClick ? {
      role: "button",
      tabindex: "0",
      onClick,
      onkeydown: e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } },
    } : {}),
  }, [
    h("div", { class: "metric-top" }, [
      h("span", { class: "metric-label", text: label }),
      h("span", { class: "metric-sub", text: sub }),
    ]),
    h("div", { class: "metric-val mono", text: value }),
    h("div", { class: `metric-delta${deltaUp ? " up" : ""}`, text: delta }),
  ]);
}

/* 推送记录行：总览与历史共用，列与原型 deploy-row 一致
   （状态 / 正文+作者 / 目标 / 时间 / 来源实例 / 操作菜单）。 */
function deployRow(r, { compact = false, onSelect = null } = {}) {
  const status = r.delivery_status || "success";
  const glyphClass = status === "success" ? "ready" : status === "partial_failed" ? "warn" : "error";
  const title = (r.text_preview || "").trim() || (r.has_media ? "（该推文为纯图片/视频附件）" : "（无正文）");
  const author = r.username ? `@${r.username}` : (r.subscription_source || "");
  return h("div", {
    class: "deploy-row",
    role: onSelect ? "button" : null,
    tabindex: onSelect ? "0" : null,
    onClick: onSelect || undefined,
    onkeydown: onSelect
      ? e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); } }
      : undefined,
  }, [
    h("span", { class: `status-glyph ${glyphClass}`, html: svgIcon(status === "success" ? "check" : "alert", 13) }),
    h("div", { class: "deploy-info" }, [
      h("div", { class: "deploy-title", text: title, title }),
      h("div", { class: "deploy-sub" }, [
        h("span", { class: "branch-tag", text: r.group_name || r.group_id || "—" }),
        h("span", { class: "mono", text: author }),
        r.has_media ? h("span", { text: "· 附件媒体" }) : null,
      ]),
    ]),
    h("span", { class: "deploy-targets", text: replayTargetShortLabel(r.target_umo) }),
    h("span", { class: "deploy-time mono", text: compact ? relativeTime(r.pushed_at) : formatDateTime(r.pushed_at) }),
    h("span", { class: "deploy-duration mono", text: r.instance ? redactInstanceLabel(r.instance) : (r.source || "") }),
    h("button", {
      class: "menu-btn",
      type: "button",
      "aria-label": "操作",
      html: svgIcon("more", 14),
      onClick: e => { e.stopPropagation(); if (onSelect) onSelect(); },
    }),
  ]);
}

/* 推送目标的短标签：平台 + 类型 + 目标号，避免整串 UMO 撑破表格列 */
function replayTargetShortLabel(umo) {
  const { label, id } = replayTargetParts(umo);
  return id ? `${label} ${id}` : label;
}


function goGroupEditor(gid) {
  state.selectedGroupId = gid;
  switchView("groups");
  // 分组视图冲刷后列表才存在，选中态与抽屉都在这里收口
  renderGroupCards();
  openGroupSheet(gid);
}

function badge(text) { return h("span", { class: "badge", text }); }

/* ==========================================================================
   13. History — Tweet-style Feed
   ========================================================================== */
function syncHistoryGroupOptions() {
  const sel = els.historyGroupSelect;
  if (!sel) return;
  const current = sel.value;
  const options = [
    { value: "", text: "全部分组" },
    ...state.groups.map(g => ({ value: g.group_id, text: g.name })),
  ];
  if (sel.setOptions) {
    sel.setOptions(options);
    return;
  }
  sel.replaceChildren(...options.map(o => h("option", { value: o.value, text: o.text })));
  sel.value = options.some(o => o.value === current) ? current : "";
}

function renderHistory() {
  const root = els.historyView; if (!root) return;
  const data = state.history;
  const recs = (data && data.records) || [];

  // Sync group dropdown & pager
  syncHistoryGroupOptions();
  if (els.historyPageLabel && data) {
    els.historyPageLabel.textContent = `${data.page || 1} / ${data.total_pages || 1} 页 · 共 ${data.total_count || 0} 条`;
  }
  if (els.historyTitle && data) {
    els.historyTitle.textContent = `推送历史记录（共 ${data.total_count || 0} 条）`;
  }
  if (els.historyPrevBtn && data) els.historyPrevBtn.disabled = !data.has_prev;
  if (els.historyNextBtn && data) els.historyNextBtn.disabled = !data.has_next;

  const content = els.historyContent;
  if (!recs.length) {
    content.replaceChildren(h("div", { class: "deploy-table empty-note", text: "暂无推送历史记录" }));
    renderHistoryBatchBar();
    return;
  }

  content.replaceChildren(h("div", { class: "deploy-table" }, recs.map(r => historyRow(r))));
  renderHistoryBatchBar();
}

/* 历史行：勾选框 + 整行点选（双击/划选保护），点开走详情抽屉。
   dataset.recordId 供 syncHistoryCheckboxes 原位同步，不重建行。 */
function historyRow(r) {
  const st = r.delivery_status;
  const stLabel = st === "success" ? "已送达" : st === "partial_failed" ? "部分失败" : "发送失败";
  const glyphClass = st === "success" ? "ready" : st === "partial_failed" ? "warn" : "error";
  const hasMedia = !!r.has_media;
  const title = (r.text_preview || "").trim() || (hasMedia ? "（该推文为纯图片/视频附件）" : "（无文字内容）");

  // Multi-select checkbox：click 只 stopPropagation（禁止 preventDefault，会回滚
  // 原生勾选翻转并吞掉 change 事件），切换统一走 onChange。
  const checkbox = h("input", {
    type: "checkbox",
    "aria-label": `选择 ${r.username || "unknown"} 的记录以批量重推`,
    checked: state.historySelection.has(r.id),
    onClick: e => e.stopPropagation(),
    onChange: e => setHistoryRecordSelected(r.id, e.target.checked, e.target),
  });

  return h("div", {
    class: "deploy-row",
    title: "点击查看详情",
    dataset: { recordId: String(r.id) },
    onClick: e => {
      if (e.detail > 1) return; // 双击/多击序列只认第一击
      if (window.getSelection()?.type === "Range") return; // 正在划选正文，不当作点选
      if (e.target.closest("input, button, a")) return;   // 勾选框与操作按钮各自处理
      openHistoryDetail(r.id);
    },
  }, [
    h("span", { class: "deploy-check" }, [checkbox]),
    h("div", { class: "deploy-info" }, [
      h("div", { class: "deploy-title", text: title, title }),
      h("div", { class: "deploy-sub" }, [
        h("span", { class: "mono", text: r.username ? `@${r.username}` : "unknown" }),
        h("span", { text: relativeTime(r.pushed_at) }),
        h("span", { class: `branch-tag ${glyphClass}`, text: stLabel }),
        r.group_name ? h("span", { class: "branch-tag", text: r.group_name }) : null,
        hasMedia ? h("span", { class: "branch-tag", text: "附件媒体" }) : null,
      ]),
    ]),
    h("span", { class: "deploy-targets", text: replayTargetShortLabel(r.target_umo) }),
    h("span", { class: "deploy-time", text: formatDateTime(r.pushed_at) }),
    h("span", { class: "deploy-duration", text: r.source || "" }),
    h("span", { class: "deploy-row-actions" }, [
      h("button", {
        class: "btn btn-ghost btn-sm",
        type: "button",
        title: "重推这条记录",
        html: svgIcon("refresh", 14),
        onClick: e => { e.stopPropagation(); replayHistory(r.id, r.replay_target_options); },
      }),
    ]),
  ]);
}

/* 推文详情抽屉：正文 / 原推链接 / 投递信息 / 错误追踪终端 / 重推目标选择 */
function openHistoryDetail(recordId) {
  const recs = (state.history && state.history.records) || [];
  const r = recs.find(x => x.id === recordId);
  if (!r) return;
  const hasMedia = !!r.has_media;
  const body = h("div", { class: "sheet-detail-flow" }, [
    // 1. 顶部标签与作者时间
    h("div", { class: "detail-header-card" }, [
      h("div", { class: "row row-wrap" }, [
        h("span", { class: "badge mono", text: `#${r.id}` }),
        h("span", { class: "badge", text: r.group_name || r.group_id || "-" }),
        h("span", {
          class: `badge ${r.delivery_status === "success" ? "badge-ok" : r.delivery_status === "partial_failed" ? "badge-warn" : "badge-danger"}`,
          text: r.delivery_status === "success" ? "已送达" : r.delivery_status === "partial_failed" ? "部分失败" : "发送失败",
        }),
        hasMedia ? h("span", { class: "badge", text: "含媒体" }) : null,
      ]),
      h("div", { class: "detail-author-row" }, [
        h("span", { class: "detail-author-name", text: r.username ? `@${r.username}` : "未知作者" }),
        h("span", { class: "detail-sep", text: "·" }),
        h("span", { class: "detail-time mono", text: formatDateTime(r.pushed_at) || "-" }),
      ]),
    ]),

    // 2. 推文正文区：排版舒适的文本展示
    h("div", { class: "detail-section" }, [
      h("div", { class: "detail-section-title" }, [
        h("span", { text: "推文正文" }),
      ]),
      h("div", { class: "tweet-content-card" }, [
        h("div", {
          class: "tweet-content-text",
          text: r.text_preview || (hasMedia ? "（该推文为纯图片/视频附件，无文字内容）" : "（无文字内容）"),
        }),
      ]),
    ]),

    // 3. 原推地址
    r.original_link ? h("div", { class: "detail-section" }, [
      h("div", { class: "detail-section-title" }, [
        h("span", { text: "原推地址" }),
      ]),
      h("a", {
        href: r.original_link,
        target: "_blank",
        rel: "noopener noreferrer",
        class: "original-tweet-link",
      }, [
        h("span", { class: "mono link-text", text: r.original_link }),
        h("span", { class: "link-icon", html: svgIcon("external", 13) }),
      ]),
    ]) : null,

    // 4. 投递链路元信息网格
    h("div", { class: "detail-section" }, [
      h("div", { class: "detail-section-title" }, [
        h("span", { text: "投递链路与来源" }),
      ]),
      h("div", { class: "detail-meta-grid" }, [
        h("div", { class: "detail-meta-item" }, [
          h("span", { class: "detail-meta-k", text: "投递目标" }),
          h("span", { class: "detail-meta-v mono", text: replayTargetShortLabel(r.target_umo) || "-" }),
        ]),
        h("div", { class: "detail-meta-item" }, [
          h("span", { class: "detail-meta-k", text: "触发来源" }),
          h("span", { class: "detail-meta-v", text: r.source === "scheduled" ? "定时轮询 (scheduled)" : (r.source || "-") }),
        ]),
        h("div", { class: "detail-meta-item detail-meta-full" }, [
          h("span", { class: "detail-meta-k", text: "解析节点" }),
          h("span", { class: "detail-meta-v mono", text: redactInstanceLabel(r.instance) || "-" }),
        ]),
      ]),
    ]),

    // 5. 错误终端（macOS 仿苹果黑曜石终端展示）
    r.delivery_error ? h("div", { class: "detail-section" }, [
      h("div", { class: "detail-section-title error" }, [
        h("span", { text: "投递追踪日志" }),
      ]),
      renderErrorTerminal(r.delivery_error, {
        title: `delivery_trace_#${r.id}.log`,
        status: r.delivery_status === "partial_failed" ? "PARTIAL" : "FAILED",
      }),
    ]) : null,
  ]);
  const footer = [
    h("button", {
      class: "btn btn-sm btn-primary",
      type: "button",
      text: "重推此条",
      onClick: () => { closeSheet(); replayHistory(r.id, r.replay_target_options); },
    }),
    h("button", { class: "btn btn-sm", type: "button", text: "关闭", onClick: () => closeSheet() }),
  ];
  openSheet({ title: "推文详情", body, footer });
}

// 更新一条记录的选中态并同步勾选框视觉；不整卡重渲染，避免键盘焦点丢失。
function setHistoryRecordSelected(id, selected, checkbox) {
  if (selected) state.historySelection.add(id);
  else state.historySelection.delete(id);
  if (checkbox) checkbox.checked = selected;
  renderHistoryBatchBar();
}

/* 把 DOM 里每行的勾选框同步回集合状态；全选/清除走原位同步，不重建行 */
function syncHistoryCheckboxes() {
  const cards = els.historyContent?.querySelectorAll("[data-record-id]") || [];
  for (const card of cards) {
    const raw = card.dataset.recordId ?? "";
    const id = /^\d+$/.test(raw) ? Number(raw) : raw;
    const box = card.querySelector(".deploy-check input");
    if (box) box.checked = state.historySelection.has(id);
  }
}

function clearHistorySelection() {
  state.historySelection.clear();
  syncHistoryCheckboxes();
  renderHistoryBatchBar();
}

function toggleHistorySelectAllPage() {
  const recs = (state.history && state.history.records) || [];
  if (!recs.length) return;
  const pageIds = recs.map(r => r.id);
  const allSelected = pageIds.every(id => state.historySelection.has(id));
  if (allSelected) pageIds.forEach(id => state.historySelection.delete(id));
  else pageIds.forEach(id => state.historySelection.add(id));
  syncHistoryCheckboxes();
  renderHistoryBatchBar();
}

function renderHistoryBatchBar() {
  const bar = els.historyBatchBar;
  if (!bar) return;
  const recs = (state.history && state.history.records) || [];
  if (recs.length) {
    const allSelected = recs.every(r => state.historySelection.has(r.id));
    if (els.historySelectAllBtn) {
      els.historySelectAllBtn.textContent = allSelected ? "清除本页" : "全选本页";
      els.historySelectAllBtn.disabled = false;
    }
  } else if (els.historySelectAllBtn) {
    els.historySelectAllBtn.textContent = "全选本页";
  }
  bar.hidden = state.historySelection.size === 0;
  if (bar.hidden) { bar.replaceChildren(); return; }
  bar.replaceChildren(
    h("span", { class: "history-batch-count", text: `已选 ${state.historySelection.size} 条` }),
    h("span", { class: "history-batch-hint", text: "将按分组合并转发重推" }),
    h("div", { class: "history-batch-actions" }, [
      h("button", {
        class: "btn btn-sm btn-primary",
        html: iconEl("send", 14).outerHTML,
        text: "批量重推",
        onClick: replayHistoryBatch,
      }),
      h("button", {
        class: "btn btn-sm btn-ghost",
        text: "取消",
        onClick: clearHistorySelection,
      }),
    ]),
  );
}

function replayHistoryBatch() {
  const recs = (state.history && state.history.records) || [];
  const selected = recs.filter(r => state.historySelection.has(r.id));
  if (!selected.length) { clearHistorySelection(); return; }

  // Group cards by their original group; each section picks its own targets.
  const byGroup = new Map();
  for (const r of selected) {
    if (!byGroup.has(r.group_id)) byGroup.set(r.group_id, { name: r.group_name || r.group_id, cards: [] });
    byGroup.get(r.group_id).cards.push(r);
  }
  // Union of target options per group (available first, umo deduped).
  const sections = [...byGroup.entries()].map(([gid, info]) => {
    const optionsByUmo = new Map();
    for (const card of info.cards) {
      for (const opt of (card.replay_target_options || [])) {
        if (!opt?.umo || optionsByUmo.has(opt.umo)) continue;
        optionsByUmo.set(opt.umo, { umo: opt.umo, available: !!opt.available });
      }
    }
    const options = [...optionsByUmo.values()].sort((a, b) => (b.available ? 1 : 0) - (a.available ? 1 : 0));
    return { gid, name: info.name, count: info.cards.length, options };
  });

  const boxes = new Map(); // gid -> container element
  const desc = h("div", { class: "replay-groups" }, [
    h("div", { text: "按分组选择重推目标（已下线目标不可选）；跨分组的记录会各自独立推送：" }),
    ...sections.map(sec => {
      const box = h("div", { class: "replay-targets" },
        sec.options.map(o => {
          const { label, id: targetId } = replayTargetParts(o.umo);
          return h("label", { class: `replay-target${o.available ? "" : " offline"}`, title: o.umo || "" }, [
            h("input", { type: "checkbox", checked: !!o.available, disabled: !o.available, value: o.umo || "" }),
            h("span", { class: "replay-target-label", text: o.available ? label : `${label}（已下线）` }),
            targetId ? h("span", { class: "replay-target-id mono", text: replayTargetShortId(targetId) }) : null,
          ]);
        }));
      boxes.set(sec.gid, box);
      return h("div", { class: "replay-group" }, [
        h("div", { class: "replay-group-title", text: `分组：${sec.name}（${sec.count} 条）` }),
        box,
      ]);
    }),
  ]);

  openConfirm({
    title: `批量重推（${selected.length} 条）`,
    desc,
    confirmText: "批量重推",
    action: () => {
      const targetsByGroup = {};
      for (const sec of sections) {
        const umos = [...(boxes.get(sec.gid)?.querySelectorAll("input:checked") || [])].map(i => i.value).filter(Boolean);
        if (!umos.length) {
          showToast(`分组「${sec.name}」未选择目标，已取消批量重推`);
          return undefined;
        }
        targetsByGroup[sec.gid] = umos;
      }
      return withAction(async () => {
        const res = await apiPost("web/history/replay", {
          record_ids: [...state.historySelection],
          targets_by_group: targetsByGroup,
        });
        state.historySelection.clear();
        const skipped = Array.isArray(res?.skipped) ? res.skipped : [];
        let message = `批量重推已触发（${res?.triggered ?? 0} 条），稍后刷新历史查看结果`;
        if (skipped.length) {
          const reasons = [...new Set(skipped.map(item => item.reason || item.group_id || item.record_id || "").filter(Boolean))].join("、");
          message += `；跳过 ${skipped.length} 项${reasons ? `：${reasons}` : ""}`;
        }
        return { ...res, message };
      }, "", { reload: false, rerender: renderHistory });
    },
  });
}

async function loadHistoryPage(delta) {
  if (!state.history) return;
  const offset = delta < 0 ? state.history.prev_offset : state.history.next_offset;
  if (offset === null || offset === undefined) return;
  state.historyOffset = offset;
  await withAction(() => refreshHistoryData(), false, { reload: false });
}

/* 孤儿列表的纯查询渲染：检测按钮经 detectHistoryOrphans 走 busy 仪式，
   删除残留后的 rerender 直接调用本函数（外层动作未结束时 withAction 会空转） */
async function renderHistoryOrphans() {
  const res = await apiGet("web/history/orphans");
  const ops = res.orphans || [];
  if (!ops.length) {
    const note = h("div", { class: "orphan-notice row row-between" }, [
      h("span", { class: "badge badge-ok", text: "未检测到废弃分组的残留历史" }),
      h("button", {
        class: "feedback-close",
        type: "button",
        title: "关闭",
        "aria-label": "关闭提示",
        text: "×",
        onClick: () => { note.remove(); },
      }),
    ]);
    els.historyOrphanResult.replaceChildren(note);
    clearTimeout(els.historyOrphanResult._timer);
    els.historyOrphanResult._timer = setTimeout(() => {
      note.classList.add("fade-out");
      setTimeout(() => { if (els.historyOrphanResult.contains(note)) note.remove(); }, 240);
    }, 3500);
    return;
  }
  els.historyOrphanResult.replaceChildren(h("div", { class: "panel" }, [
    h("div", { class: "panel-head" }, [
      h("h3", { text: `废弃分组残留 (${ops.length})` }),
      h("button", {
        class: "btn btn-ghost btn-sm",
        type: "button",
        text: "收起",
        onClick: () => els.historyOrphanResult.replaceChildren(),
      }),
    ]),
    h("div", { class: "chip-list" }, ops.map(o => h("span", { class: "chip mono" }, [
      `${o.group_id} (${o.record_count}条)`,
      h("button", { class: "btn btn-danger btn-sm", text: "删除", onClick: () => confirmDeleteOrphan(o.group_id) }),
    ]))),
  ]));
}

async function detectHistoryOrphans() {
  await withAction(() => renderHistoryOrphans(), "检测完成", { reload: false });
}

function confirmDeleteOrphan(gid) {
  openConfirm({
    title: `删除废弃分组 [${gid}] 历史？`,
    desc: "该分组已不存在，删除后相关记录彻底清除。",
    danger: true,
    action: () => withAction(() => apiPost("web/history/orphans/delete", { group_id: gid, confirm: "DELETE" }), "删除成功", { reload: false, rerender: () => renderHistoryOrphans().catch(err => showAlert(err.message || "孤儿列表刷新失败", "warn")) }),
  });
}

const UMO_PLATFORM_LABELS = {
  aiocqhttp: "QQ", onebot: "QQ", onebot_v11: "QQ", napcat: "QQ",
  qqofficial: "QQ 官方", telegram: "Telegram", lark: "飞书",
};
const UMO_KIND_LABELS = { GroupMessage: "群聊", FriendMessage: "私聊" };
function replayTargetParts(umo) {
  const raw = String(umo || "");
  const parts = raw.split(":");
  if (parts.length < 3) return { label: raw || "未知目标", id: "" };
  const platform = UMO_PLATFORM_LABELS[parts[0]] || parts[0];
  const kind = UMO_KIND_LABELS[parts[1]] || parts[1];
  return { label: `${platform} · ${kind}`, id: parts.slice(2).join(":") };
}
function replayTargetShortId(id) {
  return id.length > 14 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id;
}
function replayHistory(id, options) {
  let box = null;
  let desc;
  if (Array.isArray(options) && options.length) {
    const sorted = [...options].sort((a, b) => (b.available ? 1 : 0) - (a.available ? 1 : 0));
    box = h("div", { class: "replay-targets" },
      sorted.map(o => {
        const { label, id: targetId } = replayTargetParts(o.umo);
        return h("label", { class: `replay-target${o.available ? "" : " offline"}`, title: o.umo || "" }, [
          h("input", { type: "checkbox", checked: !!o.available, disabled: !o.available, value: o.umo || "" }),
          h("span", { class: "replay-target-label", text: o.available ? label : `${label}（已下线）` }),
          targetId ? h("span", { class: "replay-target-id mono", text: replayTargetShortId(targetId) }) : null,
        ]);
      }));
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

/* ==========================================================================
   14. Mirror Probe（能力矩阵 + 相对耗时条 + 真实日志终端）
   ========================================================================== */
function renderMirror() {
  renderMirrorBase();
  renderMirrorTerminal();
}

function renderMirrorBase() {
  if (!els.instanceList) return;
  const inst = (state.overview && state.overview.instances) || [];
  if (!inst.length) {
    els.instanceList.replaceChildren(h("span", { class: "badge badge-warn", text: "无已配置实例" }));
  } else {
    els.instanceList.replaceChildren(...inst.map(u => h("button", {
      type: "button",
      class: "chip chip-action mono",
      text: redactInstanceLabel(u),
      title: u,
      onClick: () => { if (els.mirrorInstance) els.mirrorInstance.value = u; },
    })));
  }
  renderMirrorTerminal();
}

/* 终端跟随探测结果：有结果时挂在第一张实例卡内（原型位置），
   无结果时在结果区底部单独放一个空态终端，方便直接看最近日志。 */
function renderMirrorTerminal() {
  const host = els.mirrorResult;
  if (!host) return;
  host.querySelectorAll(".mirror-terminal").forEach(el => el.remove());
  const card = host.querySelector(".inst-card-large:not(.empty-note)");
  const term = h("div", { class: "mac-terminal mirror-terminal" });
  if (card) card.appendChild(term);
  else host.appendChild(term);

  const label = state.logsMax
    ? `节点健康并发探针 — probe.sh（最近 ${state.logs.length}/${state.logsMax} 条）`
    : "节点健康并发探针 — probe.sh";
  renderTerminal(term, state.logs, {
    title: label,
    empty: "暂无插件日志事件。触发一次检查或探测后这里会出现分级输出。",
  });
}

async function probeMirror(e) {
  if (e) e.preventDefault();
  if (state.actionBusy) return;
  const username = els.mirrorUsername.value.trim();
  const query = els.mirrorQuery.value.trim();
  const list_id = els.mirrorListId.value.trim();
  if (!username && !query && !list_id) {
    showToast("请至少填写一项测试目标（用户名、搜索标签或关键词、List ID）");
    return;
  }
  const payload = {
    username: username || undefined,
    query: query || undefined,
    list_id: els.mirrorListId.value.trim() || undefined,
    limit: parseInt(els.mirrorLimit.value, 10) || 5,
    instance: els.mirrorInstance.value.trim() || undefined,
  };
  state.actionBusy = true; setBusy(true); hideAlert();
  els.mirrorResult.replaceChildren(h("div", { class: "inst-card-large empty-note", text: "探测中..." }));
  try {
    const res = await apiPost("web/mirror/probe", payload);
    const results = res.results || [];
    if (!results.length) {
      els.mirrorResult.replaceChildren(h("div", { class: "inst-card-large empty-note", text: "未返回结果" }));
    } else {
      els.mirrorResult.replaceChildren(...results.map(r => {
        const checks = r.checks || {};
        const durations = Object.values(checks).filter(c => c && c.success).map(c => c.duration_ms || 0);
        const maxMs = Math.max(1, ...durations);
        const avg = durations.length
          ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length)
          : 0;
        const rows = [
          checks.rss_user ? instCheckRow("RSS 博主多账号合并数据流 (Multi-User Stream)", checks.rss_user, maxMs) : null,
          checks.html_user ? instCheckRow("HTML 后备解析爬虫 (Fallback Search Scraper)", checks.html_user, maxMs) : null,
          checks.search ? instCheckRow("标签 / 关键词搜索端点 (Tag Query Endpoint)", checks.search, maxMs) : null,
          checks.list ? instCheckRow("List 时间线端点 (List Timeline)", checks.list, maxMs) : null,
        ].filter(Boolean);

        return h("div", { class: "inst-card-large" }, [
          h("div", { class: "inst-head" }, [
            h("div", {}, [
              h("div", { class: "inst-title-row" }, [
                h("span", { class: "mono", text: redactInstanceLabel(r.instance), title: r.instance }),
                h("span", {
                  class: `badge-status ${r.success ? "ready" : "warn"}`,
                  text: r.success ? "● 生效中" : "● 有异常",
                }),
              ]),
              h("div", { class: "inst-desc", text: r.success
                ? "自建节点 · 承载博主多账号流、列表流与标签搜索"
                : "部分能力不可用，详见下方检查项" }),
            ]),
            durations.length ? h("div", { class: "inst-latency" }, [
              h("div", { class: "value", text: String(avg) }),
              h("span", { class: "unit", text: " ms" }),
              h("div", { class: "label", text: "平均请求延迟" }),
            ]) : null,
          ]),
          h("div", { class: "probe-checks" }, rows.length ? rows : [
            h("div", { class: "inst-row" }, [
              h("span", { text: "未指定测试目标（用户名 / 搜索词 / List ID）" }),
              h("span", { class: "mono", text: "skipped" }),
            ]),
          ]),
        ]);
      }));
    }
    // 探测完成后立刻拉一次日志，让终端反映这次动作产生的事件
    await reloadLogs().catch(() => {});
    renderMirrorTerminal();
  } catch (err) {
    els.mirrorResult.replaceChildren(h("div", { class: "alert error", text: `探测失败: ${err.message}` }));
    renderMirrorTerminal();
  } finally {
    state.actionBusy = false; setBusy(false);
  }
}

/* 单项能力检查行：原型 inst-row（左标签 + 右状态/耗时 + 相对耗时条） */
function instCheckRow(label, item, maxMs = 1) {
  const ok = item.success;
  const ms = Math.round(item.duration_ms || 0);
  // 相对条以本次探测最慢的一项为满格，便于横向比较各端点延迟
  const pct = ok ? Math.max(8, Math.round((ms / Math.max(1, maxMs)) * 100)) : 0;
  return h("div", { class: "inst-row" }, [
    h("span", { text: label }),
    ok
      ? h("span", { class: "mono ok", text: `200 OK · ${item.tweet_count || 0} 条 · ${ms}ms` })
      : h("span", { class: "mono bad", title: item.error || "", text: `FAILED · ${item.error || "失败"}` }),
    ok
      ? h("span", { class: "probe-meter", "aria-hidden": "true" }, [
          h("span", { class: "probe-meter-fill", style: { width: `${pct}%` } }),
        ])
      : null,
  ]);
}

/* ==========================================================================
   14b. Storage — 媒体缓存构成 + 已读去重水位线（原型「存储运维」页）
   ========================================================================== */
function renderStorage() {
  const root = els.storageContent;
  if (!root) return;
  const p = state.overview || {};
  const mt = p.maintenance || {};
  const cache = mt.cache;
  const seen = mt.seen || null;
  const seenByGroup = (seen && seen.by_group) || {};

  if (els.cleanCacheBtn) {
    els.cleanCacheBtn.textContent = cache && cache.bytes
      ? `清空全部媒体缓存 (${formatBytes(cache.bytes)})`
      : "清空全部媒体缓存";
  }

  const files = cache?.files || 0;
  const pct = n => (files ? Math.round((n / files) * 100) : 0);

  const cacheBox = h("div", { class: "storage-box" }, [
    h("h4", { text: "媒体缓存占用分布" }),
    h("div", { class: "storage-sub", text: cache && files
      ? `总计 ${formatBytes(cache.bytes)} 磁盘占用（共 ${files} 个附件文件）`
      : "当前没有缓存文件" }),
    h("div", { class: "meter-bar" }, [
      h("div", { class: "meter-seg img", style: { width: `${pct(cache?.images || 0)}%` } }),
      h("div", { class: "meter-seg vid", style: { width: `${pct(cache?.videos || 0)}%` } }),
      h("div", { class: "meter-seg oth", style: { width: `${pct(cache?.other || 0)}%` } }),
    ]),
    h("div", { class: "meter-legend" }, [
      h("span", {}, [h("i", { class: "meter-seg img" }), `图片（${cache?.images || 0} 个文件）`]),
      h("span", {}, [h("i", { class: "meter-seg vid" }), `视频（${cache?.videos || 0} 个文件）`]),
      h("span", {}, [h("i", { class: "meter-seg oth" }), `其他（${cache?.other || 0} 个文件）`]),
    ]),
  ]);

  const seenRows = state.groups.length
    ? state.groups.map(g => h("div", { class: "inst-row" }, [
        h("span", { text: g.name }),
        h("span", { class: "mono", text: `${seenByGroup[g.group_id] ?? 0} 条已记录` }),
      ]))
    : [h("div", { class: "inst-row" }, [
        h("span", { text: "尚无分组" }),
        h("span", { class: "mono", text: "—" }),
      ])];

  const seenBox = h("div", { class: "storage-box" }, [
    h("h4", { text: "推文去重与已读数据库 (Seen DB)" }),
    h("div", { class: "storage-sub", text: "记录已推送推文状态 ID，防止重复触发" }),
    h("div", { class: "vstack-sm", style: { marginTop: "14px" } }, seenRows),
    h("div", { class: "row", style: { marginTop: "14px", flexWrap: "wrap" } }, [
      h("span", { class: "hint", text: seen ? `合计 ${seen.total} 条记录` : "记录数：未知" }),
      h("button", { class: "nav-btn", type: "button", text: "重置推送记录", onClick: confirmClearSeen }),
    ]),
  ]);

  root.replaceChildren(cacheBox, seenBox);
}


/* ==========================================================================
   15. Plugin Config V2 — 双栏导航 + 字段卡片 + 草稿保存
   细粒度更新：控件提交只改草稿 + 局部 UI（操作条/导航徽标/恢复默认按钮），
   不再整树重建；真脏集合 configDirtyKeys 增量维护，杜绝全量 JSON.stringify。
   ========================================================================== */
const configDirtyKeys = new Set();
const configKeyGroup = new Map();

/* 配置数据（重）加载后重建 key→分组 索引，并按新服务器值重算真脏集合 */
function buildConfigIndex() {
  configKeyGroup.clear();
  configDirtyKeys.clear();
  const groups = state.config?.groups || [];
  for (const g of groups) {
    for (const item of (g.items || [])) configKeyGroup.set(item.key, g.key);
  }
  for (const [key, val] of Object.entries(state.configDraft)) {
    const item = findConfigItem(key);
    if (item && JSON.stringify(val) !== JSON.stringify(item.value)) configDirtyKeys.add(key);
    else delete state.configDraft[key];
  }
}

function configItemsOf(group) {
  const q = state.configSearch.trim().toLowerCase();
  if (!q) return group.items;
  return group.items.filter(
    i => (i.description || "").toLowerCase().includes(q)
      || i.key.toLowerCase().includes(q)
  );
}

function configDirtyCount(group) {
  let n = 0;
  for (const key of configDirtyKeys) {
    if (configKeyGroup.get(key) === group.key) n++;
  }
  return n;
}

// 守卫与操作条同口径的"真脏":仅统计与当前值不同的草稿键,
// 等值残键(改走又改回等)不触发离开确认;保存时会由 saveConfigDraft 清理。
function configDraftDirty() {
  return configDirtyKeys.size > 0;
}

function renderConfig() {
  const root = els.configView;
  if (!root) return;
  const data = state.config;
  if (!data) {
    root.replaceChildren(h("div", { class: "panel empty-note", text: state.configError ? "配置加载失败，请刷新重试" : "正在加载..." }));
    return;
  }
  const groups = Array.isArray(data.groups) ? data.groups : [];
  if (!groups.length) { root.replaceChildren(h("div", { class: "panel empty-note", text: "配置数据异常，请刷新重试" })); return; }
  if (!state.configActive || !groups.some(g => g.key === state.configActive)) {
    state.configActive = groups[0].key;
  }
  const active = groups.find(g => g.key === state.configActive);

  // 左:分组导航
  const nav = h("div", { class: "panel config-nav" }, [
    h("div", { class: "panel-head" }, [h("h3", { text: "配置分组" })]),
    h("input", {
      type: "text", placeholder: "搜索配置…", value: state.configSearch,
      onInput: onConfigSearchInput,
    }),
    h("div", { class: "config-nav-list" }, groups.map(configNavItem)),
  ]);

  // 右:当前组
  const fields = h("div", { class: "config-fields" }, configFieldsChildren(active));

  const bar = h("div", { class: "config-actionbar" }, [
    h("div", { class: "config-bar-state" }),
    h("div", { class: "actions" }, [
      h("button", {
        class: "btn btn-sm", text: "放弃更改", "data-config-discard": "true",
        disabled: !configDirtyKeys.size || state.configSaving,
        onClick: () => maybeLeaveConfigGroup(() => { state.configDraft = {}; configDirtyKeys.clear(); renderConfig(); }),
      }),
      h("button", {
        class: "btn btn-sm btn-primary", "data-config-save": "true",
        text: state.configSaving ? "保存并重载中…" : "保存并重载",
        disabled: !configDirtyKeys.size || state.configSaving,
        onClick: saveConfigDraft,
      }),
    ]),
  ]);

  root.replaceChildren(bar, h("div", { class: "config-layout" }, [nav, fields]));
  renderConfigBarState();
}

/* 操作条与导航徽标的局部刷新：控件提交/保存/放弃后只动这些小块 */
function renderConfigBarState() {
  const root = els.configView; if (!root) return;
  const slot = root.querySelector(".config-bar-state");
  const total = configDirtyKeys.size;
  if (slot) {
    if (state.configJustSaved) {
      slot.replaceChildren(h("span", { class: "badge badge-ok", text: "✓ 配置已保存并热重载" }));
    } else {
      slot.replaceChildren(
        total > 0
          ? h("span", { class: "badge badge-warn", text: `存在未保存的修改（${total} 项）` })
          : h("span", { class: "config-hint", text: "配置已同步" })
      );
    }
  }
  const discard = root.querySelector("[data-config-discard]");
  const save = root.querySelector("[data-config-save]");
  if (discard) discard.disabled = !total || state.configSaving;
  if (save) {
    save.disabled = !total || state.configSaving;
    save.textContent = state.configSaving ? "保存并重载中…" : state.configJustSaved ? "已保存 ✓" : "保存并重载";
  }
}

function updateConfigNavBadges() {
  const root = els.configView; if (!root) return;
  const groups = state.config?.groups || [];
  for (const g of groups) {
    const item = root.querySelector(`.config-nav-item[data-config-group="${CSS.escape(g.key)}"]`);
    if (!item) continue;
    const count = configDirtyCount(g);
    const slot = item.querySelector(".config-nav-badge");
    if (slot) {
      slot.replaceChildren(
        count > 0
          ? h("span", { class: "badge badge-warn", text: `${count} 改` })
          : h("span", { class: "config-nav-count", text: `${configItemsOf(g).length} 项` })
      );
    }
  }
}

function updateConfigChrome() {
  renderConfigBarState();
  updateConfigNavBadges();
}

function configNavItem(g) {
  const count = configDirtyCount(g);
  return h("div", {
    class: `config-nav-item${g.key === state.configActive ? " active" : ""}`,
    dataset: { configGroup: g.key },
    // 草稿跨组平铺、切组不丢弃任何东西,无需拦截确认
    onClick: () => { if (state.configActive !== g.key) { state.configActive = g.key; state.configSearch = ""; renderConfig(); } },
  }, [
    h("span", { text: g.name }),
    h("span", { class: "config-nav-badge" }, count > 0
      ? [h("span", { class: "badge badge-warn", text: `${count} 改` })]
      : [h("span", { class: "config-nav-count", text: `${configItemsOf(g).length} 项` })]),
  ]);
}

function configFieldsChildren(active) {
  const items = configItemsOf(active);
  const children = [
    h("div", { class: "config-group-head" }, [
      h("h3", { text: active.name }),
      h("span", { class: "config-hint", text: `${items.length} 项` }),
    ]),
    ...items.map(configItem),
  ];
  // 不用 `length ? null : panel`:replaceChildren 不接受 null(仅 h() 会跳过)
  if (!items.length) children.push(h("div", { class: "panel", text: "无匹配配置项" }));
  return children;
}

// 搜索输入不整树重建(会丢失焦点/打断输入法):只刷新导航列表与右栏字段区。
function onConfigSearchInput(e) {
  state.configSearch = e.target.value;
  const root = els.configView;
  const navList = root?.querySelector(".config-nav-list");
  const fields = root?.querySelector(".config-fields");
  if (!navList || !fields) { renderConfig(); return; }
  const groups = Array.isArray(state.config?.groups) ? state.config.groups : [];
  const active = groups.find(g => g.key === state.configActive);
  navList.replaceChildren(...groups.map(configNavItem));
  if (active) fields.replaceChildren(...configFieldsChildren(active));
}

function maybeLeaveConfigGroup(action) {
  if (!configDraftDirty()) { action(); return; }
  openConfirm({
    title: "放弃未保存的配置修改？",
    desc: "当前配置有未保存的修改，继续将丢失。",
    confirmText: "丢弃并继续", danger: true,
    action,
  });
}

async function saveConfigDraft() {
  const changed = [];
  for (const [key, val] of Object.entries(state.configDraft)) {
    const item = findConfigItem(key);
    if (!item) { delete state.configDraft[key]; configDirtyKeys.delete(key); continue; }
    if (JSON.stringify(val) === JSON.stringify(item.value)) { delete state.configDraft[key]; configDirtyKeys.delete(key); continue; }
    changed.push([key, val]);
  }
  if (!changed.length) { state.configDraft = {}; configDirtyKeys.clear(); renderConfig(); return; }
  state.configSaving = true; renderConfigBarState();
  try {
    const result = await apiPost("web/config/save", { changes: Object.fromEntries(changed) });
    const touched = [];
    for (const [key, value] of Object.entries(result.values || {})) {
      const item = findConfigItem(key);
      if (item) item.value = value;
      delete state.configDraft[key];
      configDirtyKeys.delete(key);
      touched.push(key);
    }
    refreshConfigRows(touched);
    if (result.reloaded) {
      state.configJustSaved = true;
      setTimeout(() => { state.configJustSaved = false; renderConfigBarState(); }, 2400);
      showToast("配置已保存，插件已热重载");
    } else showAlert(result.warning || "配置已保存，但插件热重载失败", "error");
  } catch (err) {
    showAlert(err.message || "保存配置失败", "error");
  } finally {
    state.configSaving = false;
    renderConfigBarState();
    updateConfigNavBadges();
  }
}

/* 保存后只重建被保存值影响的字段卡（服务器可能归一化了取值） */
function refreshConfigRows(keys) {
  for (const key of keys) {
    const row = els.configView?.querySelector(`[data-config-key="${CSS.escape(key)}"]`);
    const item = findConfigItem(key);
    if (!row || !item) continue;
    row.replaceChildren(...configItemChildren(item));
  }
}

function findConfigItem(key) {
  const groups = state.config?.groups || [];
  for (const g of groups) {
    const item = (g.items || []).find(i => i.key === key);
    if (item) return item;
  }
  return null;
}

/* 单条配置项的提交入口：写草稿 → 增量维护真脏集合 → 局部刷新 UI。
   fromControl=true 表示值来自控件本身（控件显示已正确，无需重建控件） */
function commitConfigValue(key, value, fromControl = true) {
  const item = findConfigItem(key);
  state.configDraft[key] = value;
  const differs = !!item && JSON.stringify(value) !== JSON.stringify(item.value);
  if (differs) configDirtyKeys.add(key);
  else configDirtyKeys.delete(key);
  updateConfigItemUI(key, !fromControl);
  updateConfigChrome();
}

function updateConfigItemUI(key, syncControl = true) {
  const row = els.configView?.querySelector(`[data-config-key="${CSS.escape(key)}"]`);
  const item = findConfigItem(key);
  if (!row || !item) return;
  const value = state.configDraft[key] !== undefined ? state.configDraft[key] : item.value;
  if (syncControl) {
    const control = row.querySelector(".config-control");
    if (control) control.replaceWith(configControl(item, value));
  }
  const differsFromDefault = item.default !== undefined
    && JSON.stringify(value) !== JSON.stringify(item.default);
  const head = row.querySelector(".config-item-head");
  const reset = head?.querySelector(".config-reset");
  if (differsFromDefault && !reset && head) {
    head.append(h("button", {
      class: "btn btn-ghost btn-sm config-reset", text: "恢复默认",
      title: item.default === null ? "清空" : "重置为此项默认值",
      onClick: () => commitConfigValue(item.key, item.default, false),
    }));
  } else if (!differsFromDefault && reset) {
    reset.remove();
  }
}

function configItem(item) {
  return h("div", { class: "config-item", dataset: { configKey: item.key } }, configItemChildren(item));
}

function configItemChildren(item) {
  const value = state.configDraft[item.key] !== undefined
    ? state.configDraft[item.key] : item.value;
  const differsFromDefault = item.default !== undefined
    && JSON.stringify(value) !== JSON.stringify(item.default);
  return [
    h("div", { class: "config-item-head" }, [
      h("span", { class: "config-label", text: item.description || item.key }),
      h("span", { class: "config-key mono", text: item.key }),
      differsFromDefault ? h("button", {
        class: "btn btn-ghost btn-sm config-reset", text: "恢复默认",
        title: item.default === null ? "清空" : "重置为此项默认值",
        onClick: () => commitConfigValue(item.key, item.default, false),
      }) : null,
    ]),
    configControl(item, value),
    item.hint ? h("div", { class: "config-hint-block", text: item.hint }) : null,
  ];
}

function configControl(item, value) {
  const wrap = h("div", { class: "config-control" });
  const commit = (v, fromControl = true) => commitConfigValue(item.key, v, fromControl);
  if (item.editable === false) {
    wrap.append(h("span", { class: "badge", text: "在「分组订阅管理」维护" }));
    return wrap;
  }
  if (item.type === "bool") {
    const input = h("input", { type: "checkbox" });
    input.checked = !!value;
    input.addEventListener("change", () => commit(input.checked));
    wrap.append(h("label", { class: "toggle" }, [input, h("span", { class: "toggle-track" })]));
    return wrap;
  }
  if (item.type === "int" || item.type === "float") {
    const input = h("input", { type: "number", step: item.type === "float" ? "any" : "1" });
    if (value !== null && value !== undefined) input.value = String(value);
    input.addEventListener("change", () => {
      if (input.value.trim() === "") return;
      const num = Number(input.value);
      if (Number.isNaN(num)) { showToast("该配置项需要数字"); return; }
      commit(num);
    });
    wrap.append(input);
    return wrap;
  }
  if (Array.isArray(item.options) && item.options.length) {
    const select = createSelect({
      value: String(value ?? ""),
      options: item.options.map(o => ({ value: o, text: o })),
    });
    select.onChange(v => commit(v));
    wrap.append(select);
    return wrap;
  }
  if (item.type === "text" || item.type === "list") {
    const area = h("textarea", { rows: item.type === "text" ? 3 : 4 });
    area.value = item.type === "list"
      ? (Array.isArray(value) ? value.join("\n") : "")
      : String(value ?? "");
    area.addEventListener("change", () => {
      commit(item.type === "list"
        ? area.value.split("\n").map(s => s.trim()).filter(Boolean)
        : area.value);
    });
    if (item.type === "list") {
      area.placeholder = "每行一项";
    }
    wrap.append(area);
    return wrap;
  }
  if (item.type === "string" && item.key.toLowerCase().includes("provider")) {
    const options = [{ value: "", text: "（留空 = 自动选择）" }];
    for (const p of state.providers || []) {
      options.push({ value: p.id, text: p.label || p.id });
    }
    if (value && !options.some(o => o.value === value)) {
      options.push({ value, text: `${value}（当前值）` });
    }
    const select = createSelect({ value: String(value ?? ""), options });
    select.onChange(v => commit(v));
    wrap.append(select);
    return wrap;
  }
  const input = h("input", { type: "text" });
  input.value = String(value ?? "");
  input.addEventListener("change", () => commit(input.value));
  wrap.append(input);
  return wrap;
}

/* ==========================================================================
   16. Cleanup Actions
   ========================================================================== */
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

/* ==========================================================================
   17. Entry — 视图持久化路由 / boot / 事件绑定
   ========================================================================== */
const VIEW_META = {
  overview: { title: "总览", desc: "运行状态、订阅摘要与系统维护" },
  groups: { title: "分组订阅", desc: "维护博主、搜索与 List 规则" },
  history: { title: "推送历史", desc: "查看送达状态并重推" },
  mirror: { title: "实例节点", desc: "测试 Nitter 实例连通性" },
  storage: { title: "存储运维", desc: "媒体缓存、已读去重与数据库整理" },
  config: { title: "插件配置", desc: "查看与修改插件设置（与 AstrBot 设置页同源，最后保存生效）" },
};

const RENDERERS = {
  overview: renderOverview,
  groups: renderGroupCards,
  history: renderHistory,
  mirror: renderMirror,
  storage: renderStorage,
  config: renderConfig,
};

function flushView(view) {
  if (!viewDirty.has(view)) return;
  const render = RENDERERS[view];
  if (!render) return;
  viewDirty.delete(view);
  render();
}

/* 顶部导航壳没有独立标题栏，页签本身就是当前视图标识；
   document.title 跟随视图，便于宿主 iframe 与浏览器标签识别。 */
function updateHeader() {
  const m = VIEW_META[state.view] || VIEW_META.overview;
  document.title = `${m.title} · Nitter 推文控制台`;
}

function switchView(v) {
  if (!v || state.view === v) return;
  hideAlert();
  state.view = v;
  els.tabs.forEach(t => t.classList.toggle("active", t.dataset.view === v));
  els.views.forEach(s => s.classList.toggle("active", s.id === `${v}View`));
  updateHeader();
  flushView(v);
  // 诊断终端只在实例诊断视图可见时轮询，切走即停
  if (v === "mirror") {
    reloadLogs({ reset: true }).catch(() => {});
    startLogPolling();
  } else {
    stopLogPolling();
  }
}

function bindEvents() {
  els.tabs.forEach(tab => tab.addEventListener("click", () => switchView(tab.dataset.view)));
  els.refreshBtn?.addEventListener("click", () => {
    const groupsDirty = state.groups.some(g => isGroupDirty(g.group_id));
    const configDirty = configDraftDirty();
    if (!groupsDirty && !configDirty) return reloadAll({ preserveDrafts: false });
    // 文案按实际脏来源拼接,避免只有其一为脏时以偏概全
    const parts = [];
    if (groupsDirty) parts.push("分组的编辑");
    if (configDirty) parts.push("配置修改");
    openConfirm({
      title: "刷新将丢弃未保存的修改？",
      desc: `当前有未保存的${parts.join("和")}，刷新后这些修改将丢失。`,
      confirmText: "丢弃并刷新", danger: true,
      action: () => reloadAll({ preserveDrafts: false }),
    });
  });
  els.themeToggleBtn?.addEventListener("click", toggleTheme);
  els.createGroupBtn?.addEventListener("click", createGroup);
  els.cmdkBtn?.addEventListener("click", () => openCmdk());
  els.cleanCacheBtn?.addEventListener("click", confirmClearCache);
  // 实例诊断页的探测按钮在 section-header 上，表单 submit 仍保留给回车提交
  els.mirrorProbeBtn?.addEventListener("click", () => probeMirror());

  els.historyRefreshBtn?.addEventListener("click", async () => {
    state.historyGroupId = els.historyGroupSelect.value;
    state.historyUsername = els.historyUsername.value.trim();
    state.historyLimit = parseInt(els.historyLimit.value, 10) || 10;
    state.historyStatus = els.historyStatusSelect ? els.historyStatusSelect.value : "";
    state.historySelection.clear();
    state.historyOffset = 0; // 重置页码
    await withAction(() => refreshHistoryData(), false, { reload: false });
  });
  els.historyPrevBtn?.addEventListener("click", () => loadHistoryPage(-1));
  els.historyNextBtn?.addEventListener("click", () => loadHistoryPage(1));
  els.historyOrphanBtn?.addEventListener("click", detectHistoryOrphans);
  els.historySelectAllBtn?.addEventListener("click", toggleHistorySelectAllPage);
  els.mirrorForm?.addEventListener("submit", probeMirror);

  els.cancelConfirmBtn?.addEventListener("click", closeConfirm);
  els.confirmActionBtn?.addEventListener("click", async () => {
    const act = state.pendingAction; closeConfirm();
    if (typeof act === "function") await act();
  });
  els.confirmDialog?.addEventListener("click", e => { if (e.target === els.confirmDialog) closeConfirm(); });

  // 抽屉：关闭按钮 / 遮罩点击
  els.sheetCloseBtn?.addEventListener("click", () => closeSheet());
  els.sheetScrim?.addEventListener("click", () => closeSheet());

  // ⌘K 面板：输入过滤 + 键盘上下选择
  els.cmdkOverlay?.addEventListener("click", e => { if (e.target === els.cmdkOverlay) closeCmdk(); });
  els.cmdkInput?.addEventListener("input", e => { cmdkIndex = 0; renderCmdk(e.target.value); });
  els.cmdkInput?.addEventListener("keydown", e => {
    const count = els.cmdkList.children.length;
    if (e.key === "ArrowDown") { e.preventDefault(); cmdkIndex = (cmdkIndex + 1) % Math.max(1, count); renderCmdk(els.cmdkInput.value); }
    else if (e.key === "ArrowUp") { e.preventDefault(); cmdkIndex = (cmdkIndex - 1 + count) % Math.max(1, count); renderCmdk(els.cmdkInput.value); }
    else if (e.key === "Enter") {
      e.preventDefault();
      const items = cmdkItems.filter(it => {
        const q = els.cmdkInput.value.trim().toLowerCase();
        return !q || it.title.toLowerCase().includes(q) || it.sub.toLowerCase().includes(q);
      });
      const picked = items[cmdkIndex];
      if (picked) { closeCmdk(); picked.run(); }
    }
  });

  // 新建分组弹窗
  els.createGroupCancelBtn?.addEventListener("click", closeCreateGroupModal);
  els.createGroupCloseBtn?.addEventListener("click", closeCreateGroupModal);
  els.createGroupSubmitBtn?.addEventListener("click", submitCreateGroup);
  els.createGroupModal?.addEventListener("click", e => { if (e.target === els.createGroupModal) closeCreateGroupModal(); });

  document.addEventListener("keydown", e => {
    // ⌘K / Ctrl+K：任意视图都可唤起快捷面板
    if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      cmdkOpen ? closeCmdk() : openCmdk();
      return;
    }
    if (e.key === "Escape") {
      if (cmdkOpen) { closeCmdk(); return; }
      if (els.createGroupModal?.classList.contains("open")) { closeCreateGroupModal(); return; }
      if (sheetOpen) { closeSheet(); return; }
      closeConfirm();
      return;
    }
    if (e.key !== "Tab") return;
    if (els.confirmDialog && !els.confirmDialog.hidden) { trapFocus(els.confirmDialog, e); return; }
    if (els.createGroupModal?.classList.contains("open")) { trapFocus(els.createGroupModal, e); return; }
    if (sheetOpen) trapFocus(els.detailSheet, e);
  });
}

function boot() {
  try {
    bridge = window.AstrBotPluginPage;
    if (!bridge) throw new Error("AstrBot 页面桥接不可用");
    initEls();
    initStickyOffsets();
    // 原型用原生 select（配自绘 SVG 箭头），不再替换成 .dd 自绘下拉
    initTheme();
    updateHeader();
    bindEvents();
    reloadAll({ preserveDrafts: false });
  } catch (err) {
    console.error("Nitter dashboard boot failed", err);
    const message = document.createElement("div");
    message.className = "boot-error";
    message.textContent = `面板启动失败：${err.message || "未知错误"}`;
    document.querySelector(".main")?.replaceChildren(message);
  }
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
