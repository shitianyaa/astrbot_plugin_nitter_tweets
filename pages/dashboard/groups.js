// groups.js - Group List, Group Editor, Draft System & Subscriptions
import { state, els, h, withAction, openConfirm, apiPost } from "./core.js";

export const PRIVATE_QQ_GROUP_WARNING =
  "风险提示：使用私人 QQ 号作为 Bot 时，不建议创建或启用标签分组和 List 分组。";

const EDITABLE_FIELDS = [
  "name",
  "enabled",
  "interval_check_enabled",
  "daily_check_times",
  "filter_reposts_enabled",
  "filter_plain_text_enabled",
  "media_only_enabled",
  "omit_status_url",
  "hide_original_when_translated",
  "push_targets",
  "watch_users",
  "watch_queries",
  "watch_lists"
];

export function snapshotGroup(group) {
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
    } else if (f === "enabled" || f === "interval_check_enabled" || f === "filter_plain_text_enabled" || f === "media_only_enabled" || f === "omit_status_url" || f === "hide_original_when_translated") {
      snap[f] = !!group[f];
    } else {
      snap[f] = group[f] || "";
    }
  }
  snap.group_id = group.group_id;
  snap.group_type = group.group_type;
  return snap;
}

export function syncGroupDrafts() {
  for (const g of state.groups) {
    if (!state.groupDrafts[g.group_id]) {
      state.groupDrafts[g.group_id] = snapshotGroup(g);
    }
  }
}

export function isGroupDirty(groupId) {
  const g = state.groups.find(x => x.group_id === groupId);
  const d = state.groupDrafts[groupId];
  if (!g || !d) return false;
  return JSON.stringify(snapshotGroup(g)) !== JSON.stringify(d);
}

export function updateDraft(groupId, field, val) {
  const d = state.groupDrafts[groupId];
  if (!d) return;
  d[field] = val;
  renderGroupList();
  updateEditorHeaderControls(groupId);
}

/* --------------------------------------------------------------------------
   Group List
   -------------------------------------------------------------------------- */
export function renderGroupList() {
  if (!els.groupList) return;
  if (!state.groups.length) {
    els.groupList.replaceChildren(h("div", { class: "panel", text: "暂无分组，请新建。" }));
    return;
  }

  const items = state.groups.map(g => {
    const active = g.group_id === state.selectedGroupId;
    const dirty = isGroupDirty(g.group_id);
    const typeTag = g.group_type === "tag" ? "搜索" : g.group_type === "list" ? "List" : "博主";

    return h("div", {
      class: `group-item ${active ? "active" : ""}`,
      onClick: () => selectGroup(g.group_id)
    }, [
      h("div", { class: "group-item-head" }, [
        h("span", { text: (state.groupDrafts[g.group_id] && state.groupDrafts[g.group_id].name) || g.name }),
        dirty ? h("span", { class: "badge warn", text: "● 未保存" }) : null
      ]),
      h("div", { class: "group-item-meta" }, [
        h("span", { class: "badge", text: typeTag }),
        h("span", { text: g.group_id, class: "mono" }),
        !g.enabled ? h("span", { class: "badge", text: "已停用" }) : null
      ])
    ]);
  });

  els.groupList.replaceChildren(...items);
}

function selectGroup(groupId) {
  if (state.selectedGroupId && isGroupDirty(state.selectedGroupId)) {
    if (!window.confirm("当前分组有未保存的更改，切换将丢弃未保存内容。确认放弃？")) {
      return;
    }
    const prev = state.groups.find(g => g.group_id === state.selectedGroupId);
    if (prev) state.groupDrafts[prev.group_id] = snapshotGroup(prev);
  }
  state.selectedGroupId = groupId;
  renderGroupList();
  renderGroupEditor();
}

/* --------------------------------------------------------------------------
   Group Editor
   -------------------------------------------------------------------------- */
function updateEditorHeaderControls(groupId) {
  const g = state.groups.find(x => x.group_id === groupId);
  if (!g) return;
  const dirty = isGroupDirty(groupId);

  const saveBtn = document.getElementById("saveGroupBtn");
  if (saveBtn) saveBtn.disabled = !dirty || state.actionBusy;

  const checkBtn = document.getElementById("checkGroupBtn");
  if (checkBtn) {
    checkBtn.disabled = !g.enabled || dirty || state.actionBusy;
    checkBtn.title = !g.enabled ? "分组停用时不能检查" : dirty ? "请先保存更改" : "立即触发一次检查";
  }
}

