'use strict';
/* Dashboard 分片（经典 script 按序加载）：Plugin Config V2
加载顺序见 index.html 与 core.js 头注。 */

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

/* 搜索命中判定：描述 / 键名 / 说明文字都参与匹配。分组名也参与，用户搜
   "翻译"时 AI 翻译组即使没有单个字段命中，也要能在导航里定位到。 */
function configItemMatches(item, q) {
  if (!q) return true;
  return (item.description || "").toLowerCase().includes(q)
    || item.key.toLowerCase().includes(q)
    || (item.hint || "").toLowerCase().includes(q);
}

function configGroupMatches(group, q) {
  if (!q) return true;
  if ((group.name || "").toLowerCase().includes(q)) return true;
  return (group.items || []).some(i => configItemMatches(i, q));
}

function configItemsOf(group) {
  const q = state.configSearch.trim().toLowerCase();
  if (!q) return group.items;
  return group.items.filter(i => configItemMatches(i, q));
}

/* 搜索时该停在哪个分组：默认落在命中字段最多的分组（搜"翻译"应去 AI 翻译，
   而不是碰巧有一条说明命中的基础设置）。用户手动点过导航后不再自动跳，
   否则想看 0 命中分组时会被弹回去。字段全 0 命中时退回按分组名命中的分组。 */
function pickConfigGroupForSearch(groups, currentKey, q) {
  const current = groups.find(g => g.key === currentKey);
  if (state.configSearchPinned && current) return current;
  let best = null;
  let bestHits = 0;
  for (const g of groups) {
    const hits = configItemsOf(g).length;
    if (hits > bestHits) { best = g; bestHits = hits; }
  }
  return best || groups.find(g => configGroupMatches(g, q)) || current || groups[0];
}

