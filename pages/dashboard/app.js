const bridge = window.AstrBotPluginPage;

const state = {
  view: "overview",
  loading: false,
  actionBusy: false,
  overview: null,
  groups: [],
  groupDrafts: {},
  targetProbeResults: {},

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
  inertNodes: [],
  lastUpdated: "",
};

const els = {
  tabs: document.querySelectorAll(".tab"),
  views: document.querySelectorAll(".view"),
  refreshBtn: document.getElementById("refreshBtn"),
  lastUpdated: document.getElementById("lastUpdated"),
  currentTabTitle: document.getElementById("currentTabTitle"),
  currentTabDesc: document.getElementById("currentTabDesc"),
  themeToggleBtn: document.getElementById("themeToggleBtn"),
  railSchedulerStatus: document.getElementById("railSchedulerStatus"),
  railScheduleStatus: document.getElementById("railScheduleStatus"),
  railTargetStatus: document.getElementById("railTargetStatus"),
  alert: document.getElementById("alert"),
  toastContainer: document.getElementById("toastContainer"),
  overviewView: document.getElementById("overviewView"),
  createGroupBtn: document.getElementById("createGroupBtn"),
  groupList: document.getElementById("groupList"),
  groupEditor: document.getElementById("groupEditor"),

  historyGroupSelect: document.getElementById("historyGroupSelect"),
  historyUsername: document.getElementById("historyUsername"),
  historyLimit: document.getElementById("historyLimit"),
  historyRefreshBtn: document.getElementById("historyRefreshBtn"),
  historyOrphanBtn: document.getElementById("historyOrphanBtn"),
  historyPrevBtn: document.getElementById("historyPrevBtn"),
  historyNextBtn: document.getElementById("historyNextBtn"),
  historyPageLabel: document.getElementById("historyPageLabel"),
  historyOrphanResult: document.getElementById("historyOrphanResult"),
  historyContent: document.getElementById("historyContent"),
  mirrorForm: document.getElementById("mirrorForm"),
  mirrorMode: document.getElementById("mirrorMode"),
  mirrorUsername: document.getElementById("mirrorUsername"),
  mirrorQueryLabel: document.getElementById("mirrorQueryLabel"),
  mirrorLimit: document.getElementById("mirrorLimit"),
  mirrorInstance: document.getElementById("mirrorInstance"),
  mirrorProbeBtn: document.getElementById("mirrorProbeBtn"),
  instanceList: document.getElementById("instanceList"),
  mirrorInstanceListTitle: document.getElementById("mirrorInstanceListTitle"),
  mirrorInstanceListHint: document.getElementById("mirrorInstanceListHint"),
  mirrorResult: document.getElementById("mirrorResult"),
  clearCacheBtn: document.getElementById("clearCacheBtn"),
  clearSeenBtn: document.getElementById("clearSeenBtn"),
  seenGroupSelect: document.getElementById("seenGroupSelect"),
  cacheResult: document.getElementById("cacheResult"),
  seenResult: document.getElementById("seenResult"),
  confirmDialog: document.getElementById("confirmDialog"),
  confirmKicker: document.getElementById("confirmKicker"),
  confirmTitle: document.getElementById("confirmTitle"),
  confirmDesc: document.getElementById("confirmDesc"),
  cancelConfirmBtn: document.getElementById("cancelConfirmBtn"),
  confirmActionBtn: document.getElementById("confirmActionBtn"),
  cancelConfirmBtnIcon: document.getElementById("cancelConfirmBtnIcon"),
};

const viewMeta = {
  overview: {
    title: "Nitter 推文控制台总览",
    desc: "聚合查看博主订阅分组、推送目标状态以及 Nitter 节点连通性。",
  },
  groups: {
    title: "订阅分组与博主管理",
    desc: "维护订阅（关注账号或搜索）、推送目标与分组级检查策略。",
  },

  history: {
    title: "最近推送历史",
    desc: "查看成功送达记录，按分组和博主筛选，并选择当前推送目标重新推送。",
  },
  mirror: {
    title: "Nitter 镜像连通诊断",
    desc: "按模式测试 RSS / HTML 用户页 / 搜索；实例从配置同步（去重），不写推送记录。",
  },
  cleanup: {
    title: "系统维护清理",
    desc: "清理普通媒体缓存或推送记录，危险操作会二次确认。",
  },
};

const SVG_NS = "http://www.w3.org/2000/svg";
const icons = {
  refresh: [
    "M21 12a9 9 0 0 1-15.6 6.1",
    "M3 12a9 9 0 0 1 15.6-6.1",
    "M18 3v4h-4",
    "M6 21v-4h4",
  ],
  plus: ["M12 5v14", "M5 12h14"],
  trash: [
    "M3 6h18",
    "M8 6V4h8v2",
    "m19 6-1 14H6L5 6",
    "M10 11v6",
    "M14 11v6",
  ],
  send: ["m22 2-7 20-4-9-9-4Z", "M22 2 11 13"],
  probe: [
    "M10 13a5 5 0 0 0 7.1 0l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1",
    "M14 11a5 5 0 0 0-7.1 0l-2 2a5 5 0 0 0 7.1 7.1l1.1-1.1",
  ],
  erase: [
    "m7 21-4-4 10-10 4 4L7 21Z",
    "m14 6 4-4 4 4-4 4",
    "M16 21h6",
  ],
  play: ["M8 5v14l11-7Z"],
};

function appendChildren(node, children) {
  const items = Array.isArray(children) ? children : [children];
  items.forEach((child) => {
    if (Array.isArray(child)) {
      appendChildren(node, child);
      return;
    }
    if (child == null || child === false) {
      return;
    }
    if (child instanceof Node) {
      node.appendChild(child);
      return;
    }
    node.append(String(child));
  });
  return node;
}

function fragment(children = []) {
  const node = document.createDocumentFragment();
  return appendChildren(node, children);
}

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) {
    node.className = options.className;
  }
  if (options.text != null) {
    node.textContent = String(options.text);
  }
  if (options.attrs) {
    Object.entries(options.attrs).forEach(([name, value]) => {
      if (value == null || value === false) {
        return;
      }
      node.setAttribute(name, value === true ? "" : String(value));
    });
  }
  if (options.dataset) {
    Object.entries(options.dataset).forEach(([name, value]) => {
      if (value != null) {
        node.dataset[name] = String(value);
      }
    });
  }
  if (options.disabled) {
    node.disabled = true;
  }
  return appendChildren(node, children);
}

function iconSpan(name) {
  return el("span", { className: "icon", dataset: { icon: name } });
}

function createIcon(name) {
  const paths = icons[name];
  if (!paths) {
    return null;
  }
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  paths.forEach((pathData) => {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", pathData);
    svg.appendChild(path);
  });
  return svg;
}

function mountIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    node.replaceChildren();
    const icon = createIcon(node.dataset.icon);
    if (icon) {
      node.appendChild(icon);
    }
  });
}

function apiResult(result) {
  if (!result) return {};
  if (result.success === false) {
    throw new Error(result.error || "请求失败");
  }
  return result;
}

async function apiGet(endpoint, params) {
  const entries = Object.entries(params || {}).filter(([, value]) => value != null && value !== "");
  const query = Object.fromEntries(entries);
  return apiResult(await bridge.apiGet(endpoint, entries.length ? query : undefined));
}

async function apiPost(endpoint, body) {
  return apiResult(await bridge.apiPost(endpoint, body || {}));
}

function showAlert(message, type = "success") {
  els.alert.textContent = message;
  els.alert.className = `alert ${type}`;
  els.alert.hidden = false;
}

function hideAlert() {
  els.alert.hidden = true;
  els.alert.textContent = "";
}

function showToast(message) {
  if (!els.toastContainer || !message) {
    return;
  }
  const toast = el("div", { className: "toast-message", text: message });
  els.toastContainer.appendChild(toast);
  window.requestAnimationFrame(() => toast.classList.add("show"));
  window.setTimeout(() => {
    toast.classList.remove("show");
    toast.classList.add("hide");
    window.setTimeout(() => toast.remove(), 320);
  }, 1800);
}

async function copyText(text) {
  const value = String(text || "").trim();
  if (!value) {
    return false;
  }
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch (error) {
      // Embedded WebViews may expose clipboard but reject writes.
    }
  }
  const input = el("textarea", {
    attrs: { readonly: true, "aria-hidden": "true", tabindex: "-1" },
    text: value,
  });
  input.style.position = "fixed";
  input.style.left = "-9999px";
  input.style.pointerEvents = "none";
  document.body.appendChild(input);
  input.select();
  try {
    return document.execCommand("copy");
  } catch (error) {
    return false;
  } finally {
    input.remove();
  }
}

function setStatusBadge(node, text, status = "") {
  if (!node) return;
  node.className = `status-badge ${status}`.trim();
  node.replaceChildren(el("span", { className: "dot" }), text);
}

function updateViewHeader() {
  const meta = viewMeta[state.view] || viewMeta.overview;
  if (els.currentTabTitle) {
    els.currentTabTitle.textContent = meta.title;
  }
  if (els.currentTabDesc) {
    els.currentTabDesc.textContent = meta.desc;
  }
}

