'use strict';

/* Demo shares the existing editors but never writes to the plugin configuration. */
const WIZARD_STEPS = [
  { title: "推文来源", phase: 0, view: "config", config: "basic", hint: "先选择抓取来源；使用 Nitter 或 List 时，按需填写可信的自建实例。" },
  { title: "媒体设置", phase: 0, view: "config", config: "media", hint: "按需选择图片、视频和画质。跳过会保留当前值，不会关闭媒体。" },
  { title: "AI 翻译", phase: 0, view: "config", config: "ai_translation", hint: "需要译文时再开启翻译、选择模型；不需要可以直接跳过。" },
  { title: "后台检查", phase: 0, view: "config", config: "schedule", hint: "设置全局后台开关和检查间隔。只做手动查询，可以保留关闭。" },
  { title: "发送设置", phase: 0, view: "config", config: "push", hint: "按需调整发送形式与间隔。具体订阅和 UMO 接下来在分组里填写。" },
  { title: "分组订阅", phase: 1, view: "groups", hint: "选择已有分组或新建草稿，填写订阅源。UMO 可稍后补；手动查询可跳过整步。" },
  { title: "核对配置", phase: 2, view: "overview", hint: "检查修改和缺失项。本轮是交互预览，不保存、不重载，也不发送测试消息。" },
];
let wizard = null;
let wizardPromptDismissed = false;

function wizardActive() { return wizard !== null; }

function startWizard() {
  if (wizardActive()) { goWizardStep(wizard.step); return; }
  if (state.loading || state.actionBusy || state.configSaving || !state.config || state.configError) {
    showAlert("请等待配置加载完成后再打开向导", "warn");
    return;
  }
  if (sheetOpen || cmdkOpen || els.createGroupModal?.classList.contains("open")) {
    showAlert("请先关闭当前弹层，再打开向导", "warn");
    return;
  }
  wizard = {
    step: 0, skipped: new Set(), newGroups: new Set(), returnFocus: document.activeElement,
    backup: structuredClone({
      groups: state.groups, groupDrafts: state.groupDrafts, configDraft: state.configDraft,
      pendingBlacklists: state.pendingBlacklists, selectedGroupId: state.selectedGroupId,
      configSearch: state.configSearch, configActive: state.configActive,
      configSearchPinned: state.configSearchPinned, targetProbeResults: state.targetProbeResults,
      targetBlacklists: state.targetBlacklists, view: state.view,
    }),
  };
  document.body.classList.add("wizard-active");
  goWizardStep(0);
}

function goWizardStep(index, skipped = null) {
  if (!wizardActive()) return;
  if (skipped === true) wizard.skipped.add(wizard.step);
  else if (skipped === false) wizard.skipped.delete(wizard.step);
  wizard.step = Math.max(0, Math.min(WIZARD_STEPS.length - 1, index));
  const step = WIZARD_STEPS[wizard.step];
  if (sheetOpen) closeSheet({ force: true, restoreFocus: false });
  closeCreateGroupModal();
  if (step.config) {
    state.configSearch = "";
    state.configSearchPinned = false;
    state.configActive = step.config;
  }
  switchView(step.view);
  if (step.config) renderConfig();
  if (step.view === "groups") renderGroupCards();
  renderWizard();
  window.scrollTo({ top: 0, behavior: "instant" });
  els.wizardBar.querySelector("[aria-current='step']")?.focus({ preventScroll: true });
}