export function renderGroupEditor() {
  if (!els.groupEditor) return;
  const g = state.groups.find(x => x.group_id === state.selectedGroupId);
  if (!g) {
    els.groupEditor.replaceChildren(h("div", { class: "panel", text: "请选择或新建一个分组以进行配置。" }));
    return;
  }

  const d = state.groupDrafts[g.group_id] || snapshotGroup(g);
  const dirty = isGroupDirty(g.group_id);

  const head = h("div", { class: "panel-head" }, [
    h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, [
      h("h2", { text: d.name || g.name }),
      h("span", { class: `badge ${d.enabled ? "ok" : "warn"}`, text: d.enabled ? "启用中" : "已停用" }),
      h("span", { class: "mono", style: { color: "var(--text-muted)" }, text: `ID: ${g.group_id}` })
    ]),
    h("div", { style: { display: "flex", gap: "6px" } }, [
      h("button", {
        id: "checkGroupBtn",
        class: "button small",
        text: "立即检查",
        disabled: !g.enabled || dirty,
        onClick: () => runCheck(g.group_id)
      }),
      h("button", {
        id: "saveGroupBtn",
        class: "button small primary",
        text: "保存更改",
        disabled: !dirty,
        onClick: () => saveGroup(g.group_id)
      }),
      g.group_id !== "default" ? h("button", {
        class: "button small danger ghost",
        text: "删除分组",
        onClick: () => confirmDeleteGroup(g.group_id)
      }) : null
    ])
  ]);

  const baseConfig = h("div", { class: "editor-grid" }, [
    h("label", { class: "field" }, [
      h("span", { text: "分组名称" }),
      h("input", {
        type: "text",
        value: d.name,
        onInput: (e) => updateDraft(g.group_id, "name", e.target.value.trim())
      })
    ]),
    h("div", { class: "field", style: { justifyContent: "flex-end" } }, [
      h("label", { class: "toggle-label" }, [
        h("div", { class: "toggle-switch" }, [
          h("input", {
            type: "checkbox",
            checked: d.enabled,
            onChange: (e) => updateDraft(g.group_id, "enabled", e.target.checked)
          }),
          h("span", { class: "toggle-slider" })
        ]),
        h("span", { text: "启用此分组检查" })
      ])
    ])
  ]);

  const policyConfig = h("div", { class: "editor-grid" }, [
    h("label", { class: "toggle-label" }, [
      h("div", { class: "toggle-switch" }, [
        h("input", {
          type: "checkbox",
          checked: d.filter_reposts_enabled,
          onChange: (e) => updateDraft(g.group_id, "filter_reposts_enabled", e.target.checked)
        }),
        h("span", { class: "toggle-slider" })
      ]),
      h("span", { text: "过滤转发内容（需同时开启全局转发过滤总开关）" })
    ]),
    h("label", { class: "toggle-label" }, [
      h("div", { class: "toggle-switch" }, [
        h("input", {
          type: "checkbox",
          checked: d.filter_plain_text_enabled,
          onChange: (e) => updateDraft(g.group_id, "filter_plain_text_enabled", e.target.checked)
        }),
        h("span", { class: "toggle-slider" })
      ]),
      h("span", { text: "过滤纯文本（仅有媒体推文才推送）" })
    ]),
    h("label", { class: "toggle-label" }, [
      h("div", { class: "toggle-switch" }, [
        h("input", {
          type: "checkbox",
          checked: d.interval_check_enabled,
          onChange: (e) => updateDraft(g.group_id, "interval_check_enabled", e.target.checked)
        }),
        h("span", { class: "toggle-slider" })
      ]),
      h("span", { text: "开启定时循环间隔检查" })
    ]),
    h("label", { class: "field" }, [
      h("span", { text: "每日定时触发时间 (以逗号或换行隔开，如 08:00, 20:00)" }),
      h("input", {
        type: "text",
        value: Array.isArray(d.daily_check_times) ? d.daily_check_times.join(", ") : "",
        onInput: (e) => updateDraft(g.group_id, "daily_check_times", e.target.value.split(/[,，\s]+/).filter(Boolean))
      })
    ])
  ]);

  const warningCard = (g.group_type === "tag" || g.group_type === "list")
    ? h("div", { class: "alert warn", text: PRIVATE_QQ_GROUP_WARNING })
    : null;

  const entitiesPanel = renderEntitiesSection(g, d);
  const targetsPanel = renderTargetsSection(g, d);

  els.groupEditor.replaceChildren(h("div", { class: "panel" }, [
    head,
    warningCard,
    baseConfig,
    policyConfig,
    entitiesPanel,
    targetsPanel
  ]));
}

