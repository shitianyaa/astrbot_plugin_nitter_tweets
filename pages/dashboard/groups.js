// groups.js — Group List, Editor, Draft System & Subscriptions
import { state, els, h, svgIcon, iconEl, withAction, openConfirm, apiPost } from "./core.js";

export const PRIVATE_QQ_GROUP_WARNING =
  "风险提示：使用私人 QQ 号作为 Bot 时，不建议创建或启用标签分组和 List 分组。";

const EDITABLE_FIELDS = [
  "name","enabled","interval_check_enabled","daily_check_times",
  "filter_reposts_enabled","filter_plain_text_enabled","media_only_enabled",
  "omit_status_url","hide_original_when_translated",
  "push_targets","watch_users","watch_queries","watch_lists",
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
    } else if (["enabled","interval_check_enabled","filter_plain_text_enabled","media_only_enabled","omit_status_url","hide_original_when_translated"].includes(f)) {
      snap[f] = !!group[f];
    } else { snap[f] = group[f] || ""; }
  }
  snap.group_id = group.group_id; snap.group_type = group.group_type;
  return snap;
}

export function syncGroupDrafts() {
  for (const g of state.groups) {
    if (!state.groupDrafts[g.group_id]) state.groupDrafts[g.group_id] = snapshotGroup(g);
  }
}

export function isGroupDirty(groupId) {
  const g = state.groups.find(x => x.group_id === groupId);
  const d = state.groupDrafts[groupId];
  if (!g || !d) return false;
  return JSON.stringify(snapshotGroup(g)) !== JSON.stringify(d);
}

export function updateDraft(groupId, field, val) {
  const d = state.groupDrafts[groupId]; if (!d) return;
  d[field] = val; renderGroupList(); updateEditorControls(groupId);
}

/* --------------------------------------------------------------------------
   Group List
   -------------------------------------------------------------------------- */
export function renderGroupList() {
  if (!els.groupList) return;
  if (!state.groups.length) {
    els.groupList.replaceChildren(h("div", { class: "panel", style: { textAlign: "center", color: "var(--text-muted)" }, text: "暂无分组" }));
    return;
  }
  els.groupList.replaceChildren(...state.groups.map(g => {
    const active = g.group_id === state.selectedGroupId;
    const dirty = isGroupDirty(g.group_id);
    const icon = g.group_type === "tag" ? "hash" : g.group_type === "list" ? "rss" : "user";
    const label = g.group_type === "tag" ? "搜索" : g.group_type === "list" ? "List" : "博主";
    return h("div", {
      class: `group-item ${active ? "active" : ""}`,
      onClick: () => selectGroup(g.group_id),
    }, [
      h("div", { class: "group-item-row" }, [
        h("span", { style: { display: "flex", alignItems: "center", gap: "6px" }, html: svgIcon(icon, 16), text: (state.groupDrafts[g.group_id]?.name) || g.name }),
        dirty ? h("span", { class: "badge badge-warn", text: "未保存" }) : null,
      ]),
      h("div", { class: "group-item-meta" }, [
        h("span", { class: "badge badge-blue", text: label }),
        h("span", { class: "mono", text: g.group_id }),
        !g.enabled ? h("span", { class: "badge", text: "停用" }) : null,
      ]),
    ]);
  }));
}

function selectGroup(gid) {
  if (state.selectedGroupId && isGroupDirty(state.selectedGroupId)) {
    if (!confirm("有未保存更改，切换将丢弃。确认？")) return;
    const prev = state.groups.find(g => g.group_id === state.selectedGroupId);
    if (prev) state.groupDrafts[prev.group_id] = snapshotGroup(prev);
  }
  state.selectedGroupId = gid; renderGroupList(); renderGroupEditor();
}

/* --------------------------------------------------------------------------
   Group Editor
   -------------------------------------------------------------------------- */
function updateEditorControls(gid) {
  const g = state.groups.find(x => x.group_id === gid); if (!g) return;
  const dirty = isGroupDirty(gid);
  const save = document.getElementById("saveGroupBtn");
  if (save) save.disabled = !dirty;
  const chk = document.getElementById("checkGroupBtn");
  if (chk) { chk.disabled = !g.enabled || dirty; chk.title = !g.enabled ? "分组停用" : dirty ? "请先保存" : ""; }
}