function renderWizard() {
  if (!els.wizardBar) return;
  els.wizardBar.hidden = !wizardActive();
  if (!wizardActive()) return;
  const step = WIZARD_STEPS[wizard.step];
  const phases = ["基础配置", "分组订阅", "核对配置"];
  const starts = [0, 5, 6];
  els.wizardStartBtn.textContent = "返回向导";
  const nextLabel = wizard.step === 6 ? "结束预览" : wizard.step === 4 ? "去配置分组" : wizard.step === 5 ? "核对配置" : "下一步";
  const button = (text, onClick, props = {}) => h("button", { type: "button", class: "btn btn-sm", text, onClick, ...props });
  els.wizardBar.replaceChildren(
    h("div", { class: "wizard-heading" }, [
      h("h2", { text: "配置向导" }),
      h("span", { class: "badge badge-warn", text: "Demo · 不写入配置" }),
      button("退出预览", requestExitWizard, { class: "btn btn-sm btn-ghost wizard-exit" }),
    ]),
    h("nav", { class: "wizard-phases", "aria-label": "配置阶段" }, phases.map((title, phase) =>
      button(`${phase + 1} ${title}`, () => goWizardStep(starts[phase]), {
        class: `wizard-phase${phase === step.phase ? " active" : ""}`,
        "aria-current": phase === step.phase ? "step" : null,
      })
    )),
    h("div", { class: "wizard-bottom" }, [
      h("div", { class: "wizard-instruction" }, [
        h("nav", { class: "wizard-substeps", "aria-label": "当前阶段步骤" }, WIZARD_STEPS.flatMap((item, index) => item.phase === step.phase
          ? [button(item.title + (wizard.skipped.has(index) ? " · 已跳过" : ""), () => goWizardStep(index), {
              class: `wizard-substep${index === wizard.step ? " active" : ""}`,
              "aria-current": index === wizard.step ? "step" : null,
            })] : [])),
        h("p", { text: step.hint }),
      ]),
      h("div", { class: "wizard-actions" }, [
        button("上一步", () => goWizardStep(wizard.step - 1), { disabled: wizard.step === 0 }),
        wizard.step < 6 ? button("跳过此步", () => goWizardStep(wizard.step + 1, true)) : null,
        button(nextLabel, () => wizard.step === 6 ? requestExitWizard() : goWizardStep(wizard.step + 1, false), { class: "btn btn-sm btn-primary" }),
      ]),
    ]),
  );
  els.wizardReview.hidden = wizard.step !== 6 || state.view !== "overview";
  document.body.classList.toggle("wizard-reviewing", !els.wizardReview.hidden);
  if (wizard.step === 6) renderWizardReview();
}

function wizardEntry() {
  const incomplete = !state.groups.some(g => (g.watch_users?.length || g.watch_queries?.length || g.watch_lists?.length) && g.push_targets?.length);
  if (wizardActive() || wizardPromptDismissed || !incomplete) return null;
  return h("section", { class: "wizard-entry" }, [
    h("div", {}, [
      h("h3", { text: "先配基础，再添加订阅" }),
      h("p", { text: "跟着现有页面完成配置；每一步都能跳过，推送目标也可以稍后填写。" }),
    ]),
    h("div", { class: "row" }, [
      h("button", { type: "button", class: "btn btn-sm", text: "暂不需要", onClick: () => { wizardPromptDismissed = true; renderOverview(); } }),
      h("button", { type: "button", class: "btn btn-sm btn-primary", text: "预览配置向导", onClick: startWizard }),
    ]),
  ]);
}

function wizardCreateGroup(name, groupType) {
  const gid = `wizard-${crypto.randomUUID()}`;
  const group = {
    group_id: gid, group_type: groupType, name, enabled: false,
    interval_check_enabled: true, daily_check_times: [], filter_reposts_enabled: true,
    filter_plain_text_enabled: false, media_only_enabled: "完整推文",
    omit_status_url: false, hide_original_when_translated: false,
    watch_users: [], watch_queries: [], watch_lists: [], push_targets: [],
    check_interval_minutes: state.configDraft.check_interval_minutes ?? findConfigItem("check_interval_minutes")?.value,
  };
  wizard.newGroups.add(gid);
  state.groups = [...state.groups, group];
  state.groupDrafts[gid] = snapshotGroup(group);
  state.selectedGroupId = gid;
  renderGroupCards();
  openGroupSheet(gid);
}