/* 搜索态下导航顺序：命中的分组按命中数降序排在前面，0 命中的保持原相对顺序垫后 */
function configGroupsForNav(groups, q) {
  if (!q) return groups;
  const hit = groups.filter(g => configItemsOf(g).length > 0)
    .sort((a, b) => configItemsOf(b).length - configItemsOf(a).length);
  const named = groups.filter(g => !hit.includes(g) && configGroupMatches(g, q));
  const rest = groups.filter(g => !hit.includes(g) && !named.includes(g));
  return [...hit, ...named, ...rest];
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
  // 搜索结果散落在多个分组时，落在命中最多的那一组：搜"翻译"时基础设置可能
  // 只有 1 条说明里带这个词，AI 翻译有 7 条，停在基础设置会被当成搜错了。
  const searchQuery = state.configSearch.trim().toLowerCase();
  if (!searchQuery) state.configSearchPinned = false;
  else state.configActive = pickConfigGroupForSearch(groups, state.configActive, searchQuery).key;
  const active = groups.find(g => g.key === state.configActive);

  // 左:分组导航
  const nav = h("div", { class: "panel config-nav" }, [
    h("div", { class: "panel-head" }, [h("h3", { text: "配置分组" })]),
    h("input", {
      type: "text", placeholder: "搜索配置…", value: state.configSearch,
      onInput: onConfigSearchInput,
    }),
    h("div", { class: "config-nav-list" }, configGroupsForNav(groups, searchQuery).map(configNavItem)),
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

/* 操作条与导航徽标的局部刷新：控件提交/保存/放弃后只动这些小块。
   未保存改动只由状态徽标（badge-warn 文案）表达，操作条本身两种状态同款。 */
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
  const q = state.configSearch.trim().toLowerCase();
  const hit = configItemsOf(g).length;
  // 搜索期间导航只列出有命中的分组（含仅分组名命中的），点进去后搜索词保留，
  // 右栏仍按同一关键词过滤，用户能看到自己搜的是什么。
  const badge = count > 0
    ? h("span", { class: "badge badge-warn", text: `${count} 改` })
    : h("span", { class: "config-nav-count", text: q ? `${hit} 项` : `${g.items.length} 项` });
  return h("div", {
    class: `config-nav-item${g.key === state.configActive ? " active" : ""}${q && !hit ? " no-hit" : ""}`,
    dataset: { configGroup: g.key },
    // 草稿跨组平铺、切组不丢弃任何东西,无需拦截确认；搜索词也保留，
    // 但只做局部刷新，避免整树重建把导航滚动位置和输入焦点一起丢掉
    onClick: () => {
      if (state.configActive === g.key) return;
      state.configActive = g.key;
      state.configSearchPinned = true;   // 手动选组后不再被搜索自动跳走
      renderConfigFields();
    },
  }, [
    h("span", { text: g.name }),
    h("span", { class: "config-nav-badge" }, [badge]),
  ]);
}

function configFieldsChildren(active) {
  const items = configItemsOf(active);
  const q = state.configSearch.trim().toLowerCase();
  const children = [
    h("div", { class: "config-group-head" }, [
      h("h3", { text: active.name }),
      h("span", { class: "config-hint", text: q ? `匹配 ${items.length} 项` : `${items.length} 项` }),
    ]),
    // 搜索态下把命中片段摘出来：描述/键名/说明哪一处命中的，用户一眼能确认
    ...items.map(item => (q ? configItemWithMatch(item, q) : configItem(item))),
  ];
  // 不用 `length ? null : panel`:replaceChildren 不接受 null(仅 h() 会跳过)
  if (!items.length) {
    children.push(h("div", { class: "panel empty-note", text: q
      ? `「${state.configSearch.trim()}」在本分组没有匹配项，左侧导航已标出命中的分组`
      : "无匹配配置项" }));
  }
  return children;
}

/* 导航高亮与右栏字段区的局部刷新：搜索输入、切组都走这里。
   不整树重建(会丢失焦点/打断输入法)，导航输入框与滚动位置原地保留。 */
function renderConfigFields() {
  const root = els.configView;
  const navList = root?.querySelector(".config-nav-list");
  const fields = root?.querySelector(".config-fields");
  if (!navList || !fields) { renderConfig(); return; }
  const groups = Array.isArray(state.config?.groups) ? state.config.groups : [];
  const active = groups.find(g => g.key === state.configActive);
  navList.replaceChildren(...configGroupsForNav(groups, state.configSearch.trim().toLowerCase()).map(configNavItem));
  if (active) fields.replaceChildren(...configFieldsChildren(active));
}

// 搜索输入不整树重建(会丢失焦点/打断输入法):只刷新导航列表与右栏字段区。
function onConfigSearchInput(e) {
  state.configSearch = e.target.value;
  state.configSearchPinned = false;   // 换关键词重新按命中数定位
  const groups = Array.isArray(state.config?.groups) ? state.config.groups : [];
  const q = state.configSearch.trim().toLowerCase();
  // 输入过程中右栏始终停在有结果的分组上（清空搜索时留在当前组）
  if (q) state.configActive = pickConfigGroupForSearch(groups, state.configActive, q).key;
  renderConfigFields();
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
      // 成功状态由吸顶操作条徽标表达（✓ 配置已保存并热重载），不再发通知弹窗
      state.configJustSaved = true;
      setTimeout(() => { state.configJustSaved = false; renderConfigBarState(); }, 2400);
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

/* 搜索态字段卡：在正常卡片下方追加一行「命中位置」，说明这个字段为什么出现在
   结果里（描述 / 键名 / 说明），避免用户搜完只看到一堆无关卡片。 */
function configItemWithMatch(item, q) {
  const where = [];
  if ((item.description || "").toLowerCase().includes(q)) where.push("名称");
  if (item.key.toLowerCase().includes(q)) where.push("键名");
  if ((item.hint || "").toLowerCase().includes(q)) where.push("说明");
  const node = configItem(item);
  node.classList.add("config-item-hit");
  node.appendChild(h("div", { class: "config-hit-why", text: `命中：${where.join(" / ")}` }));
  return node;
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
    // input 实时提交草稿（顶部状态徽标立刻变化）；删空不提交，红边提示待处理
    input.addEventListener("input", () => {
      if (input.value.trim() === "") { input.classList.add("is-empty-edit"); return; }
      input.classList.remove("is-empty-edit");
      const num = Number(input.value);
      if (Number.isNaN(num)) return;
      commit(num);
    });
    input.addEventListener("change", () => {
      if (input.value.trim() === "") {
        // 删空后失焦：还原为草稿/已保存值，避免「看起来删掉了、实际旧值还在」
        input.classList.remove("is-empty-edit");
        const current = state.configDraft[item.key] !== undefined
          ? state.configDraft[item.key] : item.value;
        input.value = current === null || current === undefined ? "" : String(current);
        showAlert("数值不能为空，已还原", "warn");
        return;
      }
      if (Number.isNaN(Number(input.value))) showAlert("该配置项需要数字", "warn");
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
    // input 实时提交草稿：改动一发生，顶部操作条就出现强调色，不必等失焦
    const pushArea = () => commit(item.type === "list"
      ? area.value.split("\n").map(s => s.trim()).filter(Boolean)
      : area.value);
    area.addEventListener("input", pushArea);
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
  // 单行文本同样实时提交草稿，顶部强调色跟随击键出现
  input.addEventListener("input", () => commit(input.value));
  wrap.append(input);
  return wrap;
}

