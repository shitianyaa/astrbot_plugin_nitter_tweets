'use strict';
/* Dashboard 分片（经典 script 按序加载）：Rail / Overview / History / Mirror / Storage
加载顺序见 index.html 与 core.js 头注。 */

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
  // 数据来自 refreshRecentPushes（全局最新 5 条），不是历史页快照
  const records = state.recentPushes;
  const recentSection = h("section", {}, [
    h("div", { class: "section-header", style: { marginTop: "28px" } }, [
      h("div", {}, [
        h("h3", { text: `最新推送记录（前 ${records.length || RECENT_PUSH_LIMIT} 条）` }),
        h("div", { class: "section-sub", text: "点击任意记录可在右侧抽屉查看详情" }),
      ]),
      h("button", {
        class: "nav-btn",
        type: "button",
        text: `查看完整 ${stats?.total ?? state.history?.total_count ?? 0} 条记录 →`,
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
/* 历史页筛选下拉：把 index.html 里的占位 span 换成自绘下拉。
   原生 select 的展开层由系统绘制（圆角、选中色、字体全不可控），与抽屉里的
   自绘 .dd 并存时观感割裂；这里统一走 createSelect，els 引用改指新节点。 */
const HISTORY_STATUS_OPTIONS = [
  { value: "", text: "全部状态" },
  { value: "success", text: "发送成功" },
  { value: "partial_failed", text: "部分失败" },
  { value: "failed", text: "发送失败" },
];

function upgradeHistorySelects() {
  const mount = (slotId, opts) => {
    const slot = els[slotId];
    if (!slot || slot.classList?.contains("dd")) return;
    // id 必须带到新节点上：CSS/测试与宿主排查都按 #historyGroupSelect 定位
    const dd = createSelect({ id: slotId, options: opts });
    dd.classList.add("dd-filter");
    // 原生 select 的 aria-label 随节点一起没了，从占位上的 data-label 还原
    const label = slot.dataset?.label;
    if (label) dd.querySelector(".dd-trigger")?.setAttribute("aria-label", label);
    slot.replaceWith(dd);
    els[slotId] = dd;
  };
  mount("historyGroupSelect", [{ value: "", text: "全部分组" }]);
  mount("historyStatusSelect", HISTORY_STATUS_OPTIONS);
}

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
  // 总览与历史页各有自己的快照：总览读 recentPushes，历史页读 history.records，
  // 两处都可能点开同一条。只查 history 会让总览的行因历史页翻页/筛选而静默失效。
  const r = ((state.history && state.history.records) || []).find(x => x.id === recordId)
    || state.recentPushes.find(x => x.id === recordId);
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
          showAlert(`分组「${sec.name}」未选择目标，已取消批量重推`, "warn");
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
      if (!umos.length) { showAlert("未选择目标，已取消重推", "warn"); return undefined; }
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
  const card = host.querySelector(".inst-card-large:not(.empty-note)");
  const parent = card || host;
  // 复用已有终端节点：轮询每 3 秒走一次这里，整块 remove + 重建会把用户的
  // 滚动位置和选中文本一起丢掉（renderTerminal 内部的滚动保持也就失效了）。
  let term = parent.querySelector(":scope > .mirror-terminal");
  if (!term) {
    term = h("div", { class: "mac-terminal mirror-terminal" });
    parent.appendChild(term);
  }
  // 终端跟着结果卡走：探测结果重建后旧卡已从 DOM 移除，把终端迁到新卡上
  host.querySelectorAll(".mirror-terminal").forEach(el => {
    if (el !== term && !parent.contains(el)) el.remove();
  });

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
    showAlert("请至少填写一项测试目标（用户名、搜索标签或关键词、List ID）", "warn");
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