function wizardChanges() {
  const baseline = wizard.backup;
  const config = [...new Set([...Object.keys(baseline.configDraft), ...Object.keys(state.configDraft)])].flatMap(key => {
    const item = findConfigItem(key);
    const before = Object.hasOwn(baseline.configDraft, key) ? baseline.configDraft[key] : item?.value;
    const after = Object.hasOwn(state.configDraft, key) ? state.configDraft[key] : item?.value;
    return item && JSON.stringify(before) !== JSON.stringify(after) ? [{ item, before, after }] : [];
  });
  const groups = state.groups.flatMap(group => {
    const draft = state.groupDrafts[group.group_id] || snapshotGroup(group);
    const before = baseline.groupDrafts[group.group_id];
    const blacklistChanged = JSON.stringify(baseline.pendingBlacklists[group.group_id] || {}) !== JSON.stringify(state.pendingBlacklists[group.group_id] || {});
    return wizard.newGroups.has(group.group_id) || JSON.stringify(before) !== JSON.stringify(draft) || blacklistChanged ? [{ group, draft, blacklistChanged }] : [];
  });
  return { config, groups };
}

function wizardValue(value) {
  if (typeof value === "boolean") return value ? "开启" : "关闭";
  if (Array.isArray(value)) return value.length ? value.join("、") : "未填写";
  return String(value ?? "") || "未填写";
}

function renderWizardReview() {
  const { config, groups } = wizardChanges();
  const section = (title, rows) => h("section", { class: "wizard-review-section" }, [h("h3", { text: title }), ...rows]);
  els.wizardReview.replaceChildren(
    h("h2", { text: "核对本次预览" }),
    h("p", { class: "wizard-review-note", text: "以下只显示进入向导后的修改。退出会恢复原配置与原有草稿；本轮不提供保存。" }),
    section(`全局配置 · ${config.length} 项修改`, config.length ? config.map(({ item, before, after }) =>
      h("div", { class: "wizard-review-row" }, [
        h("strong", { text: item.description }),
        h("span", { text: `${wizardValue(before)} → ${wizardValue(after)}` }),
      ])
    ) : [h("p", { text: "全局配置未修改，保留当前设置。" })]),
    section(`分组订阅 · ${groups.length} 个草稿`, groups.length ? groups.map(({ group, draft, blacklistChanged }) => {
      const sources = group.group_type === "tag" ? draft.watch_queries : group.group_type === "list" ? draft.watch_lists : draft.watch_users;
      const gaps = [!sources?.length ? "未填写订阅源" : "", !draft.push_targets?.length ? "UMO 待补充" : ""].filter(Boolean);
      return h("div", { class: "wizard-review-row" }, [
        h("strong", { text: draft.name || group.group_id }),
        h("span", { text: `${wizard.newGroups.has(group.group_id) ? "新建" : "修改"} · ${sources?.length || 0} 个订阅源 · ${draft.push_targets?.length || 0} 个目标` }),
        blacklistChanged ? h("span", { class: "badge", text: "黑名单草稿有修改" }) : null,
        gaps.length ? h("span", { class: "badge badge-warn", text: `${gaps.join("、")}；需补齐后启用推送` }) : null,
        group.group_type === "list" ? h("span", { class: "hint", text: "List 须公开，且需要配置 Nitter 实例。" }) : null,
      ]);
    }) : [h("p", { text: "未新增或修改分组。只做手动查询，不需要推送目标。" })]),
    section("跳过的步骤", [h("p", { text: [...wizard.skipped].map(index => WIZARD_STEPS[index].title).join("、") || "没有跳过步骤。" })]),
    h("p", { class: "wizard-review-note", text: "正式版将从这里统一保存并应用。首次后台检查只建立基准，不推送历史；平台识别检查不等于消息已送达。" }),
  );
}

function requestExitWizard() {
  if (!wizardActive()) return;
  openConfirm({
    title: "结束向导预览？", desc: "本次预览的修改会丢弃，进入前已有的配置和未保存草稿保持不变。",
    confirmText: "结束预览", action: exitWizard,
  });
}

function exitWizard() {
  if (!wizardActive()) return;
  const { backup, returnFocus } = wizard;
  if (sheetOpen) closeSheet({ force: true, restoreFocus: false });
  closeCreateGroupModal();
  const view = backup.view;
  delete backup.view;
  Object.assign(state, backup);
  wizard = null;
  document.body.classList.remove("wizard-active", "wizard-reviewing");
  els.wizardBar.hidden = true;
  els.wizardReview.hidden = true;
  els.wizardStartBtn.textContent = "配置向导";
  buildConfigIndex();
  markData("config", "groups", "overview");
  switchView(view);
  returnFocus?.focus?.();
}
