'use strict';
/* Dashboard 分片（经典 script 按序加载）：分组列表 / 编辑器 / 草稿 / 订阅源 / 推送目标 / 黑名单
加载顺序见 index.html 与 core.js 头注。 */

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

/* 输入校验就地反馈：输入框轻微抖动红边，就地错误提示淡入，不向全局通知栈发射打扰弹窗 */
function flashInputError(input, errNode, message) {
  if (input) {
    input.classList.remove("input-error");
    void input.offsetWidth;
    input.classList.add("input-error");
    input.addEventListener("input", () => input.classList.remove("input-error"), { once: true });
  }
  if (errNode) {
    if (message) errNode.textContent = message;
    errNode.style.display = "";
  }
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
  return snapJson !== draftJson(d) || hasPendingBlacklist(groupId);
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
  // 抽屉里的控件只改草稿：页脚保存按钮要立刻从「已保存」变成可点的「保存」
  if (groupId === state.selectedGroupId) refreshSheetSaveState();
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
        delete state.pendingBlacklists[prev.group_id];
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
/* 分组编辑器是"本地草稿 + 显式保存"：所有控件只改 draft 并就地刷新，
   页脚「保存」一次性提交。删除类操作仍然弹确认框询问（移除订阅源/推送目标/
   黑名单），保存类不再逐次弹窗打断。 */
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
      }),
    ]),
    h("div", { class: "editor-grid" }, [
      toggleRow(d.enabled, "启用此分组", v => updateDraft(gid, "enabled", v)),
      toggleRow(d.interval_check_enabled, "开启定时循环间隔检查", v => updateDraft(gid, "interval_check_enabled", v)),
      toggleRow(d.filter_reposts_enabled, "过滤转发（需同时开启全局转发过滤总开关）", v => updateDraft(gid, "filter_reposts_enabled", v)),
      toggleRow(d.filter_plain_text_enabled, "过滤纯文本（仅有媒体推文才推送）", v => updateDraft(gid, "filter_plain_text_enabled", v)),
      toggleRow(d.media_only_enabled, "仅保留含媒体推文（图片/视频）", v => updateDraft(gid, "media_only_enabled", v)),
      toggleRow(d.omit_status_url, "省略原推链接", v => updateDraft(gid, "omit_status_url", v)),
      toggleRow(d.hide_original_when_translated, "翻译后隐藏原文", v => updateDraft(gid, "hide_original_when_translated", v)),
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
      }),
      h("span", { id: "dailyTimesHint", class: "field-error", style: { display: "none" } }),
    ]),
    // 订阅源：完整能力（chips / 无效隔离 / 批量导入 / 添加）
    // data-editor-section 供 refreshGroupSheet 在保存后原位重建
    h("div", { "data-editor-section": "entities" }, renderEntities(g, d)),
    // 推送目标：data-editor-section 供 rerenderTargetsSection 局部重建
    h("div", { "data-editor-section": "targets" }, renderTargets(g, d)),
  ]);

  const footer = [
    h("span", { class: "mono hint", text: g.group_id }),
    g.group_id !== "default"
      ? h("button", { class: "btn btn-sm btn-danger", type: "button", text: "删除分组", onClick: () => { closeSheet({ force: true }); confirmDeleteGroup(gid); } })
      : null,
    h("button", { class: "btn btn-sm", type: "button", text: "关闭", onClick: () => closeSheet() }),
    h("button", {
      class: "btn btn-sm btn-primary", type: "button", text: "保存",
      "data-sheet-save": "true",
      onClick: () => saveGroup(gid, "分组已保存"),
    }),
  ];

  openSheet({ title: `编辑分组 · ${d.name || g.name}`, body, footer, kind: "group" });
  refreshSheetSaveState();
}

/* 抽屉是否有未保存改动：与卡片上的「未保存」徽标同一口径（isGroupDirty） */
function sheetHasDraftChanges() {
  const gid = state.selectedGroupId;
  return !!gid && isGroupDirty(gid);
}