export function addWatchList(groupId) {
  const inp = document.getElementById("newWatchListInput");
  const val = inp ? inp.value.trim() : "";
  if (!val) return;
  if (!/^\d{1,20}$/.test(val)) {
    alert("List ID 必须是 1-20 位正整数");
    return;
  }
  const d = state.groupDrafts[groupId];
  if (!d) return;
  const list = d.watch_lists || [];
  if (list.includes(val)) {
    alert("List ID 已存在");
    return;
  }
  updateDraft(groupId, "watch_lists", [...list, val]);
  renderGroupEditor();
}

function renderEntitiesSection(group, draft) {
  const isTag = group.group_type === "tag";
  const isList = group.group_type === "list";
  const typeLabel = isTag ? "搜索查询词 (Query)" : isList ? "Twitter List ID" : "关注推特博主 (Username)";
  const list = isTag ? draft.watch_queries : isList ? draft.watch_lists : draft.watch_users;

  return h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } }, [
    h("div", { style: { fontWeight: "600", fontSize: "12px", color: "var(--text-muted)" }, text: `订阅源列表 - ${typeLabel}` }),
    h("div", { class: "chip-list" },
      (list || []).map((item, idx) => {
        const val = typeof item === "object" ? item.query : item;
        return h("span", { class: "chip mono" }, [
          val,
          h("button", {
            class: "button ghost small",
            style: { padding: "0 2px", color: "var(--danger)" },
            text: "×",
            onClick: () => {
              const next = [...list];
              next.splice(idx, 1);
              updateDraft(group.group_id, isTag ? "watch_queries" : isList ? "watch_lists" : "watch_users", next);
              renderGroupEditor();
            }
          })
        ]);
      })
    ),
    h("div", { style: { display: "flex", gap: "6px" } }, [
      h("input", {
        id: isList ? "newWatchListInput" : "newEntityInput",
        type: "text",
        placeholder: isTag ? "#tag 或关键词" : isList ? "纯数字 List ID" : "推特用户名 (无需@)",
        style: { width: "240px" }
      }),
      h("button", {
        class: "button small",
        text: "添加",
        onClick: () => {
          if (isList) {
            addWatchList(group.group_id);
          } else {
            const inp = document.getElementById("newEntityInput");
            const val = inp ? inp.value.trim() : "";
            if (!val) return;
            const next = [...(list || [])];
            if (isTag) next.push({ query: val, type: "tag" });
            else next.push(val);
            updateDraft(group.group_id, isTag ? "watch_queries" : isList ? "watch_lists" : "watch_users", next);
            renderGroupEditor();
          }
        }
      })
    ])
  ]);
}