function renderRailStatus() {
  const payload = state.overview || {};
  const scheduler = payload.scheduler || {};
  const counts = payload.counts || {};
  setStatusBadge(
    els.railSchedulerStatus,
    scheduler.running ? "运行中" : "未运行",
    scheduler.running ? "status-ok" : "status-danger",
  );
  setStatusBadge(
    els.railScheduleStatus,
    scheduler.schedule_enabled ? "已开启" : "已关闭",
    scheduler.schedule_enabled ? "status-ok" : "status-warn",
  );

  const invalidTargets = Number(counts.invalid_push_targets || 0);
  setStatusBadge(
    els.railTargetStatus,
    `${formatNumber(invalidTargets)} 条异常`,
    invalidTargets > 0 ? "status-danger" : "status-ok",
  );
}

function safeStorageGet(key) {
  try {
    return window.localStorage?.getItem(key) || "";
  } catch (error) {
    return "";
  }
}

function safeStorageSet(key, value) {
  try {
    window.localStorage?.setItem(key, value);
  } catch (error) {
    // Storage can be blocked in embedded WebViews; theme still works for this session.
  }
}

function initTheme() {
  if (!els.themeToggleBtn) return;
  const savedTheme = safeStorageGet("nitter-dashboard-theme");
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)")?.matches;
  const theme = savedTheme || (prefersDark ? "dark" : "light");
  document.body.classList.toggle("dark-theme", theme === "dark");
  document.body.classList.toggle("light-theme", theme !== "dark");
  els.themeToggleBtn.setAttribute(
    "aria-pressed",
    String(document.body.classList.contains("dark-theme")),
  );
}

function toggleTheme() {
  const dark = !document.body.classList.contains("dark-theme");
  document.body.classList.toggle("dark-theme", dark);
  document.body.classList.toggle("light-theme", !dark);
  safeStorageSet("nitter-dashboard-theme", dark ? "dark" : "light");
  if (els.themeToggleBtn) {
    els.themeToggleBtn.setAttribute("aria-pressed", String(dark));
  }
}

function setBusy(isBusy) {
  state.loading = isBusy;
  const noGroups = !state.groups.length;
  const groupDependentButtons = [
    els.historyRefreshBtn,
    els.historyPrevBtn,
    els.historyNextBtn,
  ];
  [
    els.refreshBtn,
    els.createGroupBtn,
    els.historyRefreshBtn,
    els.historyOrphanBtn,
    els.historyPrevBtn,
    els.historyNextBtn,
    els.mirrorProbeBtn,
    els.clearCacheBtn,
    els.clearSeenBtn,
  ].forEach((button) => {
    if (button) {
      button.disabled =
        isBusy ||
        state.actionBusy ||
        (noGroups && groupDependentButtons.includes(button));
    }
  });
}