/* 丢弃当前分组草稿，回到服务器快照 */
function discardGroupDraft() {
  const gid = state.selectedGroupId;
  const g = state.groups.find(x => x.group_id === gid);
  if (!g) return;
  state.groupDrafts[gid] = snapshotGroup(g);
  delete state.targetProbeResults[gid];
  delete state.pendingBlacklists[gid];
  markData("groups");
  refreshGroupSheet(gid);
}

/* 页脚保存按钮与抽屉标题跟随草稿状态：有改动时按钮高亮并显示「保存」，
   无改动时置灰为「已保存」，避免用户反复点保存却看不出结果。 */
function refreshSheetSaveState() {
  const btn = els.sheetFooter?.querySelector("[data-sheet-save]");
  if (!btn) return;
  const dirty = sheetHasDraftChanges();
  btn.disabled = !dirty || state.actionBusy;
  btn.textContent = dirty ? "保存" : "已保存";
  const gid = state.selectedGroupId;
  const g = state.groups.find(x => x.group_id === gid);
  const d = state.groupDrafts[gid];
  if (els.sheetTitle && g) {
    els.sheetTitle.textContent = `编辑分组 · ${(d && d.name) || g.name}`;
  }
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

/* 抽屉原位刷新：chips 的移除按钮闭包捕获的是渲染时的下标，抽屉不跟着 draft
   重建就会按旧下标删错条目，用户也必须关掉抽屉重开才能看到结果。
   只重建 entities/targets 两个数据分区，标题与开关保持原节点（不打断焦点与输入法）。 */
function refreshGroupSheet(gid) {
  if (!sheetOpen || gid !== state.selectedGroupId) return;
  const g = state.groups.find(x => x.group_id === gid);
  const d = g ? (state.groupDrafts[g.group_id] || snapshotGroup(g)) : null;
  if (!g || !d) return;
  const entities = els.sheetBody?.querySelector('[data-editor-section="entities"]');
  if (entities) entities.replaceChildren(renderEntities(g, d));
  rerenderTargetsSection(gid);
  if (els.sheetTitle) els.sheetTitle.textContent = `编辑分组 · ${d.name || g.name}`;
  refreshSheetSaveState();
}

/* 添加类操作后的 chips 原位重绘：只动 chip 区，不重建分区（输入框在容器外，
   连续录入时焦点不丢）。removeChildren/replaceWith 语义见 renderEntityChips 尾部。 */
function rerenderEntityChips(gid) {
  const g = state.groups.find(x => x.group_id === gid);
  const d = g ? (state.groupDrafts[gid] || snapshotGroup(g)) : null;
  if (!g || !d) return;
  const container = els.sheetBody?.querySelector('[data-entity-chips="true"]');
  if (container) renderEntityChips(container, g, d);
}

function rerenderTargetChips(gid) {
  const g = state.groups.find(x => x.group_id === gid);
  const d = g ? (state.groupDrafts[gid] || snapshotGroup(g)) : null;
  if (!g || !d) return;
  const container = els.sheetBody?.querySelector('[data-target-chips="true"]');
  if (container) container.replaceWith(renderTargetChips(g, d, state.targetProbeResults[gid]));
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
  // 按值删除而不是按渲染时下标：确认弹窗挂着时 draft 可能已被别的动作改过，
  // 下标会指向另一条订阅源，静默删错。
  const entityValue = item => (item && typeof item === "object" ? item.query : item);
  const nodes = (draft[field] || []).map(item => {
    const val = entityValue(item);
    return h("span", { class: "chip mono" }, [
      iconEl(icon, 12), val,
      h("button", { class: "btn-icon chip-remove", title: "移除", "aria-label": `移除 ${val}`, html: svgIcon("close", 12), onClick: () => {
        if (state.actionBusy) return;
        confirmGroupMutation(group.group_id, {
          title: "移除订阅源？",
          desc: `将从草稿中移除 ${val}，点击抽屉底部的「保存」后生效。`,
          confirmText: "移除",
          danger: true,
          successText: false,
          mutate: () => {
            const current = state.groupDrafts[group.group_id]?.[field] || [];
            updateDraft(group.group_id, field, current.filter(x => entityValue(x) !== val));
          },
        });
      }}),
    ]);
  });
  // 无效订阅源（仅博主分组的 watch_users 有隔离区）：可见、可显式移除
  if (!isTag && !isList) {
    (draft.invalid_watch_users || []).forEach(val => {
      nodes.push(h("span", { class: "chip chip-invalid mono", title: val }, [
        iconEl(icon, 12), val,
        h("span", { class: "badge badge-danger", text: "无效" }),
        h("button", { class: "btn-icon chip-remove", title: "移除", "aria-label": `移除 ${val}`, html: svgIcon("close", 12), onClick: () => {
          if (state.actionBusy) return;
          confirmGroupMutation(group.group_id, {
            title: "移除无效订阅源？",
            desc: `将从草稿中移除 ${val}，点击抽屉底部的「保存」后生效。`,
            confirmText: "移除",
            danger: true,
            successText: false,
            mutate: () => {
              const current = state.groupDrafts[group.group_id]?.invalid_watch_users || [];
              updateDraft(group.group_id, "invalid_watch_users", current.filter(x => x !== val));
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
          if (existing) {
            flashInputError(inp, document.getElementById("entityError"), "订阅源已存在");
            return;
          }
          // 添加是纯增量操作：只写草稿，用户点「保存」时统一提交
          const current = state.groupDrafts[group.group_id]?.[field] || [];
          updateDraft(group.group_id, field, [...current, isTag ? { query: v, type: "tag" } : v]);
          if (inp) inp.value = "";
          rerenderEntityChips(group.group_id);
        }
      }}),
    ]),
    h("span", { id: "entityError", class: "field-error", style: { display: "none" } }),
    (!isTag && !isList) ? renderBulkSubscriptions(group) : null,
  ]);
}

function renderBulkSubscriptions(group) {
  const area = h("textarea", { rows: 3, class: "ta-full", placeholder: "每行一个用户名，也可用逗号分隔" });
  const run = mode => {
    if (state.actionBusy) return;
    const entries = area.value.split(/[\n,，]+/).map(s => s.trim()).filter(Boolean);
    if (!entries.length) {
      flashInputError(area, null, "");
      showAlert("请先填写用户名", "warn");
      return;
    }
    // 草稿语义：批量增删与单个添加同权，页脚「保存」才落库（保存后由后端
    // 分组解析隔离无效条目），这里不发通知、不直接调接口
    const apply = () => {
      const d = state.groupDrafts[group.group_id]; if (!d) return;
      if (mode === "import") {
        const known = new Set([...(d.watch_users || []), ...(d.invalid_watch_users || [])]);
        const fresh = entries.filter(v => !known.has(v));
        updateDraft(group.group_id, "watch_users", [...(d.watch_users || []), ...fresh]);
      } else {
        const drop = new Set(entries);
        updateDraft(group.group_id, "watch_users", (d.watch_users || []).filter(v => !drop.has(v)));
        updateDraft(group.group_id, "invalid_watch_users", (d.invalid_watch_users || []).filter(v => !drop.has(v)));
      }
      rerenderEntityChips(group.group_id);
      area.value = "";
    };
    if (mode === "import") { apply(); return; }
    openConfirm({
      title: "确认从草稿移除订阅？",
      desc: `共 ${entries.length} 个用户名，保存后生效；未保存前可随时放弃更改恢复。`,
      confirmText: "移除",
      danger: true,
      action: apply,
    });
  };
  return h("div", { class: "subsection" }, [
    h("span", { class: "section-head", text: "批量导入 / 移除" }),
    area,
    h("div", { class: "input-action-row" }, [
      h("button", { class: "btn btn-sm", "data-busy-control": "true", text: "导入", onClick: () => run("import") }),
      h("button", { class: "btn btn-sm", "data-busy-control": "true", text: "移除", onClick: () => run("remove") }),
    ]),
  ]);
}

/* 推送目标 chips 独立成节点并带 data-target-chips 标记：添加类操作后
   rerenderTargetChips 用 replaceWith 原位替换这一块，其余控件不动。 */
function renderTargetChips(group, draft, probe) {
  const targets = draft.push_targets || [];
  return h("div", { class: "chip-list", "data-target-chips": "true" },
    targets.map(t => {
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
            desc: `将从草稿中移除 ${t}，点击抽屉底部的「保存」后生效。`,
            confirmText: "移除",
            danger: true,
            successText: false,
            mutate: () => {
              const current = state.groupDrafts[group.group_id]?.push_targets || [];
              updateDraft(group.group_id, "push_targets", current.filter(x => x !== t));
            },
          });
        }}),
      ]);
    })
  );
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
    renderTargetChips(group, draft, probe),
    renderInvalidTargets(group, draft, probe),
    h("div", { class: "input-action-row" }, [
      h("input", {
        id: "newTargetInput", type: "text", placeholder: "aiocqhttp:GroupMessage:123456",
        onInput: () => { const err = document.getElementById("targetError"); if (err) err.style.display = "none"; },
      }),
      h("button", { class: "btn btn-sm", html: svgIcon("plus", 14), text: "添加", onClick: () => {
        const inp = document.getElementById("newTargetInput");
        const v = inp?.value.trim(); if (!v) return;
        if (state.actionBusy) return;
        // 免确认路径用实时 draft 查重，避免保存失败重试时重复追加
        const live = state.groupDrafts[group.group_id] || draft;
        const known = new Set([...(live.push_targets || []), ...(live.invalid_push_targets || [])]);
        if (known.has(v)) {
          flashInputError(inp, document.getElementById("targetError"), "推送目标已存在");
          return;
        }
        // 纯增量可逆操作：只写草稿，点页脚「保存」时统一提交
        updateDraft(group.group_id, "push_targets", [...(live.push_targets || []), v]);
        if (inp) inp.value = "";
        rerenderTargetChips(group.group_id);
      }}),
    ]),
    h("span", { id: "targetError", class: "field-error", style: { display: "none" } }),
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
      invalid.map(t => h("span", { class: "chip chip-invalid", title: t }, [
        h("span", { text: t }),
        probe?.targets?.find(x => x.umo === t.trim()) ? h("span", { class: "badge badge-danger", text: "无效" }) : null,
        h("button", { class: "btn-icon chip-remove", title: "移除", "aria-label": `移除 ${t}`, html: svgIcon("close", 12), onClick: () => {
          if (state.actionBusy) return;
          confirmGroupMutation(group.group_id, {
            title: "移除无效推送目标？",
            desc: `将从草稿中移除 ${t}，点击抽屉底部的「保存」后生效。`,
            confirmText: "移除",
            danger: true,
            successText: false,
            mutate: () => {
              const current = state.groupDrafts[group.group_id]?.invalid_push_targets || [];
              updateDraft(group.group_id, "invalid_push_targets", current.filter(x => x !== t));
            },
          });
        }}),
      ]))
    ),
  ]);
}