export function renderGroupEditor() {
  if (!els.groupEditor) return;
  const g = state.groups.find(x => x.group_id === state.selectedGroupId);
  if (!g) { els.groupEditor.replaceChildren(h("div", { class: "panel", style: { textAlign: "center", color: "var(--text-muted)" }, text: "请选择一个分组" })); return; }
  const d = state.groupDrafts[g.group_id] || snapshotGroup(g);
  const dirty = isGroupDirty(g.group_id);

  // Head
  const head = h("div", { class: "panel-head" }, [
    h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, [
      h("h2", { text: d.name || g.name }),
      h("span", { class: `badge ${d.enabled ? "badge-ok" : "badge-warn"}`, text: d.enabled ? "启用" : "停用" }),
      h("span", { class: "mono", style: { color: "var(--text-muted)" }, text: g.group_id }),
    ]),
    h("div", { style: { display: "flex", gap: "6px" } }, [
      h("button", { id: "checkGroupBtn", class: "btn btn-sm", html: svgIcon("play", 14), text: "检查", disabled: !g.enabled || dirty, onClick: () => runCheck(g.group_id) }),
      h("button", { id: "saveGroupBtn", class: "btn btn-sm btn-primary", text: "保存", disabled: !dirty, onClick: () => saveGroup(g.group_id) }),
      g.group_id !== "default" ? h("button", { class: "btn btn-sm btn-danger", html: svgIcon("trash", 14), text: "删除", onClick: () => confirmDeleteGroup(g.group_id) }) : null,
    ]),
  ]);

  // Base config
  const base = h("div", { class: "editor-grid" }, [
    h("label", { class: "field" }, [
      h("span", { text: "分组名称" }),
      h("input", { type: "text", value: d.name, onInput: e => updateDraft(g.group_id, "name", e.target.value.trim()) }),
    ]),
    h("div", { style: { display: "flex", alignItems: "flex-end", justifyContent: "flex-end" } }, [
      h("label", { class: "toggle" }, [
        h("input", { type: "checkbox", checked: d.enabled, onChange: e => updateDraft(g.group_id, "enabled", e.target.checked) }),
        h("span", { class: "toggle-track" }),
        h("span", { text: "启用此分组" }),
      ]),
    ]),
  ]);

  // Policy toggles
  const policy = h("div", { class: "editor-grid" }, [
    toggleRow(d.filter_reposts_enabled, "过滤转发（需同时开启全局转发过滤总开关）", v => updateDraft(g.group_id, "filter_reposts_enabled", v)),
    toggleRow(d.filter_plain_text_enabled, "过滤纯文本（仅有媒体推文才推送）", v => updateDraft(g.group_id, "filter_plain_text_enabled", v)),
    toggleRow(d.interval_check_enabled, "开启定时循环间隔检查", v => updateDraft(g.group_id, "interval_check_enabled", v)),
    h("label", { class: "field editor-grid-full" }, [
      h("span", { text: "每日定时触发时间（逗号或换行分隔，如 08:00, 20:00）" }),
      h("input", { type: "text", value: (d.daily_check_times || []).join(", "), onInput: e => updateDraft(g.group_id, "daily_check_times", e.target.value.split(/[,，\s]+/).filter(Boolean)) }),
    ]),
  ]);

  // Private QQ warning for tag/list groups
  const warn = (g.group_type === "tag" || g.group_type === "list")
    ? h("div", { class: "alert warn", text: PRIVATE_QQ_GROUP_WARNING })
    : null;

  // Subscription entities section
  const entities = renderEntities(g, d);
  // Push targets section
  const targets = renderTargets(g, d);

  els.groupEditor.replaceChildren(h("div", { class: "panel" }, [
    head, warn, base, policy, entities, targets,
  ]));
}

function toggleRow(checked, label, onChange) {
  return h("label", { class: "toggle" }, [
    h("input", { type: "checkbox", checked, onChange: e => onChange(e.target.checked) }),
    h("span", { class: "toggle-track" }),
    h("span", { text: label }),
  ]);
}

function renderEntities(group, draft) {
  const isTag = group.group_type === "tag";
  const isList = group.group_type === "list";
  const icon = isTag ? "hash" : isList ? "rss" : "user";
  const label = isTag ? "搜索查询词" : isList ? "Twitter List ID" : "博主用户名";
  const list = isTag ? draft.watch_queries : isList ? draft.watch_lists : draft.watch_users;

  return h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } }, [
    h("div", { style: { display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, fontSize: "13px", color: "var(--text-muted)" } }, [
      iconEl(icon, 16), `订阅源 — ${label}`,
    ]),
    h("div", { class: "chip-list" },
      (list || []).map((item, idx) => {
        const val = typeof item === "object" ? item.query : item;
        return h("span", { class: "chip mono" }, [
          iconEl(icon, 12), val,
          h("button", { class: "btn-icon", style: { width: "20px", height: "20px" }, html: svgIcon("close", 12), onClick: () => {
            const next = [...list]; next.splice(idx, 1);
            updateDraft(group.group_id, isTag ? "watch_queries" : isList ? "watch_lists" : "watch_users", next);
            renderGroupEditor();
          }}),
        ]);
      })
    ),
    h("div", { style: { display: "flex", gap: "6px" } }, [
      h("input", { id: isList ? "newWatchListInput" : "newEntityInput", type: "text", placeholder: isTag ? "#tag 或关键词" : isList ? "纯数字 List ID" : "推特用户名", style: { width: "240px" } }),
      h("button", { class: "btn btn-sm", html: svgIcon("plus", 14), text: "添加", onClick: () => {
        if (isList) { addWatchList(group.group_id); }
        else {
          const inp = document.getElementById("newEntityInput");
          const v = inp?.value.trim(); if (!v) return;
          const next = [...(list || [])];
          if (isTag) next.push({ query: v, type: "tag" }); else next.push(v);
          updateDraft(group.group_id, isTag ? "watch_queries" : "watch_lists", next);
          renderGroupEditor();
        }
      }}),
    ]),
  ]);
}