function formatBool(value) {
  return value ? "已开启" : "已关闭";
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

function formatTime(value) {
  if (!value) return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  const date = new Date(number * 1000);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function safeUrl(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  try {
    const url = new URL(text);
    if (url.protocol === "http:" || url.protocol === "https:") {
      return url.href;
    }
  } catch (error) {
    return "";
  }
  return "";
}

function externalLink(url, text) {
  const href = safeUrl(url);
  if (!href) {
    return el("span", { text: text || url || "-" });
  }
  return el("a", {
    attrs: {
      href,
      target: "_blank",
      rel: "noopener noreferrer",
      title: "点击复制原推文链接",
    },
    dataset: { copyLink: href },
    text: text || href,
  });
}

function shortUmoLabel(umo) {
  const value = String(umo || "").trim();
  if (!value) return "-";
  const [platform, messageType, sessionId] = value.split(":");
  if (!platform || !messageType || !sessionId) {
    return value;
  }
  const typeLabel = messageType.replace("Message", "");
  return `${platform}:${typeLabel}`;
}

function historyTargetChips(row) {
  const targets = Array.isArray(row.target_umos)
    ? row.target_umos.filter(Boolean)
    : [row.target_umo].filter(Boolean);
  if (!targets.length) {
    return el("span", { className: "muted", text: "-" });
  }
  return el(
    "div",
    { className: "history-targets" },
    targets.map((target) =>
      el("span", {
        className: "chip mono history-target-chip",
        attrs: { title: target },
        text: shortUmoLabel(target),
      }),
    ),
  );
}

function historyDeliveryStatus(row) {
  if (row.delivery_status === "partial_failed") {
    const error = row.delivery_error || "媒体附件发送失败";
    return el("span", {
      className: "badge warning",
      attrs: { title: error },
      text: "媒体失败",
    });
  }
  return el("span", { className: "badge ok", text: "已送达" });
}

function formatWatchQueryLabel(item) {
  if (item == null || item === "") return "";
  if (typeof item === "string") return item;
  if (typeof item === "object") {
    const query = String(item.query || item.q || "").trim();
    const type = String(item.type || item.kind || "").trim();
    if (query && type) return `${query} (${type})`;
    if (query) return query;
    return "";
  }
  return String(item);
}

function normalizeWatchQueryItem(item) {
  if (item == null || item === "") return null;
  if (typeof item === "string") {
    const query = item.trim();
    if (!query || query.toLowerCase() === "[object object]") return null;
    return {
      query,
      type: query.startsWith("#") ? "tag" : "phrase",
    };
  }
  if (typeof item === "object") {
    const query = String(item.query || item.q || "").trim();
    if (!query || query.toLowerCase() === "[object object]") return null;
    const typeRaw = String(item.type || item.kind || "").trim().toLowerCase();
    const type =
      typeRaw === "tag" || typeRaw === "phrase"
        ? typeRaw
        : query.startsWith("#")
          ? "tag"
          : "phrase";
    return { query, type };
  }
  return null;
}

function compactList(values, empty = "无") {
  const list = Array.isArray(values)
    ? values.map((item) => formatWatchQueryLabel(item) || String(item || "")).filter(Boolean)
    : [];
  if (!list.length) {
    return el("span", { className: "muted", text: empty });
  }
  return fragment(list.map((item) => el("span", { className: "chip", text: item })));
}

function selectedGroupId() {
  return state.selectedGroupId || "";
}



function selectedHistoryGroupId() {
  return els.historyGroupSelect.value || state.historyGroupId || "";
}

function groupOptions(includeAll = false) {
  const options = [];
  if (includeAll) {
    options.push(el("option", { attrs: { value: "" }, text: "全部分组" }));
  }
  state.groups.forEach((group) => {
    options.push(
      el("option", {
        attrs: { value: group.group_id },
        text: `${group.name} (${group.group_id})`,
      }),
    );
  });
  return options;
}

function syncSelectors() {
  const groupIds = new Set(state.groups.map((group) => group.group_id));
  const firstGroupId = state.groups[0]?.group_id || "";
  if (!groupIds.has(state.selectedGroupId)) {
    state.selectedGroupId = firstGroupId;
  }
  const currentHistory =
    state.historyGroupId && groupIds.has(state.historyGroupId)
      ? state.historyGroupId
      : "";
  els.historyGroupSelect.replaceChildren(...groupOptions(true));
  els.historyGroupSelect.value = currentHistory;
  state.historyGroupId = els.historyGroupSelect.value;
  state.seenGroupId = els.seenGroupSelect.value;
}

function emptyState(text) {
  return el("div", { className: "empty" }, [el("strong", { text })]);
}

function buildInfoTable(rows, className = "info-table") {
  const tbody = el("tbody");
  rows.forEach(([label, value]) => {
    const row = el("tr");
    const cell = el("td");
    appendChildren(cell, value);
    row.append(el("th", { text: label }), cell);
    tbody.appendChild(row);
  });
  return el("table", { className }, [tbody]);
}

function buildPanel(title, rows, tableClass = "info-table", panelClass = "panel") {
  return el("div", { className: panelClass }, [
    el("h2", { text: title }),
    buildInfoTable(rows, tableClass),
  ]);
}

function buildChipSection(title, values, className = "chip-list") {
  const list = el("div", { className });
  list.appendChild(compactList(values));
  return el("div", {}, [el("b", { text: title }), list]);
}

function buildWatchUserSection(group) {
  const users = Array.isArray(group.watch_users)
    ? group.watch_users.filter(Boolean)
    : [];
  const list = el("div", { className: "chip-list" });
  if (!users.length) {
    list.appendChild(el("span", { className: "muted", text: "无" }));
  } else {
    list.append(
      ...users.map((username) =>
        el(
          "button",
          {
            className: "chip chip-action",
            attrs: {
              type: "button",
              title: `删除关注账号 ${username}`,
            },
            dataset: {
              deleteWatchUser: username,
              deleteWatchUserGroup: group.group_id,
            },
            disabled: state.loading || state.actionBusy,
          },
          username,
        ),
      ),
    );
  }
  return el("div", {}, [el("b", { text: "关注账号" }), list]);
}

function buildWatchQuerySection(group, draft) {
  const queries = Array.isArray(draft.watch_queries)
    ? draft.watch_queries.map(normalizeWatchQueryItem).filter(Boolean)
    : [];
  const list = el("div", { className: "chip-list" });
  if (!queries.length) {
    list.appendChild(el("span", { className: "muted", text: "空" }));
  } else {
    list.append(
      ...queries.map((item, index) =>
        el(
          "button",
          {
            className: "chip chip-action",
            attrs: {
              type: "button",
              title: `删除查询 ${item.query}`,
            },
            dataset: {
              deleteWatchQueryIndex: String(index),
              deleteWatchQueryGroup: group.group_id,
            },
            disabled: state.loading || state.actionBusy,
          },
          formatWatchQueryLabel(item),
        ),
      ),
    );
  }
  const queryInput = el("input", {
    attrs: {
      id: "groupQueryInput",
      type: "text",
      placeholder: "#标签 或 短语关键词",
    },
    disabled: state.loading || state.actionBusy,
  });
  return el("section", { className: "editor-section" }, [
    el("div", { className: "section-head" }, [el("h3", { text: "搜索订阅" })]),
    el("p", {
      className: "helper-text",
      text: "前导 # 为标签；否则为短语。不会自动给短语加 #。",
    }),
    el("p", {
      className: "helper-text",
      text: "风险提示：使用私人 QQ 号作为 Bot 时，不建议开启标签分组定时功能。",
    }),
    el("div", { className: "input-with-actions" }, [
      editorField("添加查询", queryInput),
      el(
        "button",
        {
          className: "button primary",
          attrs: { type: "button" },
          dataset: { addWatchQuery: group.group_id },
          disabled: state.loading || state.actionBusy,
        },
        [iconSpan("plus"), "添加"],
      ),
    ]),
    el("div", { className: "details-grid" }, [
      el("div", {}, [el("b", { text: "当前查询" }), list]),
      buildChipSection(
        "无效查询",
        group.invalid_watch_queries,
        "chip-list bad",
      ),
      buildChipSection(
        "重复查询",
        group.duplicate_watch_queries,
        "chip-list warn",
      ),
    ]),
  ]);
}

function inferQueryType(query) {
  return String(query || "")
    .trim()
    .startsWith("#")
    ? "tag"
    : "phrase";
}

function addWatchQuery(groupId) {
  const input = document.getElementById("groupQueryInput");
  const raw = String(input?.value || "").trim();
  if (!raw) {
    showAlert("请输入查询内容", "error");
    return;
  }
  const draft =
    state.groupDrafts[groupId] ||
    snapshotEditableGroup(
      state.groups.find((item) => item.group_id === groupId) || {},
    );
  const next = [...(draft.watch_queries || [])];
  const type = inferQueryType(raw);
  let query = raw;
  if (type === "tag" && !query.startsWith("#")) {
    query = `#${query}`;
  }
  if (
    next.some(
      (item) => String(item.query).toLowerCase() === query.toLowerCase(),
    )
  ) {
    showAlert("查询已存在", "error");
    return;
  }
  next.push({ query, type });
  updateGroupDraft(groupId, "watch_queries", next);
  if (input) input.value = "";
  renderGroupEditor();
}

function deleteWatchQuery(groupId, index) {
  const draft = state.groupDrafts[groupId];
  if (!draft || !Array.isArray(draft.watch_queries)) return;
  if (index < 0 || index >= draft.watch_queries.length) return;
  const next = draft.watch_queries.filter((_, i) => i !== index);
  updateGroupDraft(groupId, "watch_queries", next);
  renderGroupEditor();
}

function buildPushTargetEditor(group, draft) {
  const targets = Array.isArray(draft.push_targets)
    ? draft.push_targets.filter(Boolean)
    : [];
  const list = el("div", { className: "chip-list mono editable-chip-list" });
  if (!targets.length) {
    list.appendChild(el("span", { className: "muted", text: "无" }));
  } else {
    list.append(
      ...targets.map((target, index) =>
        el(
          "button",
          {
            className: "chip chip-action",
            attrs: {
              type: "button",
              title: `删除推送目标 ${target}`,
            },
            dataset: {
              deletePushTarget: String(index),
              deletePushTargetGroup: group.group_id,
            },
            disabled: state.loading || state.actionBusy,
          },
          target,
        ),
      ),
    );
  }
  return el("div", { className: "push-target-editor" }, [
    el("b", { text: "推送目标" }),
    list,
    el("div", { className: "target-edit-row" }, [
      el("input", {
        attrs: {
          id: "pushTargetInput",
          type: "text",
          placeholder: "platform:MessageType:session_id",
        },
        dataset: { pushTargetInput: group.group_id },
        disabled: state.loading || state.actionBusy,
      }),
      el("button", {
        className: "button primary small",
        attrs: { type: "button" },
        dataset: { addPushTarget: group.group_id },
        disabled: state.loading || state.actionBusy,
      }, [iconSpan("plus"), "新增"]),
      el("button", {
        className: "button secondary small",
        attrs: { type: "button" },
        dataset: { probePushTargets: group.group_id },
        disabled: state.loading || state.actionBusy || !targets.length,
      }, [iconSpan("probe"), "检测目标"]),
    ]),
    renderTargetProbeResults(group.group_id),
  ]);
}

function renderTargetProbeResults(groupId) {
  const payload = state.targetProbeResults[groupId];
  if (!payload) {
    return null;
  }
  const rows = payload.targets || [];
  const summary = payload.summary || {};
  return el("div", { className: "target-probe-results" }, [
    el("small", {
      className: "muted",
      text: `检测 ${formatNumber(summary.total)} 个，有效 ${formatNumber(summary.valid)} 个，异常 ${formatNumber(summary.invalid)} 个`,
    }),
    el(
      "div",
      { className: "chip-list mono" },
      rows.map((row) =>
        el("span", {
          className: `chip ${row.valid ? "" : "bad"}`.trim(),
          attrs: {
            title: row.valid
              ? `${row.platform_kind || "default"} · ${row.platform_found ? "已找到平台实例" : "未找到平台实例"} · ${row.supports_merged_forward ? "支持合并转发" : "普通发送"}`
              : row.error,
          },
          text: row.valid
            ? `${shortUmoLabel(row.umo)} · ${row.platform_kind || "default"}`
            : `${row.umo || "空目标"} · 无效`,
        }),
      ),
    ),
  ]);
}

function buildAttentionBadge(item) {
  return el(
    "span",
    {
      className: `attention-badge ${item.level || "info"}`,
      attrs: { title: item.detail || "" },
      text: item.title || "",
    },
  );
}

function snapshotEditableGroup(group) {
  return {
    group_id: group.group_id,
    name: group.name,
    enabled: !!group.enabled,
    group_type: group.group_type || "blogger",
    interval_check_enabled: !!group.interval_check_enabled,
    daily_check_times: [...(group.daily_check_times || [])],
    filter_plain_text_enabled: !!group.filter_plain_text_enabled,
    media_only_enabled: !!group.media_only_enabled,
    omit_status_url: group.omit_status_url !== false,
    hide_original_when_translated: !!group.hide_original_when_translated,
    push_targets: [...(group.push_targets || [])],
    watch_queries: (group.watch_queries || [])
      .map(normalizeWatchQueryItem)
      .filter(Boolean),
  };
}

function syncGroupDrafts() {
  const nextDrafts = {};
  state.groups.forEach((group) => {
    nextDrafts[group.group_id] =
      state.groupDrafts[group.group_id] || snapshotEditableGroup(group);
  });
  state.groupDrafts = nextDrafts;
}

function isGroupDirty(groupId) {
  const group = state.groups.find((item) => item.group_id === groupId);
  const draft = state.groupDrafts[groupId];
  if (!group || !draft) return false;
  return JSON.stringify(snapshotEditableGroup(group)) !== JSON.stringify(draft);
}

function hasDirtyGroup() {
  return state.groups.some((group) => isGroupDirty(group.group_id));
}

function updateGroupDraft(groupId, key, value) {
  if (!state.groupDrafts[groupId]) {
    const group = state.groups.find((item) => item.group_id === groupId);
    if (!group) return;
    state.groupDrafts[groupId] = snapshotEditableGroup(group);
  }
  state.groupDrafts[groupId][key] = value;
  renderGroupList();
  syncGroupEditorControls(groupId);
}

function groupDraft(group) {
  return state.groupDrafts[group.group_id] || snapshotEditableGroup(group);
}

function syncGroupEditorControls(groupId) {
  const group = state.groups.find((item) => item.group_id === groupId);
  const draft = state.groupDrafts[groupId];
  if (!group || !draft) return;
  const dirty = isGroupDirty(groupId);
  const saveButton = [...els.groupEditor.querySelectorAll("[data-save-group]")].find(
    (node) => node.dataset.saveGroup === groupId,
  );
  if (saveButton) {
    saveButton.disabled =
      !dirty || state.loading || state.actionBusy;
  }
  const checkButton = [...els.groupEditor.querySelectorAll("[data-check-group]")].find(
    (node) => node.dataset.checkGroup === groupId,
  );
  if (checkButton) {
    checkButton.disabled = !group.enabled || dirty || state.loading || state.actionBusy;
    checkButton.title = !group.enabled
      ? "分组停用时不能立即检查"
      : dirty
        ? "请先保存更改"
        : "";
  }
  const title = [...els.groupEditor.querySelectorAll("[data-group-title]")].find(
    (node) => node.dataset.groupTitle === groupId,
  );
  if (title) {
    title.textContent = draft.name || group.name;
  }
}

function editorField(label, control) {
  return el("label", { className: "editor-field" }, [
    el("span", { className: "editor-label", text: label }),
    control,
  ]);
}

function readonlyField(text) {
  return el("div", { className: "readonly-field", text });
}

function toggleField(groupId, key, checked) {
  const input = el("input", {
    attrs: { type: "checkbox" },
    dataset: { groupId, groupField: key, fieldType: "checkbox" },
    disabled: state.loading || state.actionBusy,
  });
  input.checked = !!checked;
  return el("label", { className: "toggle-field" }, [
    input,
    checked ? "已开启" : "已关闭",
  ]);
}

function textInput(groupId, key, value, placeholder = "") {
  return el("input", {
    attrs: { type: "text", value: value || "", placeholder },
    dataset: { groupId, groupField: key, fieldType: "text" },
    disabled: state.loading || state.actionBusy,
  });
}

function groupRuntimeCard(label, value) {
  return el("div", { className: "runtime-item" }, [
    el("span", { text: label }),
    el("strong", { text: value }),
  ]);
}

function renderOverview() {
  const payload = state.overview;
  if (!payload) {
    els.overviewView.replaceChildren(emptyState("正在加载概览"));
    return;
  }
  const counts = payload.counts || {};
  const scheduler = payload.scheduler || {};
  const features = payload.features || {};
  const configSummary = payload.config_summary || {};
  const attentionItems = payload.attention_items || [];
  const stats = [
    ["调度器", scheduler.running ? "运行中" : "未运行"],
    ["后台检查", scheduler.schedule_enabled ? "已开启" : "已关闭"],
    [
      "推送分组",
      `${formatNumber(counts.groups)} / 启用 ${formatNumber(counts.enabled_groups)}`,
    ],
    ["关注账号（博主）", formatNumber(counts.watch_users)],
    ["推送目标", formatNumber(counts.push_targets)],
    ["无效推送目标", formatNumber(counts.invalid_push_targets)],
  ];
  const featureRows = [
    ["图片附件", formatBool(features.images)],
    ["视频/GIF", formatBool(features.videos)],
    ["翻译", formatBool(features.translation)],
  ];
  const configRows = [
    ["Nitter 实例", formatNumber(configSummary.nitter_instance_count)],
    ["手动默认数量", formatNumber(configSummary.default_limit)],
    ["检查间隔", `${formatNumber(configSummary.check_interval_minutes)} 分钟`],
    ["合并阈值", formatNumber(configSummary.merge_tweet_threshold)],
    ["目标间隔", `${formatNumber(configSummary.send_target_interval)} 秒`],
    ["并发拉取", formatBool(configSummary.concurrent_fetch_enabled)],
    ["并发准备", formatBool(configSummary.concurrent_prepare_enabled)],
  ];
  const metrics = el(
    "div",
    { className: "metrics-grid" },
    stats.map(([label, value]) =>
      el("div", { className: "metric" }, [
        el("span", { text: label }),
        el("strong", { text: value }),
      ]),
    ),
  );
  const panels = el("div", { className: "overview-panels" }, [
    buildPanel("博主订阅状态", [
      ["原始关注项", formatNumber(counts.raw_watch_users)],
      ["重复关注项", formatNumber(counts.duplicate_watch_users)],
      ["无效关注项", formatNumber(counts.invalid_watch_users)],
    ]),
    buildPanel("功能开关", featureRows),
    buildPanel("配置摘要", configRows),
  ]);
  const attentionList = el(
    "div",
    { className: "attention-list" },
    attentionItems.map((item) =>
      el("div", { className: `attention-item ${item.level || "info"}` }, [
        el("strong", { text: item.title || "" }),
        el("span", { text: item.detail || "" }),
      ]),
    ),
  );
  const attentionPanel = el("div", { className: "panel attention-panel" }, [
    el("h2", { text: "需要关注" }),
    attentionList,
  ]);
  els.overviewView.replaceChildren(metrics, panels, attentionPanel);
}

function renderGroupList() {
  if (!state.groups.length) {
    els.groupList.replaceChildren(emptyState("暂无分组"));
    return;
  }
  const items = state.groups.map((group) => {
    const typeLabel = group.group_type === "tag" ? "标签" : "博主";
    const subCount =
      group.group_type === "tag"
        ? formatNumber(group.watch_query_count || 0)
        : formatNumber(group.watch_user_count);
    const subLabel = group.group_type === "tag" ? "查询" : "关注";
    const meta = el("div", { className: "group-list-meta" }, [
      el("span", { text: group.group_id }),
      el("span", { text: typeLabel }),
      el("span", { text: group.enabled ? "启用" : "停用" }),
      el("span", {
        text: `${subLabel} ${subCount} · 目标 ${formatNumber(group.push_target_count)}`,
      }),
    ]);
    const alerts = el(
      "div",
      { className: "group-list-alerts" },
      (group.attention_items || []).slice(0, 2).map((item) => buildAttentionBadge(item)),
    );
    return el(
      "button",
      {
        className: `group-list-item ${group.group_id === state.selectedGroupId ? "active" : ""}`,
        attrs: { type: "button" },
        dataset: { groupSelect: group.group_id },
        disabled: state.loading || state.actionBusy,
      },
      [
        el("strong", { text: group.name }),
        meta,
        isGroupDirty(group.group_id)
          ? el("span", { className: "dirty-badge", text: "未保存" })
          : null,
        alerts,
      ],
    );
  });
  els.groupList.replaceChildren(...items);
}

function renderGroupEditor() {
  const group = state.groups.find(
    (item) => item.group_id === state.selectedGroupId,
  );
  if (!group) {
    els.groupEditor.replaceChildren(emptyState("请选择一个分组"));
    return;
  }
  const draft = groupDraft(group);
  const dirty = isGroupDirty(group.group_id);
  const checkButton = el(
    "button",
    {
      className: "button secondary small",
      attrs: {
        type: "button",
        title: !group.enabled
          ? "分组停用时不能立即检查"
          : dirty
            ? "请先保存更改"
            : null,
      },
      dataset: { checkGroup: group.group_id },
      disabled: !group.enabled || dirty || state.loading || state.actionBusy,
    },
    [iconSpan("play"), "立即检查"],
  );
  const saveButton = el(
    "button",
    {
      className: "button primary small",
      attrs: { type: "button" },
      dataset: { saveGroup: group.group_id },
      disabled: !isGroupDirty(group.group_id) || state.loading || state.actionBusy,
    },
    "保存更改",
  );
  const deleteButton = el(
    "button",
    {
      className: "button danger ghost small",
      attrs: { type: "button" },
      dataset: { deleteGroup: group.group_id },
      disabled:
        group.group_id === "default" || state.loading || state.actionBusy,
    },
    "删除分组",
  );
  const editor = el("div", { className: "panel group-editor-panel" }, [
    el("div", { className: "panel-head" }, [
      el("div", {}, [
        el("div", { className: "group-title-row" }, [
          el("h2", {
            text: draft.name || group.name,
            dataset: { groupTitle: group.group_id },
          }),
          el("span", {
            className: `badge ${group.enabled ? "" : "warning"}`.trim(),
            text: group.enabled ? "启用中" : "已停用",
          }),
        ]),
        (group.attention_items || []).length
          ? el(
              "div",
              { className: "group-list-alerts" },
              (group.attention_items || []).map((item) =>
                buildAttentionBadge(item),
              ),
            )
          : null,
      ]),
      el("div", { className: "row-actions" }, [
        checkButton,
        saveButton,
        deleteButton,
      ]),
    ]),
    el("div", { className: "editor-grid" }, [
      editorField("分组名称", textInput(group.group_id, "name", draft.name)),
      editorField("分组 ID", readonlyField(group.group_id)),
      editorField(
        "分组类型",
        readonlyField(group.group_type === "tag" ? "标签分组" : "博主分组"),
      ),
      editorField(
        "启用分组",
        toggleField(group.group_id, "enabled", draft.enabled),
      ),
      editorField(
        "间隔检查",
        toggleField(
          group.group_id,
          "interval_check_enabled",
          draft.interval_check_enabled,
        ),
      ),
      editorField(
        "检查间隔",
        readonlyField(
          `继承全局 ${formatNumber(group.check_interval_minutes)} 分钟`,
        ),
      ),
      editorField(
        "每日检查",
        textInput(
          group.group_id,
          "daily_check_times",
          (draft.daily_check_times || []).join(","),
          "08:30,21:05",
        ),
      ),
      editorField(
        "纯文本过滤",
        toggleField(
          group.group_id,
          "filter_plain_text_enabled",
          draft.filter_plain_text_enabled,
        ),
      ),
      editorField(
        "仅媒体",
        toggleField(
          group.group_id,
          "media_only_enabled",
          draft.media_only_enabled,
        ),
      ),
      editorField(
        "发送时去除推文链接",
        toggleField(
          group.group_id,
          "omit_status_url",
          draft.omit_status_url !== false,
        ),
      ),
      editorField(
        "有翻译时只显示译文",
        toggleField(
          group.group_id,
          "hide_original_when_translated",
          !!draft.hide_original_when_translated,
        ),
      ),
      el("p", {
        className: "helper-text",
        text: "开启后：存在译文时隐藏原文块，仅发送翻译；无译文时仍显示原文。仅媒体模式不调用翻译。",
      }),

      el("p", {
        className: "helper-text",
        text: "默认开启：不发送推文 URL 明文，并去掉正文/译文中的 http(s) 链接。Telegram 仍可用摘要链到原文。仅媒体模式不调用翻译。",
      }),
      el("p", {
        className: "helper-text",
        text: "受全局图片和视频/GIF附件开关控制。",
      }),
      draft.media_only_enabled && group.media_only_unavailable_reason
        ? el("p", {
            className: "helper-text",
            text: "当前全局媒体不可用，“仅媒体”暂不生效，将发送完整内容。",
          })
        : null,
    ]),
    group.group_type === "tag"
      ? buildWatchQuerySection(group, draft)
      : el("section", { className: "editor-section" }, [
          el("div", { className: "section-head" }, [
            el("h3", { text: "关注账号" }),
          ]),
      el("div", { className: "input-with-actions" }, [
        editorField(
          "批量导入或删除",
          el("input", {
            attrs: {
              id: "groupSubscriptionInput",
              type: "text",
              placeholder: "NASA,@OpenAI",
            },
            disabled: state.loading || state.actionBusy,
          }),
        ),
        el(
          "button",
          {
            className: "button primary",
            attrs: { type: "button" },
            dataset: { importGroup: group.group_id },
            disabled: state.loading || state.actionBusy,
          },
          [iconSpan("plus"), "导入"],
        ),
        el(
          "button",
          {
            className: "button danger ghost",
            attrs: { type: "button" },
            dataset: { deleteSubscriptions: group.group_id },
            disabled: state.loading || state.actionBusy,
          },
          [iconSpan("trash"), "删除"],
        ),
      ]),
      el("div", { className: "details-grid" }, [
        buildWatchUserSection(group),
            buildChipSection(
              "无效关注账号",
              group.invalid_watch_users,
              "chip-list bad",
            ),
            buildChipSection(
              "重复关注项",
              group.duplicate_watch_users,
              "chip-list warn",
            ),
      ]),
    ]),
    el("section", { className: "editor-section" }, [
      el("div", { className: "section-head" }, [
        el("h3", { text: "推送目标" }),
        el("span", { className: "helper-text", text: "按 /sid 返回值维护" }),
      ]),
      el("div", { className: "details-grid" }, [
        buildPushTargetEditor(group, draft),
        buildChipSection(
          "无效推送目标",
          group.invalid_push_targets,
          "chip-list bad",
        ),
        buildChipSection("分组别名", group.aliases),
      ]),
    ]),
    el("section", { className: "editor-section" }, [
      el("div", { className: "section-head" }, [
        el("h3", { text: "运行摘要" }),
      ]),
      el("div", { className: "runtime-grid" }, [
        groupRuntimeCard(
          "无效推送目标",
          formatNumber(group.invalid_push_target_count),
        ),
        group.group_type === "tag"
          ? groupRuntimeCard(
              "无效搜索查询",
              formatNumber(group.invalid_watch_queries?.length),
            )
          : groupRuntimeCard(
              "无效关注账号",
              formatNumber(group.invalid_watch_users?.length),
            ),
      ]),
    ]),
  ]);
  els.groupEditor.replaceChildren(editor);
  mountIcons(els.groupEditor);
}

function renderGroups() {
  renderGroupList();
  renderGroupEditor();
}



function renderHistory() {
  const payload = state.history;
  renderHistoryPager(payload);
  if (!payload) {
    els.historyContent.replaceChildren(emptyState("正在加载最近推送"));
    return;
  }
  const records = payload.records || [];
  if (!records.length) {
    els.historyContent.replaceChildren(
      emptyState("暂无发送成功历史，新版本启用后成功送达的推送会显示在这里。"),
    );
    return;
  }
  const tbody = el(
    "tbody",
    {},
    records.map((row) => {
      const tweetCell = el("td", {}, [
        externalLink(row.original_link, row.status_id || row.original_link),
        el("span", { text: row.text_preview || "" }),
      ]);
      return el("tr", {}, [
        el("td", { text: formatTime(row.pushed_at) }),
        el("td", { text: row.group_name || row.group_id || "-" }),
        el("td", { text: `@${row.username}` }),
        tweetCell,
        el("td", {}, [historyTargetChips(row)]),
        el("td", { text: row.source || "-" }),
        el("td", {}, [historyDeliveryStatus(row)]),
        el("td", {}, [
          el(
            "button",
            {
              className: "button secondary small",
              attrs: { type: "button" },
              dataset: { replayHistory: row.id },
              disabled: state.loading || state.actionBusy,
            },
            [iconSpan("send"), "重新推送"],
          ),
        ]),
      ]);
    }),
  );
  els.historyContent.replaceChildren(
    el("div", { className: "table-wrap" }, [
      el("table", { className: "data-table history-table" }, [
        el("thead", {}, [
          el("tr", {}, [
            el("th", { text: "发送时间" }),
            el("th", { text: "分组" }),
            el("th", { text: "博主" }),
            el("th", { text: "推文" }),
            el("th", { text: "当时推送目标" }),
            el("th", { text: "来源" }),
            el("th", { text: "状态" }),
            el("th", { text: "操作" }),
          ]),
        ]),
        tbody,
      ]),
    ]),
  );
  mountIcons(els.historyContent);
}

function renderHistoryOrphans(payload = state.historyOrphans) {
  if (!els.historyOrphanResult) return;
  if (!payload) {
    els.historyOrphanResult.replaceChildren();
    return;
  }
  const orphans = Array.isArray(payload.orphans) ? payload.orphans : [];
  if (!orphans.length) {
    els.historyOrphanResult.replaceChildren(
      el("div", {
        className: "result-line",
        text: "未发现已推送但当前配置不存在的分组 ID。",
      }),
    );
    return;
  }
  const tbody = el(
    "tbody",
    {},
    orphans.map((row) =>
      el("tr", {}, [
        el("td", { className: "mono-cell", text: row.group_id || "-" }),
        el("td", { text: formatNumber(row.record_count) }),
        el("td", { text: formatNumber(row.user_count) }),
        el("td", { text: formatTime(row.latest_pushed_at) }),
        el("td", {}, [
          el(
            "button",
            {
              className: "button danger small",
              attrs: {
                type: "button",
                "data-delete-history-orphan": row.group_id,
              },
              disabled: state.loading || state.actionBusy,
            },
            [iconSpan("trash"), "删除运行数据"],
          ),
        ]),
      ]),
    ),
  );
  els.historyOrphanResult.replaceChildren(
    el("div", { className: "panel" }, [
      el("div", { className: "panel-head" }, [
        el("h2", { text: "失效分组记录" }),
        el("span", {
          className: "badge warning",
          text: `${formatNumber(orphans.length)} 个分组`,
        }),
      ]),
      el("p", {
        className: "muted",
        text: "这些 group_id 存在于推送历史，但当前配置里已经没有对应分组。删除会清理该 group_id 的推送历史和防重复推送记录。",
      }),
      el("div", { className: "table-wrap" }, [
        el("table", { className: "data-table" }, [
          el("thead", {}, [
            el("tr", {}, [
              el("th", { text: "Group ID" }),
              el("th", { text: "记录" }),
              el("th", { text: "账号" }),
              el("th", { text: "最近推送" }),
              el("th", { text: "操作" }),
            ]),
          ]),
          tbody,
        ]),
      ]),
    ]),
  );
  mountIcons(els.historyOrphanResult);
}

function renderHistoryPager(payload = state.history) {
  const page = Math.max(1, Number(payload?.page || 1));
  const totalPages = Math.max(1, Number(payload?.total_pages || 1));
  els.historyPageLabel.textContent = `${page} / ${totalPages}`;
  els.historyPrevBtn.disabled = state.loading || state.actionBusy || !payload?.has_prev;
  els.historyNextBtn.disabled = state.loading || state.actionBusy || !payload?.has_next;
}

function mirrorModeValue() {
  return String(els.mirrorMode?.value || "blogger_rss").trim() || "blogger_rss";
}

function instancesForMirrorMode(mode) {
  const lists = state.overview?.instance_lists || {};
  const rss = Array.isArray(lists.rss)
    ? lists.rss
    : Array.isArray(state.overview?.instances)
      ? state.overview.instances
      : [];
  if (mode === "blogger_html") {
    return Array.isArray(lists.blogger_html) ? lists.blogger_html : [];
  }
  if (mode === "search") {
    return Array.isArray(lists.search) ? lists.search : [];
  }
  return rss;
}

function syncMirrorModeUi() {
  const mode = mirrorModeValue();
  const isSearch = mode === "search";
  if (els.mirrorQueryLabel) {
    els.mirrorQueryLabel.textContent = isSearch ? "搜索内容" : "用户名";
  }
  if (els.mirrorUsername) {
    els.mirrorUsername.placeholder = isSearch
      ? "#标签 或 短语（不自动加 #）"
      : "nasa";
    if (isSearch && String(els.mirrorUsername.value || "").toLowerCase() === "nasa") {
      els.mirrorUsername.value = "";
    }
    if (!isSearch && !String(els.mirrorUsername.value || "").trim()) {
      els.mirrorUsername.value = "nasa";
    }
  }
  const titles = {
    blogger_rss: "配置实例（RSS）",
    blogger_html: "配置实例（博主 HTML）",
    search: "配置实例（搜索）",
  };
  if (els.mirrorInstanceListTitle) {
    els.mirrorInstanceListTitle.textContent = titles[mode] || titles.blogger_rss;
  }
  if (els.mirrorInstanceListHint) {
    els.mirrorInstanceListHint.textContent = isSearch
      ? "点击填入左侧 URL；搜索请用 search_instances，勿混用 RSS 列表"
      : "点击填入左侧 URL";
  }
}

function renderMirrorBase() {
  syncMirrorModeUi();
  const mode = mirrorModeValue();
  const instances = instancesForMirrorMode(mode);
  if (!els.mirrorInstance.value && instances.length) {
    els.mirrorInstance.value = instances[0];
  }
  if (!instances.length) {
    els.instanceList.replaceChildren(
      el("span", {
        className: "muted",
        text: "当前模式未配置实例，可手填临时 URL",
      }),
    );
    return;
  }
  const chips = instances.map((item) =>
    el(
      "button",
      {
        className: "chip chip-action",
        attrs: { type: "button", title: `使用 ${item}` },
        dataset: { mirrorInstancePick: item },
        disabled: state.loading || state.actionBusy,
      },
      item,
    ),
  );
  els.instanceList.replaceChildren(...chips);
}

function renderCleanupSelectors() {
  els.seenGroupSelect.replaceChildren(...groupOptions(true));
  els.seenGroupSelect.value = state.seenGroupId;
  state.seenGroupId = els.seenGroupSelect.value;
}

function renderAll() {
  syncSelectors();
  updateViewHeader();
  renderRailStatus();
  renderOverview();
  renderGroups();
  renderHistory();
  renderHistoryOrphans();
  renderMirrorBase();
  renderCleanupSelectors();
  mountIcons();
}



async function loadHistory() {
  state.historyGroupId = selectedHistoryGroupId();
  state.historyUsername = els.historyUsername.value.trim();
  state.historyLimit = Math.max(1, Math.min(Number(els.historyLimit.value || 10), 50));
  els.historyLimit.value = String(state.historyLimit);
  state.historyOffset = Math.max(0, Number(state.historyOffset || 0));
  state.history = await apiGet("web/history", {
    group_id: state.historyGroupId,
    username: state.historyUsername,
    limit: state.historyLimit,
    offset: state.historyOffset,
  });
  state.historyOffset = Math.max(0, Number(state.history.offset || 0));
  renderHistory();
}

function resetHistoryPage() {
  state.historyOffset = 0;
}

async function loadHistoryPage(offset) {
  state.historyOffset = Math.max(0, Number(offset || 0));
  await loadHistory();
}

async function detectHistoryOrphans() {
  state.historyOrphans = await apiGet("web/history/orphans");
  renderHistoryOrphans();
  return state.historyOrphans;
}

async function reloadAll(options = {}) {
  setBusy(true);
  hideAlert();
  try {
    await bridge.ready();
    const [overview, groups] = await Promise.all([
      apiGet("web/overview"),
      apiGet("web/groups"),
    ]);
    state.overview = overview;
    state.groups = Array.isArray(groups.groups) ? groups.groups : [];
    if (!state.selectedGroupId && state.groups[0]) {
      state.selectedGroupId = state.groups[0].group_id;
    }
    if (!state.groups.some((group) => group.group_id === state.selectedGroupId)) {
      state.selectedGroupId = state.groups[0]?.group_id || "";
    }
    if (options.preserveDrafts === false) {
      state.groupDrafts = {};
    }
    syncGroupDrafts();
    syncSelectors();
    await loadHistory();
    state.lastUpdated = new Date().toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    els.lastUpdated.textContent = `更新于 ${state.lastUpdated}`;
    setBusy(false);
    renderAll();
    return true;
  } catch (error) {
    showAlert(error.message || "加载失败", "error");
    return false;
  } finally {
    if (state.loading) {
      setBusy(false);
    }
  }
}

async function refreshDashboard() {
  if (hasDirtyGroup()) {
    const confirmed = window.confirm("分组订阅有未保存更改，刷新会丢弃这些草稿。继续刷新？");
    if (!confirmed) {
      return;
    }
  }
  await reloadAll({ preserveDrafts: false });
}

function switchView(view) {
  state.view = view;
  updateViewHeader();
  els.tabs.forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-pressed", String(active));
  });
  els.views.forEach((section) => {
    section.classList.toggle("active", section.id === `${view}View`);
  });
}