/* 黑名单草稿（pending）：服务器名单 + 待增/待删合并出生效视图，页脚「保存」
   时随分组一起落库。加入/移除只动 pending，不发通知。 */
function pendingBlacklistFor(gid, target) {
  const rec = state.pendingBlacklists[gid];
  return rec ? rec[target] : null;
}

function ensurePendingBlacklist(gid, target) {
  if (!state.pendingBlacklists[gid]) state.pendingBlacklists[gid] = {};
  if (!state.pendingBlacklists[gid][target]) {
    state.pendingBlacklists[gid][target] = { adds: [], removes: [] };
  }
  return state.pendingBlacklists[gid][target];
}

function hasPendingBlacklist(gid) {
  const rec = state.pendingBlacklists[gid];
  return !!rec && Object.values(rec).some(p => p.adds.length || p.removes.length);
}

function renderBlacklistChips(group, target, serverUsers) {
  const gid = group.group_id;
  const p = pendingBlacklistFor(gid, target);
  const adds = p ? p.adds : [];
  const removes = new Set(p ? p.removes : []);
  const chip = (u, state_) => {
    const pendingAdd = state_ === "pending-add";
    const removing = state_ === "removing";
    return h("span", { class: `chip mono${removing ? " chip-removing" : ""}`, title: removing ? "保存后移除" : u }, [
      `@${u}`,
      pendingAdd ? h("span", { class: "badge badge-warn", text: "待保存" }) : null,
      h("button", {
        class: "btn-icon chip-remove",
        title: removing ? "撤销移除" : pendingAdd ? "撤销添加" : "移除",
        "aria-label": `${removing ? "撤销移除" : "移除"} ${u}`,
        html: svgIcon("close", 12),
        onClick: () => {
          if (state.actionBusy) return;
          const rec = ensurePendingBlacklist(gid, target);
          if (removing) { rec.removes = rec.removes.filter(x => x !== u); }
          else if (pendingAdd) { rec.adds = rec.adds.filter(x => x !== u); }
          else {
            confirmGroupMutation(gid, {
              title: "移除黑名单用户？",
              desc: `@${u} 将从草稿中移除，点击抽屉底部的「保存」后生效。`,
              confirmText: "移除", danger: true, successText: false,
              mutate: () => { ensurePendingBlacklist(gid, target).removes.push(u); scheduleGroupListRender(); },
            });
            return;
          }
          rerenderBlacklistChips(gid, target, serverUsers);
          refreshSheetSaveState();
        },
      }),
    ]);
  };
  const nodes = [
    ...serverUsers.map(u => chip(u, removes.has(u) ? "removing" : "normal")),
    ...adds.map(u => chip(u, "pending-add")),
  ];
  return h("div", { class: "chip-list", "data-blacklist-chips": "true" },
    nodes.length ? nodes : [h("span", { class: "hint-subtle", text: "黑名单为空" })]);
}

