/* Dashboard 脚本入口分片。原为单文件 app.js，现按分节拆为经典 script 多文件，
   加载顺序（必须保持）：core -> ui -> data -> groups -> views -> config -> boot。
   顶层 let/const/function 在 classic script 间共享全局词法环境，
   每个分片各自 'use strict'；boot 必须最后加载（RENDERERS 引用各视图渲染函数）。 */

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
  configDraft: {}, configSearch: "", configSearchPinned: false, configActive: "",
  configSaving: false, providers: [],
  targetBlacklists: [], targetBlacklistTarget: "",
  history: null, selectedGroupId: "",
  // 总览「最新推送记录」独立取数：不受历史页筛选与分页影响
  recentPushes: [],
  historyGroupId: "", historyUsername: "", historyLimit: 20,
  historyStatus: "", historySelection: new Set(),
  historyOffset: 0,
  pendingAction: null, lastFocusedElement: null,
  statusNotice: null, statusNoticeClosed: false,
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
  // 总览「最新推送记录」独立取数：历史页翻页/筛选不波及总览，反之亦然
  recent: ["overview"],
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
    "railSchedulerStatus","noticeStack",
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
  window.addEventListener("resize", sync);
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
   5. Feedback（通知栈 / 时间与体积格式化）
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
    return;
  }
  if (state.statusNoticeClosed) return;
  state.statusNotice = pushNotice("status", text, 0);
}

/* 通知栈是纯浮层：高度不参与文档流，不再做任何布局同步（历史方案曾按栈实测
   高度写 --banner-offset 避让吸顶栏，结果是每弹一条提示整页下移再弹回）。
   结果提示出现时，直接把进行中提示原地改写成结果，避免“移除 + 新增”两次跳动 */
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