function confirmFocusableElements() {
  return [...els.confirmDialog.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
  )].filter((node) => !node.disabled && node.offsetParent !== null);
}

function setBackgroundInert(isInert) {
  const nodes = [
    document.querySelector(".topbar"),
    document.querySelector(".tabs"),
    document.querySelector("main"),
    els.alert,
  ].filter(Boolean);
  state.inertNodes = isInert ? nodes : [];
  nodes.forEach((node) => {
    if ("inert" in node) {
      node.inert = isInert;
    } else if (isInert) {
      node.setAttribute("aria-hidden", "true");
    } else {
      node.removeAttribute("aria-hidden");
    }
  });
}

function openConfirm({
  kicker = "确认操作",
  title,
  desc,
  confirmText,
  danger = true,
  action,
}) {
  if (!els.confirmDialog.hidden) {
    closeConfirm({ restoreFocus: false });
  }
  state.lastFocusedElement = document.activeElement;
  state.pendingAction = action;
  els.confirmKicker.textContent = kicker;
  els.confirmTitle.textContent = title;
  els.confirmDesc.replaceChildren();
  if (desc instanceof Node) {
    els.confirmDesc.appendChild(desc);
  } else {
    els.confirmDesc.textContent = desc;
  }
  els.confirmActionBtn.textContent = confirmText || "确认";
  els.confirmActionBtn.disabled = false;
  els.confirmActionBtn.classList.toggle("danger", danger);
  els.confirmDialog.hidden = false;
  document.body.classList.add("dialog-open");
  setBackgroundInert(true);
  const focusable = confirmFocusableElements();
  if (focusable.length) {
    focusable[0].focus();
  } else {
    els.confirmDialog.focus();
  }
}

