'use strict';
/* Dashboard 分片（经典 script 按序加载）：Select / Confirm / Sheet / CmdK / 终端 / Theme
加载顺序见 index.html 与 core.js 头注。 */

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
/* 抽屉用途：分组编辑器要拦截「有未保存修改时关闭」，推文详情不需要 */
let sheetKind = "";

function openSheet({ title, body, footer = [], onClose = null, kind = "" }) {
  if (!els.detailSheet) return;
  if (!sheetOpen) state.sheetReturnFocus = document.activeElement;
  sheetOpen = true;
  sheetKind = kind;
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

/* 关闭抽屉。分组编辑器有未保存修改时先确认：点空白处/关闭按钮/Escape 都走这里，
   确认后丢弃草稿，取消则留在原地继续编辑。 */
function closeSheet({ restoreFocus = true, force = false } = {}) {
  if (!els.detailSheet || !sheetOpen) return;
  if (!force && sheetKind === "group" && sheetHasDraftChanges()) {
    openConfirm({
      title: "放弃未保存的修改？",
      desc: "当前分组有未保存的改动，关闭后这些修改将丢失。",
      confirmText: "放弃并关闭", danger: true,
      action: () => { discardGroupDraft(); closeSheet({ restoreFocus, force: true }); },
    });
    return;
  }
  sheetOpen = false;
  sheetKind = "";
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
  // 复用同一个 body 节点：轮询每 3 秒重渲染一次，整块替换会让用户翻看历史时
  // 被强制弹回底部。保留节点 + 只在“本来就贴着底部”时跟随新日志。
  let body = container.querySelector(".mac-terminal-body");
  const wasAtBottom = body
    ? body.scrollHeight - body.scrollTop - body.clientHeight < 24
    : true;

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
  const bar = h("div", { class: "mac-terminal-bar" }, [
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
  ]);

  if (body) {
    // 只换行内容，body 节点本身留着：滚动位置与用户的选择都不会被重置
    body.replaceChildren(...(lines.length ? lines : [h("div", { class: "term-empty", text: empty })]));
  } else {
    body = h("div", { class: "mac-terminal-body" }, lines.length ? lines : [h("div", { class: "term-empty", text: empty })]);
  }
  container.replaceChildren(bar, body);
  // 只有本来就在底部才跟随新日志；用户往上翻看时保持原位
  if (wasAtBottom) body.scrollTop = body.scrollHeight;
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

/* 在途守卫：轮询与「进入视图时的 reset 拉取」可能重叠，两次请求会拿到同一批
   seq 各自 concat，同一批日志在终端里出现两遍（接口慢于 3s 轮询间隔即可复现）。
   reset 请求优先：它清空后重拉，普通增量请求直接让位。 */
let logsInFlight = null;
let logsResetPending = false;

async function reloadLogs({ reset = false } = {}) {
  if (reset) {
    logsResetPending = true;
    // 让在途的增量请求失效，避免它把旧数据写回刚清空的 state
    state.logs = [];
    state.logsAfterSeq = 0;
  } else if (logsInFlight || logsResetPending) {
    return;   // 已有请求在途，本轮跳过；下一次轮询自然会补上
  }

  const request = (async () => {
    const res = await apiGet("web/logs", { after_seq: state.logsAfterSeq || undefined });
    const incoming = res.entries || [];
    state.logsMax = res.max_entries || state.logsMax;
    if (incoming.length) {
      // 按 seq 去重：即便守卫失效（例如 reset 与增量交错），也不会重复追加
      const seen = new Set(state.logs.map(e => e.seq));
      const fresh = incoming.filter(e => !seen.has(e.seq));
      if (fresh.length) {
        state.logs = state.logs.concat(fresh);
        state.logsAfterSeq = fresh[fresh.length - 1].seq;
      }
      // 前端与后端同上限，避免长时间停留后无限增长
      if (state.logsMax && state.logs.length > state.logsMax) {
        state.logs = state.logs.slice(-state.logsMax);
      }
    }
    markData("logs");
  })();

  logsInFlight = request;
  try {
    await request;
  } finally {
    if (logsInFlight === request) logsInFlight = null;
    if (reset) logsResetPending = false;
  }
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