function renderTargets(group, draft) {
  const targets = draft.push_targets || [];
  const probe = state.targetProbeResults[group.group_id];

  return h("div", { style: { display: "flex", flexDirection: "column", gap: "8px", borderTop: "1px solid var(--border)", paddingTop: "12px" } }, [
    h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } }, [
      h("span", { style: { display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, fontSize: "13px", color: "var(--text-muted)" } }, [iconEl("send", 16), "推送目标 (UMO)"]),
      h("button", { class: "btn btn-sm btn-ghost", html: svgIcon("probe", 14), text: "测试连通性", disabled: !targets.length, onClick: () => probeTargets(group.group_id) }),
    ]),
    h("div", { class: "chip-list" },
      targets.map((t, idx) => {
        const info = probe?.targets?.find(x => x.umo === t);
        return h("span", { class: "chip mono" }, [
          t,
          info ? h("span", { class: `badge ${info.valid ? "badge-ok" : "badge-danger"}`, text: info.platform_kind || (info.valid ? "有效" : "失败") }) : null,
          h("button", { class: "btn-icon", style: { width: "20px", height: "20px" }, html: svgIcon("close", 12), onClick: () => {
            const next = [...targets]; next.splice(idx, 1);
            updateDraft(group.group_id, "push_targets", next); renderGroupEditor();
          }}),
        ]);
      })
    ),
    h("div", { style: { display: "flex", gap: "6px" } }, [
      h("input", { id: "newTargetInput", type: "text", placeholder: "aiocqhttp:GroupMessage:123456", style: { width: "320px" } }),
      h("button", { class: "btn btn-sm", html: svgIcon("plus", 14), text: "添加", onClick: () => {
        const inp = document.getElementById("newTargetInput");
        const v = inp?.value.trim(); if (!v) return;
        updateDraft(group.group_id, "push_targets", [...targets, v]); renderGroupEditor();
      }}),
    ]),
  ]);
}

export function addWatchList(groupId) {
  const inp = document.getElementById("newWatchListInput");
  const val = inp?.value.trim(); if (!val) return;
  if (!/^\d{1,20}$/.test(val)) { alert("List ID 必须是 1-20 位正整数"); return; }
  const d = state.groupDrafts[groupId]; if (!d) return;
  if ((d.watch_lists || []).includes(val)) { alert("List ID 已存在"); return; }
  updateDraft(groupId, "watch_lists", [...(d.watch_lists || []), val]); renderGroupEditor();
}

/* --------------------------------------------------------------------------
   Actions
   -------------------------------------------------------------------------- */
export function createGroup() {
  const nameInput = h("input", { type: "text", value: "新订阅分组", style: { width: "100%", marginBottom: "10px" } });
  const options = [
    { value: "blogger", label: "博主分组" },
    { value: "tag", label: "搜索订阅分组" },
    { value: "list", label: "List 分组" },
  ];
  const radioBox = h("div", { class: "group-type-options", style: { display: "flex", flexDirection: "column", gap: "6px" } },
    options.map(opt => h("label", { style: { display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", cursor: "pointer" } }, [
      h("input", { type: "radio", name: "createGroupType", value: opt.value, checked: opt.value === "blogger" }),
      h("span", { text: opt.label }),
    ]))
  );
  const warn = h("div", { class: "alert warn", style: { marginTop: "10px" }, text: PRIVATE_QQ_GROUP_WARNING });

  openConfirm({
    title: "新建订阅分组",
    desc: h("div", {}, [h("div", { text: "分组名称：", style: { marginBottom: "4px", fontSize: "13px" } }), nameInput, h("div", { text: "选择类型：", style: { marginBottom: "4px", fontSize: "13px" } }), radioBox, warn]),
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

async function saveGroup(gid) {
  const d = state.groupDrafts[gid]; if (!d) return;
  await withAction(async () => {
    await apiPost("web/groups/update", d);
    delete state.groupDrafts[gid];
  }, "分组保存成功");
}

function confirmDeleteGroup(gid) {
  openConfirm({
    title: `删除分组 [${gid}]？`,
    desc: "此操作不可恢复，订阅规则与历史关联将被清理。",
    danger: true,
    action: () => withAction(async () => {
      await apiPost("web/groups/delete", { group_id: gid, force: true, confirm: "DELETE" });
      state.selectedGroupId = "";
    }, "分组已删除"),
  });
}

async function runCheck(gid) {
  await withAction(() => apiPost("web/check", { group_id: gid }), "检查完成");
}

async function probeTargets(gid) {
  await withAction(async () => {
    const res = await apiPost("web/targets/probe", { group_id: gid });
    state.targetProbeResults[gid] = res; renderGroupEditor();
  }, "探测完成", { reload: false });
}