function rerenderBlacklistChips(gid, target, serverUsers) {
  scheduleGroupListRender();   // pending 变化影响卡片「未保存」徽标
  const container = els.sheetBody?.querySelector('[data-blacklist-chips="true"]');
  if (container) container.replaceWith(renderBlacklistChips({ group_id: gid }, target, serverUsers));
}

function renderTargetBlacklist(group, draft) {
  const gid = group.group_id;
  const targets = draft.push_targets || [];
  const rows = Array.isArray(state.targetBlacklists) ? state.targetBlacklists : [];
  if (!targets.includes(state.targetBlacklistTarget)) state.targetBlacklistTarget = targets[0] || "";
  const selected = state.targetBlacklistTarget;
  const serverUsers = [...((rows.find(r => r.target_umo === selected) || {}).blocked_users || [])];
  const box = h("div", { class: "subsection" }, [
    h("div", { class: "section-head" }, [
      iconEl("ban", 16), "目标作者黑名单",
      h("span", { class: "hint", text: "跨分组共享，仅影响后台推送；改动随「保存」落库" }),
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
  select.onChange(v => { state.targetBlacklistTarget = v; rerenderTargetsSection(gid); });
  const errSpan = h("span", { class: "field-error", style: { display: "none" } });
  const input = h("input", {
    type: "text", placeholder: "用户名或 @用户名",
    onInput: () => { if (errSpan) errSpan.style.display = "none"; },
  });
  box.append(
    h("div", { class: "input-action-row" }, [
      select, input,
      h("button", { class: "btn btn-sm", html: svgIcon("plus", 14), text: "加入", onClick: () => {
        const v = input.value.trim();
        if (!v) return;
        const uname = v.replace(/^@+/, "");
        const removes = new Set(pendingBlacklistFor(gid, selected)?.removes || []);
        const known = new Set([...serverUsers, ...(pendingBlacklistFor(gid, selected)?.adds || [])]);
        if (known.has(uname) && !removes.has(uname)) {
          flashInputError(input, errSpan, "用户名已在黑名单");
          return;
        }
        ensurePendingBlacklist(gid, selected).adds.push(uname);
        input.value = "";
        rerenderBlacklistChips(gid, selected, serverUsers);
        refreshSheetSaveState();
      }}),
    ]),
    errSpan,
    renderBlacklistChips(group, selected, serverUsers),
  );
  return box;
}

/* 页脚保存的收尾步骤：把该分组抽屉里累计的黑名单增删按 target 合并落库。
   任一 target 失败即抛错（withAction 统一提示），pending 保留供重试。 */
async function flushPendingBlacklists(gid) {
  const rec = state.pendingBlacklists[gid];
  if (!rec) return;
  for (const [target, p] of Object.entries(rec)) {
    if (!p.adds.length && !p.removes.length) continue;
    const serverUsers = [...((state.targetBlacklists.find(r => r.target_umo === target) || {}).blocked_users || [])];
    const removes = new Set(p.removes);
    const merged = [...serverUsers.filter(u => !removes.has(u)), ...p.adds];
    await apiPost("web/target-blacklists/update", { target_umo: target, blocked_users: merged });
    const rest = state.targetBlacklists.filter(r => r.target_umo !== target);
    if (merged.length) rest.push({ target_umo: target, blocked_users: merged });
    state.targetBlacklists = rest.sort((a, b) => a.target_umo.localeCompare(b.target_umo));
  }
  delete state.pendingBlacklists[gid];
}

function addWatchList(groupId) {
  const inp = document.getElementById("newWatchListInput");
  const err = document.getElementById("entityError");
  const showError = msg => {
    if (err) { err.textContent = msg; err.style.display = ""; }
    else showAlert(msg, "warn");
    if (inp) flashInputError(inp);
  };
  const val = inp?.value.trim(); if (!val) return;
  if (!/^\d{1,20}$/.test(val)) { showError("List ID 必须是 1-20 位正整数"); return; }
  const d = state.groupDrafts[groupId]; if (!d) return;
  if ((d.watch_lists || []).includes(val)) { showError("List ID 已存在"); return; }
  if (err) err.style.display = "none";
  // 纯增量操作：只写草稿，点页脚「保存」时统一提交
  updateDraft(groupId, "watch_lists", [...(d.watch_lists || []), val]);
  if (inp) inp.value = "";
  rerenderEntityChips(groupId);
}

/* --------------------------------------------------------------------------
   Group Actions
   -------------------------------------------------------------------------- */
/* 删除类操作（移除订阅源/推送目标/黑名单用户）走确认框，确认后只改草稿并就地
   刷新抽屉，真正落盘由页脚「保存」统一完成。 */
function confirmGroupMutation(gid, { title, desc, confirmText, danger = false, successText = false, mutate }) {
  openConfirm({
    title,
    desc,
    confirmText,
    danger,
    action: async () => {
      mutate();
      refreshGroupSheet(gid);
      if (successText) showAlert(successText);
    },
  });
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
    // 黑名单增删随本次保存落库；失败则抛错走统一提示，pending 保留可重试
    await flushPendingBlacklists(gid);
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
  }, successText, {
    reload: false,
    rerender: () => {
      markData("groups");
      markData("overview");
      // 抽屉仍开着就原位重建分区并复位保存按钮（草稿已清空 →「已保存」置灰）。
      // 用局部刷新而不是 openGroupSheet：整棵重建会把抽屉滚回顶部、丢掉焦点。
      if (sheetOpen && gid === state.selectedGroupId) {
        refreshGroupSheet(gid);
        refreshSheetSaveState();
      }
    },
  });
}

function confirmDeleteGroup(gid) {
  openConfirm({
    title: `删除分组 [${gid}]？`,
    desc: "此操作不可恢复，订阅规则与历史关联将被清理。",
    danger: true,
    action: () => withAction(async () => {
      await apiPost("web/groups/delete", { group_id: gid, force: true, confirm: "DELETE" });
      delete state.targetProbeResults[gid];
      delete state.pendingBlacklists[gid];
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

