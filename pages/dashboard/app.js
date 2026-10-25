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
  pendingAction: null, lastFocusedElement: null, lastUpdated: "",
  statusNotice: null, statusNoticeClosed: false, bannerOffset: "",
};

const els = {};

/* 五个视图容器常驻 DOM；初始全脏，boot 后只冲刷激活视图，其余首次切换时渲染 */
const viewDirty = new Set(["overview", "groups", "history", "mirror", "config"]);

/* 数据通道 → 受影响视图 */
const CHANNEL_VIEWS = {
  overview: ["overview", "mirror"],
  groups: ["groups", "overview"],
  history: ["history"],
  config: ["config"],
};

function markDirtyView(view) {
  viewDirty.add(view);
  if (view === state.view) flushView(view);
}

function markData(...channels) {
  for (const ch of channels) {
    for (const v of CHANNEL_VIEWS[ch] || []) markDirtyView(v);
    if (ch === "overview") renderRailStatus();
    if (ch === "groups") syncHistoryGroupOptions();
  }
}

function initEls() {
  const ids = [
    "refreshBtn","lastUpdated","currentTabTitle","currentTabDesc","themeToggleBtn",
    "railSchedulerStatus","railScheduleStatus","railTargetStatus","noticeStack","toastContainer",
    "overviewView","groupsView","historyView","mirrorView","configView",
    "createGroupBtn","groupList","groupEditor",
    "historyGroupSelect","historyUsername","historyLimit","historyStatusSelect","historyRefreshBtn",
    "historyOrphanBtn","historyPrevBtn","historyNextBtn","historyPageLabel",
    "historyOrphanResult","historyContent","historySelectAllBtn","historyBatchBar",
    "mirrorForm","mirrorUsername","mirrorQuery","mirrorListId","mirrorLimit",
    "mirrorInstance","mirrorProbeBtn","instanceList","mirrorResult",
    "confirmDialog","confirmTitle","confirmDesc","cancelConfirmBtn","confirmActionBtn",
  ];
  ids.forEach(id => { els[id] = document.getElementById(id); });
  els.tabs = document.querySelectorAll(".tab");
  els.views = document.querySelectorAll(".view");
}

/* 吸顶坐标实测合帧：ResizeObserver/resize 触发的一帧内只读一次布局。
   ≤1000px 时侧栏折叠为吸顶整体叠在标题栏上方，吸附让位高度 = 两者之和 */