function closeConfirm(options = {}) {
  const restoreFocus = options.restoreFocus !== false;
  els.confirmDialog.hidden = true;
  state.pendingAction = null;
  document.body.classList.remove("dialog-open");
  setBackgroundInert(false);
  if (
    restoreFocus &&
    state.lastFocusedElement &&
    document.contains(state.lastFocusedElement) &&
    typeof state.lastFocusedElement.focus === "function"
  ) {
    state.lastFocusedElement.focus();
  }
  state.lastFocusedElement = null;
}

function trapConfirmFocus(event) {
  if (els.confirmDialog.hidden || event.key !== "Tab") {
    return;
  }
  const focusable = confirmFocusableElements();
  if (!focusable.length) {
    event.preventDefault();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

async function withAction(action, successText, options = {}) {
  state.actionBusy = true;
  setBusy(true);
  hideAlert();
  try {
    const result = await action();
    const successMessage = successText || result.message || "操作完成";
    state.actionBusy = false;
    if (options.reload !== false) {
      const reloaded = await reloadAll();
      if (reloaded === false) {
        return result;
      }
    } else if (typeof options.rerender === "function") {
      setBusy(false);
      options.rerender();
    }
    showAlert(successMessage, "success");
    return result;
  } catch (error) {
    showAlert(error.message || "操作失败", "error");
    return null;
  } finally {
    if (state.actionBusy) {
      state.actionBusy = false;
    }
    setBusy(false);
  }
}

function selectGroup(groupId) {
  if (!groupId || groupId === state.selectedGroupId) {
    return;
  }
  const previousId = state.selectedGroupId;
  if (previousId && isGroupDirty(previousId)) {
    const confirmed = window.confirm("当前分组有未保存修改，确认切换并丢弃草稿？");
    if (!confirmed) {
      return;
    }
    delete state.groupDrafts[previousId];
  }
  state.selectedGroupId = groupId;
  renderGroups();
}

function createGroup() {
  const nameInput = el("input", {
    attrs: {
      type: "text",
      placeholder: "留空自动生成",
      autocomplete: "off",
    },
  });
  const typeSelect = el(
    "select",
    {
      attrs: { id: "createGroupType" },
    },
    [
      el("option", {
        attrs: { value: "blogger", selected: true },
        text: "博主分组",
      }),
      el("option", { attrs: { value: "tag" }, text: "标签分组" }),
    ],
  );
  const form = el("div", { className: "confirm-form" }, [
    el("label", { className: "field" }, [
      el("span", { text: "分组类型" }),
      typeSelect,
    ]),
    el("label", { className: "field" }, [
      el("span", { text: "分组名称" }),
      nameInput,
    ]),
    el("p", {
      className: "helper-text",
      text: "类型创建后不可修改。博主分组跟用户；标签分组跟搜索订阅（#标签 或短语）。",
    }),
    el("p", {
      className: "helper-text",
      text: "风险提示：若 Bot 使用私人 QQ 号，不建议创建或启用标签分组（定时搜索/推送较频繁，有封号风险）。",
    }),
  ]);
  openConfirm({
    kicker: "新建分组",
    title: "新建分组",
    desc: form,
    confirmText: "创建",
    danger: false,
    action: () =>
      withAction(async () => {
        const result = await apiPost("web/groups/create", {
          name: nameInput.value.trim(),
          group_type: typeSelect.value || "blogger",
        });
        // API returns { success, group: { group_id, ... } } via _ok(group=...).
        const newId = String(
          result?.group?.group_id || result?.group_id || "",
        ).trim();
        if (newId) {
          state.selectedGroupId = newId;
        }
        return result;
      }, "分组已创建"),
  });
}

async function runGroupCheck(groupId) {
  const group = state.groups.find((item) => item.group_id === groupId);
  openConfirm({
    kicker: "立即检查",
    title: "立即检查这个分组？",
    desc: `${group?.name || groupId} 将使用当前已保存配置检查推文，并可能立即推送到该分组的推送目标。`,
    confirmText: "开始检查",
    danger: false,
    action: () =>
      withAction(() => apiPost("web/check", { group_id: groupId }), "检查完成"),
  });
}



function subscriptionEntriesInput() {
  return document.getElementById("groupSubscriptionInput");
}

function subscriptionEntriesValue() {
  return subscriptionEntriesInput()?.value.trim() || "";
}

function pushTargetInput() {
  return document.getElementById("pushTargetInput");
}

function pushTargetList(groupId) {
  const group = state.groups.find((item) => item.group_id === groupId);
  const draft = state.groupDrafts[groupId] || (group ? snapshotEditableGroup(group) : null);
  return Array.isArray(draft?.push_targets) ? [...draft.push_targets] : [];
}

function addPushTarget(groupId) {
  const input = pushTargetInput();
  const value = input?.value.trim() || "";
  if (!value) {
    showAlert("请填写推送目标", "error");
    return;
  }
  const targets = pushTargetList(groupId);
  targets.push(value);
  updateGroupDraft(groupId, "push_targets", targets);
  renderGroupEditor();
}

async function probePushTargets(groupId) {
  const targets = pushTargetList(groupId);
  if (!targets.length) {
    showAlert("当前草稿没有推送目标", "error");
    return;
  }
  await withAction(async () => {
    const result = await apiPost("web/targets/probe", {
      group_id: groupId,
      target_umos: targets,
    });
    state.targetProbeResults[groupId] = result;
    return result;
  }, "推送目标检测完成", {
    reload: false,
    rerender: renderGroupEditor,
  });
}

function confirmDeletePushTarget(groupId, indexText) {
  const index = Number(indexText);
  const targets = pushTargetList(groupId);
  const target = targets[index];
  if (!Number.isInteger(index) || !target) return;
  openConfirm({
    kicker: "删除推送目标",
    title: "删除这个推送目标？",
    desc: "只会从当前分组配置移除推送目标，不会删除关注账号、媒体、推送记录或发送历史。",
    confirmText: "删除",
    action: () =>
      withAction(async () => {
        const nextTargets = pushTargetList(groupId).filter((_, itemIndex) => itemIndex !== index);
        updateGroupDraft(groupId, "push_targets", nextTargets);
        renderGroupEditor();
        return { message: "推送目标已从草稿删除，请保存更改" };
      }, "推送目标已从草稿删除，请保存更改", {
        reload: false,
        rerender: renderGroupEditor,
      }),
  });
}

async function saveGroupEdits(groupId) {
  const draft = state.groupDrafts[groupId];
  if (!draft) {
    return;
  }
  await withAction(async () => {
    const result = await apiPost("web/groups/update", draft);
    // API returns { success, group: {...} }; full list reloads via reloadAll.
    const savedId = String(
      result?.group?.group_id || result?.group_id || groupId,
    ).trim();
    state.selectedGroupId = savedId;
    delete state.groupDrafts[groupId];
    if (savedId && savedId !== groupId) {
      delete state.groupDrafts[savedId];
    }
    return result;
  }, "");
}

function confirmDeleteHistoryOrphan(groupId) {
  const value = String(groupId || "").trim();
  if (!value) return;
  openConfirm({
    kicker: "清理失效分组",
    title: `删除 ${value} 的运行数据？`,
    desc: "该 group_id 当前不在配置分组里。确认后会删除它的推送历史和防重复推送记录，不能恢复。",
    confirmText: "删除运行数据",
    action: () =>
      withAction(async () => {
        const result = await apiPost("web/history/orphans/delete", {
          group_id: value,
          confirm: "DELETE",
        });
        await detectHistoryOrphans();
        await loadHistory();
        return result;
      }, "失效分组运行数据已删除", {
        reload: false,
        rerender: () => {
          renderHistoryOrphans();
          renderHistory();
        },
      }),
  });
}

function replayHistory(recordId) {
  const record = (state.history?.records || []).find(
    (item) => String(item.id) === String(recordId),
  );
  const group = state.groups.find((item) => item.group_id === record?.group_id);
  const options = Array.isArray(record?.replay_target_options)
    ? record.replay_target_options
    : (group?.push_targets || []).map((target) => ({
        umo: target,
        historical: (record?.target_umos || []).includes(target),
        available: true,
      }));
  const desc = el("div", { className: "replay-target-panel" }, [
    el("p", {
      text: "选择要重新推送到的当前推送目标。历史旧目标只用于提示，不会自动使用。",
    }),
    el(
      "div",
      { className: "replay-target-list" },
      options.map((option, index) =>
        el("label", { className: `replay-target-option ${option.available ? "" : "disabled"}` }, [
          el("input", {
            attrs: {
              type: "checkbox",
              checked: option.available,
              disabled: !option.available,
            },
            dataset: { replayTarget: option.umo },
          }),
          el("span", { className: "mono-cell", text: option.umo }),
          el("small", {
            text: option.available
              ? option.historical
                ? "当前可用，历史已送达"
                : "当前可用"
              : "历史目标，当前配置未包含",
          }),
        ]),
      ),
    ),
  ]);
  openConfirm({
    kicker: "重新推送",
    title: "重新推送这条记录？",
    desc,
    confirmText: "重新推送",
    danger: false,
    action: () =>
      withAction(() => {
        const selectedTargets = [
          ...els.confirmDialog.querySelectorAll("[data-replay-target]:checked"),
        ].map((node) => node.dataset.replayTarget);
        if (!selectedTargets.length) {
          throw new Error("请选择至少一个推送目标");
        }
        return apiPost("web/history/replay", {
          record_id: recordId,
          target_umos: selectedTargets,
        });
      }, "重新推送完成"),
  });
  const updateReplayConfirmState = () => {
    const selectedCount = els.confirmDialog.querySelectorAll(
      "[data-replay-target]:checked",
    ).length;
    els.confirmActionBtn.disabled = selectedCount <= 0;
  };
  desc.addEventListener("change", (event) => {
    if (event.target.closest("[data-replay-target]")) {
      updateReplayConfirmState();
    }
  });
  updateReplayConfirmState();
}

function confirmDeleteGroup(groupId) {
  openConfirm({
    kicker: "删除分组",
    title: "删除这个分组？",
    desc: "会同时删除该分组的推送记录和运行数据，且无法恢复。",
    confirmText: "确认删除",
    action: () =>
      withAction(async () => {
        const result = await apiPost("web/groups/delete", {
          group_id: groupId,
          force: true,
          confirm: "DELETE",
        });
        state.selectedGroupId = "";
        return result;
      }, ""),
  });
}

function confirmDeleteSubscriptions(groupId = selectedGroupId()) {
  const entries = subscriptionEntriesValue();
  if (!entries) {
    showAlert("请填写要删除的关注账号", "error");
    return;
  }
  openConfirm({
    kicker: "删除关注账号",
    title: "删除关注账号？",
    desc: "只会从当前分组移除关注账号，不会删除推送目标或媒体文件。",
    confirmText: "删除",
    action: () =>
      withAction(async () => {
        const result = await apiPost("web/subscriptions/delete", {
          group_id: groupId,
          entries,
        });
        if (subscriptionEntriesInput()) {
          subscriptionEntriesInput().value = "";
        }
        return result;
      }),
  });
}

function confirmDeleteWatchUser(groupId, username) {
  if (!groupId || !username) return;
  openConfirm({
    kicker: "删除关注账号",
    title: `删除 ${username}？`,
    desc: "只会从当前分组移除这个关注账号，不会删除推送目标或媒体文件。",
    confirmText: "删除",
    action: () =>
      withAction(() =>
        apiPost("web/subscriptions/delete", {
          group_id: groupId,
          entries: username,
        }),
      ),
  });
}

async function importSubscriptions(groupId = selectedGroupId()) {
  const entries = subscriptionEntriesValue();
  if (!entries) {
    showAlert("请填写要导入的关注账号", "error");
    return;
  }
  await withAction(async () => {
    const result = await apiPost("web/subscriptions/import", {
      group_id: groupId,
      entries,
    });
    if (subscriptionEntriesInput()) {
      subscriptionEntriesInput().value = "";
    }
    return result;
  });
}

async function probeMirror(event) {
  event.preventDefault();
  state.actionBusy = true;
  setBusy(true);
  hideAlert();
  try {
    const mode = mirrorModeValue();
    const query = els.mirrorUsername.value.trim();
    const payload = {
      mode,
      limit: Number(els.mirrorLimit.value || 5),
      instance: els.mirrorInstance.value.trim(),
    };
    if (mode === "search") {
      payload.query = query;
    } else {
      payload.username = query;
    }
    const result = await apiPost("web/mirror/probe", payload);
    const tweets = (result.tweets || []).map((tweet) => {
      const link = externalLink(tweet.link, tweet.status_id || tweet.link || "");
      link.appendChild(el("span", { text: tweet.text_preview || "" }));
      return link;
    });
    const modeLabel =
      result.mode === "search"
        ? "搜索"
        : result.mode === "blogger_html"
          ? "博主 HTML"
          : "博主 RSS";
    const subject =
      result.mode === "search"
        ? result.query || result.subject || query
        : `@${result.username || query}`;
    const kindHint =
      result.mode === "search" && result.kind
        ? ` · ${result.kind === "tag" ? "标签" : "短语"}`
        : "";
    els.mirrorResult.replaceChildren(
      el("div", { className: "panel" }, [
        el("h2", {
          text: `${modeLabel}${kindHint} · ${subject} · ${result.instance}`,
        }),
        el("p", {
          className: "muted",
          text: `获取 ${formatNumber(result.tweet_count)} 条`,
        }),
        el("div", { className: "probe-list" }, tweets),
      ]),
    );
  } catch (error) {
    showAlert(error.message || "镜像测试失败", "error");
  } finally {
    state.actionBusy = false;
    setBusy(false);
  }
}

function confirmClearCache() {
  openConfirm({
    kicker: "缓存清理",
    title: "清理媒体缓存？",
    desc: "普通媒体缓存会被删除。",
    confirmText: "清理",
    action: () =>
      withAction(async () => {
        const result = await apiPost("web/cache/clear");
        const detail = result.result || {};
        const parts = [
          `已删除 ${formatNumber(detail.removed)} 个`,
          `图片 ${formatNumber(detail.removed_images)}`,
          `视频 ${formatNumber(detail.removed_videos)}`,
          `其他 ${formatNumber(detail.removed_other)}`,
          `空目录 ${formatNumber(detail.removed_empty_dirs)}`,
          `跳过目录 ${formatNumber(detail.skipped_dirs)}`,
          `失败 ${formatNumber(detail.failed)}`,
        ];
        els.cacheResult.textContent = parts.join("，");
        return result;
      }, "媒体缓存清理完成"),
  });
}

function confirmClearSeen() {
  const groupId = els.seenGroupSelect.value;
  const group = state.groups.find((item) => item.group_id === groupId);
  const scope = group?.name || "全部分组";
  openConfirm({
    kicker: "推送记录",
    title: "清理推送记录？",
    desc: `清理范围：${scope}。不会删除关注账号、推送目标或媒体文件，但旧推文可能重新参与检查。`,
    confirmText: "清理",
    action: () =>
      withAction(async () => {
        const result = await apiPost("web/seen/clear", {
          group_id: groupId,
          confirm: groupId ? "" : "CLEAR_ALL",
        });
        els.seenResult.textContent = `${scope}：删除 ${formatNumber(result.deleted)} 条`;
        return result;
      }, "推送记录清理完成"),
  });
}

function bindEvents() {
  document.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const link = event.target.closest("a[data-copy-link]");
    if (!link) return;
    event.preventDefault();
    const copied = await copyText(link.dataset.copyLink);
    showToast(copied ? "已复制原推文链接" : "复制失败，请手动复制链接");
  });
  els.tabs.forEach((tab) => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  });
  els.refreshBtn.addEventListener("click", refreshDashboard);
  els.createGroupBtn.addEventListener("click", createGroup);
  els.historyRefreshBtn.addEventListener("click", () =>
    withAction(() => {
      resetHistoryPage();
      return loadHistory();
    }, "最近推送已刷新", {
      reload: false,
      rerender: renderHistory,
      },
    ),
  );
  if (els.historyOrphanBtn) {
    els.historyOrphanBtn.addEventListener("click", () =>
      withAction(() => detectHistoryOrphans(), "失效分组检测完成", {
        reload: false,
        rerender: renderHistoryOrphans,
      }),
    );
  }
  els.historyGroupSelect.addEventListener("change", (event) => {
    state.historyGroupId = event.target.value;
    withAction(() => {
      resetHistoryPage();
      return loadHistory();
    }, "最近推送已刷新", {
      reload: false,
      rerender: renderHistory,
      },
    );
  });
  els.historyUsername.addEventListener("change", () =>
    withAction(() => {
      resetHistoryPage();
      return loadHistory();
    }, "最近推送已刷新", {
      reload: false,
      rerender: renderHistory,
      },
    ),
  );
  els.historyLimit.addEventListener("change", () =>
    withAction(() => {
      resetHistoryPage();
      return loadHistory();
    }, "最近推送已刷新", {
      reload: false,
      rerender: renderHistory,
      },
    ),
  );
  els.historyPrevBtn.addEventListener("click", () => {
    if (state.loading || state.actionBusy) return;
    withAction(
      () => loadHistoryPage(state.history?.prev_offset || 0),
      "最近推送已刷新",
      {
        reload: false,
        rerender: renderHistory,
      },
    );
  });
  els.historyNextBtn.addEventListener("click", () => {
    if (state.loading || state.actionBusy) return;
    withAction(
      () => loadHistoryPage(state.history?.next_offset || state.historyOffset),
      "最近推送已刷新",
      {
        reload: false,
        rerender: renderHistory,
      },
    );
  });
  els.historyContent.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (state.loading || state.actionBusy) return;
    if (target.dataset.replayHistory) replayHistory(target.dataset.replayHistory);
  });
  if (els.historyOrphanResult) {
    els.historyOrphanResult.addEventListener("click", (event) => {
      const target = event.target.closest("button");
      if (!target) return;
      if (state.loading || state.actionBusy) return;
      if (target.dataset.deleteHistoryOrphan) {
        confirmDeleteHistoryOrphan(target.dataset.deleteHistoryOrphan);
      }
    });
  }
  els.seenGroupSelect.addEventListener("change", (event) => {
    state.seenGroupId = event.target.value;
  });
  els.groupList.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (state.loading || state.actionBusy) return;
    if (target.dataset.groupSelect) selectGroup(target.dataset.groupSelect);
  });
  els.groupEditor.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (state.loading || state.actionBusy) return;
    if (target.dataset.checkGroup) runGroupCheck(target.dataset.checkGroup);
    if (target.dataset.addWatchQuery) {
      addWatchQuery(target.dataset.addWatchQuery);
      return;
    }
    if (target.dataset.deleteWatchQueryGroup != null) {
      deleteWatchQuery(
        target.dataset.deleteWatchQueryGroup,
        Number(target.dataset.deleteWatchQueryIndex || -1),
      );
      return;
    }
    if (target.dataset.saveGroup) saveGroupEdits(target.dataset.saveGroup);
    if (target.dataset.deleteGroup) confirmDeleteGroup(target.dataset.deleteGroup);
    if (target.dataset.importGroup) importSubscriptions(target.dataset.importGroup);
    if (target.dataset.addPushTarget) addPushTarget(target.dataset.addPushTarget);
    if (target.dataset.probePushTargets) probePushTargets(target.dataset.probePushTargets);
    if (target.dataset.deletePushTarget) {
      confirmDeletePushTarget(
        target.dataset.deletePushTargetGroup,
        target.dataset.deletePushTarget,
      );
    }
    if (target.dataset.deleteSubscriptions) {
      confirmDeleteSubscriptions(target.dataset.deleteSubscriptions);
    }
    if (target.dataset.deleteWatchUser) {
      confirmDeleteWatchUser(
        target.dataset.deleteWatchUserGroup,
        target.dataset.deleteWatchUser,
      );
    }
  });
  els.groupEditor.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (!target.dataset.groupField || !target.dataset.groupId) return;
    if (target.dataset.fieldType === "checkbox") {
      updateGroupDraft(
        target.dataset.groupId,
        target.dataset.groupField,
        target.checked,
      );
      return;
    }
    if (target.dataset.groupField === "daily_check_times") {
      updateGroupDraft(
        target.dataset.groupId,
        target.dataset.groupField,
        target.value
          .split(/[\n,，]+/)
          .map((item) => item.trim())
          .filter(Boolean),
      );
      return;
    }
    updateGroupDraft(
      target.dataset.groupId,
      target.dataset.groupField,
      target.value,
    );
  });
  els.groupEditor.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (
      target.dataset.groupField &&
      target.dataset.groupId &&
      target.dataset.fieldType === "checkbox"
    ) {
      updateGroupDraft(
        target.dataset.groupId,
        target.dataset.groupField,
        target.checked,
      );
      renderGroupEditor();
    }
  });
  els.mirrorForm.addEventListener("submit", probeMirror);
  if (els.mirrorMode) {
    els.mirrorMode.addEventListener("change", () => {
      if (els.mirrorInstance) els.mirrorInstance.value = "";
      renderMirrorBase();
    });
  }
  if (els.instanceList) {
    els.instanceList.addEventListener("click", (event) => {
      const target = event.target.closest("button");
      if (!target || !target.dataset.mirrorInstancePick) return;
      if (state.loading || state.actionBusy) return;
      if (els.mirrorInstance) {
        els.mirrorInstance.value = target.dataset.mirrorInstancePick;
      }
    });
  }
  els.clearCacheBtn.addEventListener("click", confirmClearCache);
  els.clearSeenBtn.addEventListener("click", confirmClearSeen);
  els.cancelConfirmBtn.addEventListener("click", closeConfirm);
  if (els.cancelConfirmBtnIcon) {
    els.cancelConfirmBtnIcon.addEventListener("click", closeConfirm);
  }
  if (els.themeToggleBtn) {
    els.themeToggleBtn.addEventListener("click", toggleTheme);
  }
  els.confirmDialog.addEventListener("click", (event) => {
    if (event.target === els.confirmDialog) closeConfirm();
  });
  els.confirmActionBtn.addEventListener("click", async () => {
    const action = state.pendingAction;
    closeConfirm();
    if (typeof action === "function") await action();
  });
  document.addEventListener("keydown", (event) => {
    trapConfirmFocus(event);
    if (event.key === "Escape" && !els.confirmDialog.hidden) closeConfirm();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!hasDirtyGroup()) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

initTheme();
mountIcons();
bindEvents();
reloadAll();
