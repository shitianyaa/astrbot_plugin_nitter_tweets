'use strict';
/* Dashboard 分片（经典 script 按序加载）：Cleanup / Entry / boot / 事件绑定
加载顺序见 index.html 与 core.js 头注。 */

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

/* 存储运维页只有「重置推送记录」一个入口，作用域就是全部分组。
   早先还去读一个页面里已不存在的 #seenSelect，gid 恒为空串，等价于全量重置
   却按「分组重置」的文案走——这里把语义写死，避免再出现这种静默扩大范围。 */
function confirmClearSeen() {
  openConfirm({
    title: "重置全部推送记录？",
    desc: "重置后下次检查可能将当前推文视为未推送，可能导致重复发送。",
    danger: true, confirmText: "确认重置",
    action: () => withAction(
      () => apiPost("web/seen/clear", { confirm: "CLEAR_ALL" }),
      "推送记录已重置",
    ),
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
  // 切页时按视图重新取数：此前只有视图被标脏才刷新，别处（调度器、另一个
  // 浏览器标签）产生的新数据要等手动点「刷新数据」才出现。只取当前视图
  // 需要的数据，保留已有内容渲染（stale-while-revalidate），不闪空屏。
  refreshOnEnter(v);
  // 诊断终端只在实例诊断视图可见时轮询，切走即停
  if (v === "mirror") {
    reloadLogs({ reset: true }).catch(() => {});
    startLogPolling();
  } else {
    stopLogPolling();
  }
}

/* 视图进入时的取数策略：草稿跨刷新保留（配置控件优先读 draft，分组抽屉由
   refreshGroupSheet 原位重建），所以重取不会冲掉未保存的编辑。分组的脏检查
   只用来避免编辑期间抽屉内容被外部数据打断。 */
const VIEW_ENTER_TTL = 15_000;
const viewEnteredAt = new Map();

function refreshOnEnter(view) {
  if (view === "groups" && state.groups.some(g => isGroupDirty(g.group_id))) return;
  const now = Date.now();
  if (now - (viewEnteredAt.get(view) || 0) < VIEW_ENTER_TTL) return;
  viewEnteredAt.set(view, now);
  refreshViewData(view).catch(() => {});
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

  const applyHistoryFilters = async () => {
    state.historyGroupId = els.historyGroupSelect.value;
    state.historyUsername = els.historyUsername.value.trim();
    state.historyLimit = parseInt(els.historyLimit.value, 10) || 20;
    state.historyStatus = els.historyStatusSelect ? els.historyStatusSelect.value : "";
    state.historySelection.clear();
    state.historyOffset = 0; // 重置页码
    await withAction(() => refreshHistoryData(), false, { reload: false });
  };
  els.historyRefreshBtn?.addEventListener("click", applyHistoryFilters);
  // 下拉与条数改变即刻查询：此前只有点「筛选」才生效，看起来像切换后没刷新
  els.historyGroupSelect?.onChange?.(() => { applyHistoryFilters(); });
  els.historyStatusSelect?.onChange?.(() => { applyHistoryFilters(); });
  els.historyLimit?.addEventListener("change", applyHistoryFilters);
  els.historyUsername?.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); applyHistoryFilters(); }
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
    // 历史页两个筛选框用自绘下拉（与分组抽屉里的 .dd 保持同一观感）；
    // 其余位置仍用原生 select + 自绘 SVG 箭头。
    upgradeHistorySelects();
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