function initStickyOffsets() {
  const header = document.querySelector(".topheader");
  const sidebar = document.querySelector(".sidebar");
  if (!header) return;
  const stackedLayout = () => window.matchMedia?.("(max-width: 1000px)").matches;
  let frame = 0;
  const sync = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const headerH = Math.ceil(header.getBoundingClientRect().height);
      const stackH = stackedLayout() && sidebar ? Math.ceil(sidebar.getBoundingClientRect().height) : 0;
      document.documentElement.style.setProperty("--topheader-height", `${headerH + stackH}px`);
    });
  };
  sync();
  window.addEventListener("resize", scheduleBannerSync);
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(sync).observe(header);
    if (sidebar) new ResizeObserver(sync).observe(sidebar);
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
      onClick: () => { pick(o.value); close(); },
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
  function close() {
    list.hidden = true;
    root.classList.remove("open");
    trigger.setAttribute("aria-expanded", "false");
    document.removeEventListener("click", onDocClick, true);
    if (openDropdown === api) openDropdown = null;
  }
  trigger.addEventListener("click", () => (list.hidden ? open() : close()));
  trigger.addEventListener("keydown", e => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); open(); }
  });
  list.addEventListener("keydown", e => {
    const items = [...list.querySelectorAll(".dd-option")];
    const idx = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[Math.min(idx + 1, items.length - 1)]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[Math.max(idx - 1, 0)]?.focus(); }
    else if (e.key === "Escape") { e.preventDefault(); close(); trigger.focus(); }
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

function upgradeSelect(el) {
  if (!el || el.tagName !== "SELECT") return el;
  const value = el.value;
  const options = [...el.options].map(o => ({ value: o.value, text: o.textContent }));
  const custom = createSelect({ id: el.id, value, options });
  el.replaceWith(custom);
  return custom;
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
    showAlert(successText || res?.message || "操作完成");
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
    state.lastUpdated = new Date().toLocaleTimeString();
    if (els.lastUpdated) els.lastUpdated.textContent = state.lastUpdated;
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
    renderGroupList();
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

function renderGroupList() {
  if (!els.groupList) return;
  if (!state.groups.length) {
    els.groupList.replaceChildren(h("div", { class: "panel empty-note", text: "暂无分组" }));
    return;
  }
  els.groupList.replaceChildren(...state.groups.map(g => {
    const active = g.group_id === state.selectedGroupId;
    const dirty = isGroupDirty(g.group_id);
    const icon = g.group_type === "tag" ? "hash" : g.group_type === "list" ? "rss" : "user";
    const label = g.group_type === "tag" ? "搜索" : g.group_type === "list" ? "List" : "博主";
    const health = groupHealthInfo(g);
    return h("div", {
      class: `group-item ${active ? "active" : ""}`,
      onClick: () => selectGroup(g.group_id),
    }, [
      h("div", { class: "group-item-row" }, [
        h("span", { class: "group-item-name" }, [
          iconEl(icon, 16),
          (state.groupDrafts[g.group_id]?.name) || g.name,
        ]),
        dirty ? h("span", { class: "badge badge-warn", text: "未保存" }) : null,
      ]),
      h("div", { class: "group-item-meta" }, [
        h("span", { class: "badge badge-blue", text: label }),
        h("span", { class: "mono", text: g.group_id }),
        !g.enabled ? h("span", { class: "badge", text: "停用" }) : null,
        h("span", { class: `health-dot ${health.count ? "warn" : "ok"}`, title: health.title }),
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
function renderGroupEditor() {
  if (!els.groupEditor) return;
  const g = state.groups.find(x => x.group_id === state.selectedGroupId);
  if (!g) { els.groupEditor.replaceChildren(h("div", { class: "panel empty-note", text: "请选择一个分组" })); return; }
  const d = state.groupDrafts[g.group_id] || snapshotGroup(g);

  // Head
  const head = h("div", { class: "panel-head" }, [
    h("div", { class: "row" }, [
      h("h2", { text: d.name || g.name }),
      h("span", { class: `badge ${d.enabled ? "badge-ok" : "badge-warn"}`, text: d.enabled ? "启用" : "停用" }),
      h("span", { class: "mono hint", text: g.group_id }),
    ]),
    h("div", { class: "row" }, [
      g.group_id !== "default" ? h("button", { class: "btn btn-sm btn-danger", html: svgIcon("trash", 14), text: "删除", onClick: () => confirmDeleteGroup(g.group_id) }) : null,
    ]),
  ]);

  // Base config: 名称通栏 + 开关 2×2 + 每日定时通栏,同一个 grid 保证对齐
  const base = h("div", { class: "editor-grid" }, [
    h("label", { class: "field editor-grid-full" }, [
      h("span", { text: "分组名称" }),
      h("input", { type: "text", value: d.name,
        onInput: e => updateDraft(g.group_id, "name", e.target.value.trim()),
        onChange: () => saveGroup(g.group_id, "分组名称已保存"),
      }),
    ]),
    toggleRow(d.enabled, "启用此分组", v => commitGroupField(g.group_id, "enabled", v)),
    toggleRow(d.filter_reposts_enabled, "过滤转发（需同时开启全局转发过滤总开关）", v => commitGroupField(g.group_id, "filter_reposts_enabled", v)),
    toggleRow(d.filter_plain_text_enabled, "过滤纯文本（仅有媒体推文才推送）", v => commitGroupField(g.group_id, "filter_plain_text_enabled", v)),
    toggleRow(d.interval_check_enabled, "开启定时循环间隔检查", v => commitGroupField(g.group_id, "interval_check_enabled", v)),
    h("span", { class: "hint-line editor-grid-full", text: `间隔检查使用全局检查间隔：${g.check_interval_minutes ?? "—"} 分钟` }),
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
      }, onChange: () => saveGroup(g.group_id, "定时设置已保存") }),
      h("span", { id: "dailyTimesHint", class: "field-error", style: { display: "none" } }),
    ]),
  ]);

  // Subscription entities section
  const entities = renderEntities(g, d);
  // Push targets section（data-editor-section 供 rerenderTargetsSection 局部重建）
  const targets = h("div", { "data-editor-section": "targets" }, renderTargets(g, d));

  els.groupEditor.replaceChildren(h("div", { class: "panel" }, [
    head, base, entities, targets,
  ]));
}

/* targets 区块局部重建：probe/黑名单等只影响该区块的操作不必整棵重建编辑器 */
function rerenderTargetsSection(gid) {
  if (gid !== state.selectedGroupId) return;   // 请求在途时用户已切换分组，跳过过期重渲
  const g = state.groups.find(x => x.group_id === gid);
  const d = g ? (state.groupDrafts[g.group_id] || snapshotGroup(g)) : null;
  const section = els.groupEditor?.querySelector('[data-editor-section="targets"]');
  if (!g || !d || !section) { renderGroupEditor(); return; }
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
    h("div", { class: "input-action-row entity-input-row" }, [
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
    h("div", { class: "input-action-row bulk-actions" }, [
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
    h("div", { class: "input-action-row target-input-row" }, [
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
    h("div", { class: "input-action-row blacklist-input-row" }, [
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
  const nameInput = h("input", { type: "text", value: "新订阅分组", class: "confirm-input" });
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
  openConfirm({
    title: "新建订阅分组",
    desc: h("div", { class: "vstack-sm" }, [h("div", { class: "hint", text: "分组名称：" }), nameInput, h("div", { class: "hint", text: "选择类型：" }), radioBox]),
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

/* ==========================================================================
   12. Overview
   ========================================================================== */
function renderOverview() {
  const root = els.overviewView; if (!root) return;
  const p = state.overview;
  if (!p) { root.replaceChildren(h("div", { class: "panel empty-note", text: "正在加载..." })); return; }
  const c = p.counts || {}; const s = p.scheduler || {};
  const cfg = p.config_summary || {}; const inst = p.instances || [];
  const att = p.attention_items || [];

  // Metric cards with icons(除调度器外点击跳转分组管理)
  const goGroups = () => document.querySelector('[data-view="groups"]')?.click();
  const metrics = h("div", { class: "metrics-grid" }, [
    metric("home", "调度器", s.running ? "运行中" : "已停用"),
    metric("list", "启用分组", `${c.enabled_groups || 0} / ${c.groups || 0}`, goGroups),
    metric("user", "博主订阅", c.watch_users || 0, goGroups),
    metric("hash", "搜索订阅", c.watch_queries || 0, goGroups),
    metric("rss", "List 订阅", c.watch_lists || 0, goGroups),
    metric("send", "推送目标", c.push_targets || 0, goGroups),
  ]);

  // Attention items
  const attPanel = att.length ? h("div", { class: "panel" }, [
    h("div", { class: "panel-head" }, [
      h("h3", { text: "需要关注" }),
      h("span", { class: "badge badge-warn", text: `${att.length} 项` }),
    ]),
    ...att.map(item => h("div", {
      class: `alert-item ${item.level === "error" ? "danger" : item.level === "warning" || item.level === "warn" ? "warn" : "info"}`,
    }, [
      h("span", {}, [
        h("strong", { text: `${item.title || ""}: ` }),
        item.detail || "",
      ]),
      item.group_id ? h("button", {
        class: "btn btn-ghost btn-sm",
        html: svgIcon("external", 14),
        title: "前往该分组",
        onClick: () => goGroupEditor(item.group_id),
      }) : null,
    ])),
  ]) : null;

  // Instance & config summary
  const configPanel = h("div", { class: "panel" }, [
    h("div", { class: "panel-head" }, [h("h3", { text: "实例与配置" })]),
    h("div", { class: "row row-wrap" }, [
      h("div", { class: "field field-flex" }, [
        h("span", { text: "已配置 Nitter 实例" }),
        inst.length
          ? h("div", { class: "chip-list" }, inst.map(u => h("span", { class: "chip mono chip-action", text: u, onClick: () => { if (els.mirrorInstance) els.mirrorInstance.value = u; document.querySelector('[data-view="mirror"]')?.click(); } })))
          : h("span", { class: "badge badge-warn", text: "未配置任何实例" }),
      ]),
      h("div", { class: "field field-flex" }, [
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

  // Danger zone（收敛视觉权重：细红边面板 + 常规卡面；展示缓存构成辅助决策）
  const mt = (state.overview && state.overview.maintenance) || {};
  const cacheInfo = mt.cache;
  const parts = [];
  if (cacheInfo) {
    if (cacheInfo.images) parts.push(`图片 ${cacheInfo.images}`);
    if (cacheInfo.videos) parts.push(`视频 ${cacheInfo.videos}`);
    if (cacheInfo.other) parts.push(`其他 ${cacheInfo.other}`);
  }
  const breakdown = parts.join(" · ");
  const cacheText = cacheInfo
    ? (cacheInfo.files
        ? `当前缓存：${cacheInfo.files} 个文件 · ${formatBytes(cacheInfo.bytes)}${breakdown ? `（${breakdown}）` : ""}`
        : "当前缓存：空")
    : "当前缓存：未知";
  const seenInfo = mt.seen || null;
  const seenByGroup = (seenInfo && seenInfo.by_group) || {};
  const dz = h("div", { class: "panel danger-zone" }, [
    h("div", { class: "panel-head" }, [
      h("h3", { text: "维护与缓存清理" }),
      h("span", { class: "badge badge-danger", text: "不可逆" }),
    ]),
    h("div", { class: "danger-grid" }, [
      h("div", { class: "danger-item" }, [
        h("h4", { text: "清理媒体缓存" }),
        h("p", { text: "删除临时下载的图片与视频附件" }),
        h("p", { text: cacheText }),
        h("div", { class: "actions" }, [
          h("button", { class: "btn btn-danger btn-sm", text: "清理", onClick: confirmClearCache }),
        ]),
      ]),
      h("div", { class: "danger-item" }, [
        h("h4", { text: "重置推送记录 (Seen)" }),
        h("p", { text: "可能导致历史推文再次推送" }),
        h("p", { text: seenInfo ? `当前共 ${seenInfo.total} 条记录` : "当前记录数：未知" }),
        h("div", { class: "actions" }, [
          createSelect({
            id: "seenSelect",
            options: [
              { value: "", text: "全部分组" },
              ...state.groups.map(g => ({
                value: g.group_id,
                text: `${g.name}（${seenByGroup[g.group_id] ?? 0} 条）`,
              })),
            ],
          }),
          h("button", { class: "btn btn-danger btn-sm", text: "重置", onClick: confirmClearSeen }),
        ]),
      ]),
    ]),
  ]);

  // 诊断优先（Monitor surface）：有问题先看问题，指标其次
  root.replaceChildren(...(attPanel ? [attPanel] : []), metrics, configPanel, dz);
}

function goGroupEditor(gid) {
  state.selectedGroupId = gid;
  document.querySelector('[data-view="groups"]')?.click();
}

function metric(icon, label, value, onClick) {
  return h("div", {
    class: `metric${onClick ? " clickable" : ""}`,
    ...(onClick ? { role: "button", tabindex: "0", onClick, onkeydown: e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } } } : {}),
  }, [
    h("div", { class: "metric-icon", html: svgIcon(icon, 16) }),
    h("div", { class: "metric-text" }, [
      h("span", { class: "metric-label", text: label }),
      h("span", { class: "metric-value", text: String(value) }),
    ]),
  ]);
}
function badge(text) { return h("span", { class: "badge", text }); }

/* ==========================================================================
   13. History — Tweet-style Feed
   ========================================================================== */
function syncHistoryGroupOptions() {
  if (els.historyGroupSelect?.setOptions) {
    els.historyGroupSelect.setOptions([
      { value: "", text: "所有分组" },
      ...state.groups.map(g => ({ value: g.group_id, text: g.name })),
    ]);
  }
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
  if (els.historyPrevBtn && data) els.historyPrevBtn.disabled = !data.has_prev;
  if (els.historyNextBtn && data) els.historyNextBtn.disabled = !data.has_next;

  const content = els.historyContent;
  if (!recs.length) {
    content.replaceChildren(h("div", { class: "panel empty-note", text: "暂无推送历史记录" }));
    renderHistoryBatchBar();
    return;
  }

  content.replaceChildren(...recs.map(r => {
    const st = r.delivery_status;
    const stBadge = h("span", { class: `badge ${st === "success" ? "badge-ok" : st === "partial_failed" ? "badge-warn" : "badge-danger"}`, text: st === "success" ? "已送达" : st === "partial_failed" ? "部分失败" : "发送失败" });
    const hasMedia = !!r.has_media;

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
      class: "tweet-card",
      title: "点击切换选中",
      dataset: { recordId: String(r.id) },
      onClick: e => {
        if (e.detail > 1) return; // 双击/多击序列只认第一击
        if (window.getSelection()?.type === "Range") return; // 正在划选正文，不当作点选
        toggleHistoryRecord(r.id, checkbox);
      },
    }, [
      h("div", { class: "tweet-select" }, [checkbox]),
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
        // Tweet text（两行截断，title 保留全文供悬停查看）
        h("div", { class: "tweet-text", title: r.text_preview || null }, [
          r.original_link ? h("a", { href: r.original_link, target: "_blank", rel: "noopener noreferrer", class: "mono", text: r.status_id, style: { marginRight: "6px", fontWeight: "600" }, onClick: e => e.stopPropagation() }) : null,
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
              onClick: e => {
                e.stopPropagation(); // 卡片可点后，按钮点击不切换选中
                replayHistory(r.id, r.replay_target_options);
              },
            }),
          ]),
        ]),
      ]),
    ]);
  }));

  renderHistoryBatchBar();
}

// 更新一条记录的选中态并同步勾选框视觉；不整卡重渲染，避免键盘焦点丢失。
function setHistoryRecordSelected(id, selected, checkbox) {
  if (selected) state.historySelection.add(id);
  else state.historySelection.delete(id);
  if (checkbox) checkbox.checked = selected;
  renderHistoryBatchBar();
}

function toggleHistoryRecord(id, checkbox) {
  setHistoryRecordSelected(id, !state.historySelection.has(id), checkbox);
}

/* 把 DOM 里每张卡片的勾选框同步回集合状态；全选/清除走原位同步，不重建卡片 */
function syncHistoryCheckboxes() {
  const cards = els.historyContent?.querySelectorAll(".tweet-card") || [];
  for (const card of cards) {
    const raw = card.dataset.recordId ?? "";
    const id = /^\d+$/.test(raw) ? Number(raw) : raw;
    const box = card.querySelector(".tweet-select input");
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
  await withAction(() => refreshHistoryData(), "翻页完成", { reload: false });
}

/* 孤儿列表的纯查询渲染：检测按钮经 detectHistoryOrphans 走 busy 仪式，
   删除残留后的 rerender 直接调用本函数（外层动作未结束时 withAction 会空转） */
async function renderHistoryOrphans() {
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
   14. Mirror Probe（能力矩阵 + 相对耗时条）
   ========================================================================== */
function renderMirrorBase() {
  if (!els.instanceList) return;
  const inst = (state.overview && state.overview.instances) || [];
  if (!inst.length) {
    els.instanceList.replaceChildren(h("span", { class: "badge badge-warn", text: "无已配置实例" }));
    return;
  }
  els.instanceList.replaceChildren(...inst.map(u => h("button", {
    type: "button",
    class: "chip chip-action mono", text: u,
    onClick: () => { if (els.mirrorInstance) els.mirrorInstance.value = u; },
  })));
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
  els.mirrorResult.replaceChildren(h("div", { class: "panel empty-note", text: "探测中..." }));
  try {
    const res = await apiPost("web/mirror/probe", payload);
    const results = res.results || [];
    if (!results.length) {
      els.mirrorResult.replaceChildren(h("div", { class: "panel empty-note", text: "未返回结果" }));
      return;
    }
    els.mirrorResult.replaceChildren(...results.map(r => {
      const checks = r.checks || {};
      // 耗时条按本实例内各成功能力的相对占比构建，静态写入（无过渡、无循环动画）
      const durations = Object.values(checks).filter(c => c && c.success).map(c => c.duration_ms || 0);
      const maxMs = Math.max(1, ...durations);
      return h("div", { class: "probe-result" }, [
        h("div", { class: "probe-instance-head" }, [
          h("span", { class: "mono mono-strong", text: r.instance }),
          h("span", { class: `badge ${r.success ? "badge-ok" : "badge-danger"}`, text: r.success ? "全部可用" : "有异常" }),
        ]),
        h("div", { class: "probe-checks" }, [
          checks.rss_user ? probeCheck("RSS", checks.rss_user, maxMs) : null,
          checks.html_user ? probeCheck("HTML", checks.html_user, maxMs) : null,
          checks.search ? probeCheck("搜索", checks.search, maxMs) : null,
          checks.list ? probeCheck("List", checks.list, maxMs) : null,
        ]),
      ]);
    }));
  } catch (err) {
    els.mirrorResult.replaceChildren(h("div", { class: "alert error", text: `探测失败: ${err.message}` }));
  } finally {
    state.actionBusy = false; setBusy(false);
  }
}

function probeCheck(label, item, maxMs = 1) {
  if (!item) return null;
  const ok = item.success;
  const pct = ok ? Math.max(8, Math.round(((item.duration_ms || 0) / maxMs) * 100)) : 0;
  return h("div", { class: `probe-check ${ok ? "ok" : "fail"}` }, [
    iconEl(ok ? "check" : "alert", 14),
    h("span", { text: label }),
    ok ? h("span", { text: `${item.tweet_count || 0}条 ${Math.round(item.duration_ms || 0)}ms` }) : h("span", { class: "probe-error", text: item.error || "失败" }),
    ok ? h("span", { class: "probe-meter", "aria-hidden": "true" }, [
      h("span", { class: "probe-meter-fill", style: { width: `${pct}%` } }),
    ]) : null,
  ]);
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
    slot.replaceChildren(
      total > 0
        ? h("span", { class: "badge badge-warn", text: `存在未保存的修改（${total} 项）` })
        : h("span", { class: "config-hint", text: "配置已同步" })
    );
  }
  const discard = root.querySelector("[data-config-discard]");
  const save = root.querySelector("[data-config-save]");
  if (discard) discard.disabled = !total || state.configSaving;
  if (save) {
    save.disabled = !total || state.configSaving;
    save.textContent = state.configSaving ? "保存并重载中…" : "保存并重载";
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
    if (result.reloaded) showToast("配置已保存，插件已热重载");
    else showAlert(result.warning || "配置已保存，但插件热重载失败", "error");
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
  overview: { title: "控制台总览", desc: "运行状态、订阅摘要与系统维护" },
  groups: { title: "分组订阅管理", desc: "维护博主、搜索与 List 规则" },
  history: { title: "推送历史", desc: "查看送达状态并重推" },
  mirror: { title: "实例能力诊断", desc: "测试 Nitter 实例连通性" },
  config: { title: "插件配置", desc: "查看与修改插件设置（与 AstrBot 设置页同源，最后保存生效）" },
};

const RENDERERS = {
  overview: renderOverview,
  groups: () => { renderGroupList(); renderGroupEditor(); },
  history: renderHistory,
  mirror: renderMirrorBase,
  config: renderConfig,
};

function flushView(view) {
  if (!viewDirty.has(view)) return;
  const render = RENDERERS[view];
  if (!render) return;
  viewDirty.delete(view);
  render();
}

function updateHeader() {
  const m = VIEW_META[state.view] || VIEW_META.overview;
  if (els.currentTabTitle) els.currentTabTitle.textContent = m.title;
  if (els.currentTabDesc) els.currentTabDesc.textContent = m.desc;
}

function switchView(v) {
  if (!v || state.view === v) return;
  hideAlert();
  state.view = v;
  els.tabs.forEach(t => t.classList.toggle("active", t.dataset.view === v));
  els.views.forEach(s => s.classList.toggle("active", s.id === `${v}View`));
  updateHeader();
  flushView(v);
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

  els.historyRefreshBtn?.addEventListener("click", async () => {
    state.historyGroupId = els.historyGroupSelect.value;
    state.historyUsername = els.historyUsername.value.trim();
    state.historyLimit = parseInt(els.historyLimit.value, 10) || 10;
    state.historyStatus = els.historyStatusSelect ? els.historyStatusSelect.value : "";
    state.historySelection.clear();
    state.historyOffset = 0; // 重置页码
    await withAction(() => refreshHistoryData(), "筛选完成", { reload: false });
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
    initStickyOffsets();
    els.historyGroupSelect = upgradeSelect(els.historyGroupSelect);
    els.historyStatusSelect = upgradeSelect(els.historyStatusSelect);
    initTheme();
    updateHeader();
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