function renderTargetsSection(group, draft) {
  const targets = draft.push_targets || [];
  const probeRes = state.targetProbeResults[group.group_id];

  return h("div", { style: { display: "flex", flexDirection: "column", gap: "8px", borderTop: "1px solid var(--border-muted)", paddingTop: "12px" } }, [
    h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } }, [
      h("span", { style: { fontWeight: "600", fontSize: "12px", color: "var(--text-muted)" }, text: "推送目标会话 (UMO)" }),
      h("button", {
        class: "button small ghost",
        text: "测试目标连通性",
        disabled: !targets.length,
        onClick: () => probeTargets(group.group_id)
      })
    ]),
    h("div", { class: "chip-list" },
      targets.map((t, idx) => {
        const pInfo = probeRes && probeRes.targets && probeRes.targets.find(x => x.umo === t);
        return h("span", { class: "chip mono" }, [
          t,
          pInfo ? h("span", { class: `badge ${pInfo.valid ? "ok" : "danger"}` }, [
            pInfo.platform_kind || (pInfo.valid ? "有效" : "失败")
          ]) : null,
          h("button", {
            class: "button ghost small",
            style: { padding: "0 2px", color: "var(--danger)" },
            text: "×",
            onClick: () => {
              const next = [...targets];
              next.splice(idx, 1);
              updateDraft(group.group_id, "push_targets", next);
              renderGroupEditor();
            }
          })
        ]);
      })
    ),
    h("div", { style: { display: "flex", gap: "6px" } }, [
      h("input", {
        id: "newTargetInput",
        type: "text",
        placeholder: "如 aiocqhttp:GroupMessage:123456",
        style: { width: "320px" }
      }),
      h("button", {
        class: "button small",
        text: "添加目标",
        onClick: () => {
          const inp = document.getElementById("newTargetInput");
          const val = inp ? inp.value.trim() : "";
          if (!val) return;
          const next = [...targets, val];
          updateDraft(group.group_id, "push_targets", next);
          renderGroupEditor();
        }
      })
    ])
  ]);
}

/* --------------------------------------------------------------------------
   Actions & Dialogs
   -------------------------------------------------------------------------- */
export function createGroup() {
  // Modal with radio options
  const nameInput = h("input", { type: "text", value: "新订阅分组", style: { width: "100%", marginBottom: "10px" } });
  
  const options = [
    { value: "blogger", label: "博主分组" },
    { value: "tag", label: "搜索订阅分组" },
    { value: "list", label: "List 分组" },
  ];

  const radioContainer = h("div", { class: "group-type-options", style: { display: "flex", flexDirection: "column", gap: "6px" } },
    options.map(opt => h("label", { style: { display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", cursor: "pointer" } }, [
      h("input", { type: "radio", name: "createGroupType", value: opt.value, checked: opt.value === "blogger" }),
      h("span", { text: opt.label })
    ]))
  );

  const warnMsg = h("div", { class: "alert warn", style: { marginTop: "10px" }, text: PRIVATE_QQ_GROUP_WARNING });

  const desc = h("div", {}, [
    h("div", { style: { marginBottom: "4px", fontSize: "12px" }, text: "分组名称：" }),
    nameInput,
    h("div", { style: { marginBottom: "4px", fontSize: "12px" }, text: "选择分组类型：" }),
    radioContainer,
    warnMsg
  ]);

  openConfirm({
    title: "新建订阅分组",
    desc,
    confirmText: "创建",
    action: () => withAction(async () => {
      const selectedRadio = radioContainer.querySelector('input[name="createGroupType"]:checked');
      const gType = selectedRadio ? selectedRadio.value : "blogger";
      const name = nameInput.value.trim() || "新订阅分组";
      const res = await apiPost("web/groups/create", { name, group_type: gType });
      if (res && res.group) {
        state.selectedGroupId = res.group.group_id;
      }
    }, "分组创建成功")
  });
}

async function saveGroup(groupId) {
  const draft = state.groupDrafts[groupId];
  if (!draft) return;
  await withAction(async () => {
    await apiPost("web/groups/update", draft);
    delete state.groupDrafts[groupId];
  }, "分组保存成功");
}

function confirmDeleteGroup(groupId) {
  openConfirm({
    title: `确认删除分组 [${groupId}]？`,
    desc: "此操作不可恢复，已订阅的规则与相关历史关联都将被清理。",
    danger: true,
    action: () => withAction(async () => {
      await apiPost("web/groups/delete", { group_id: groupId, force: true, confirm: "DELETE" });
      state.selectedGroupId = "";
    }, "分组已删除")
  });
}

async function runCheck(groupId) {
  await withAction(() => apiPost("web/check", { group_id: groupId }), "检查执行完成");
}

async function probeTargets(groupId) {
  await withAction(async () => {
    const res = await apiPost("web/targets/probe", { group_id: groupId });
    state.targetProbeResults[groupId] = res;
    renderGroupEditor();
  }, "连通性探测完成", { reload: false });
}
