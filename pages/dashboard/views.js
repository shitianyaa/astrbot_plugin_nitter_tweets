// views.js — Overview, Tweet-feed History, Probe & Danger Zone
import { state, els, h, svgIcon, iconEl, withAction, openConfirm, apiGet, apiPost, copyText } from "./core.js";

/* --------------------------------------------------------------------------
   Rail Health Status
   -------------------------------------------------------------------------- */
export function renderRailStatus() {
  const p = state.overview; if (!p) return;
  const s = p.scheduler || {}; const c = p.counts || {};
  setRailPill("railSchedulerStatus", s.running ? "ok" : "warn", s.running ? "运行中" : "未启动");
  setRailPill("railScheduleStatus", s.schedule_enabled ? "ok" : "warn", s.schedule_enabled ? "已开启" : "已关闭");
  const inv = c.invalid_push_targets || 0;
  setRailPill("railTargetStatus", inv > 0 ? "danger" : "ok", inv > 0 ? `${inv} 异常` : "正常");
}
function setRailPill(id, cls, text) {
  const el = els[id]; if (!el) return;
  el.className = `pill-status pill-${cls}`;
  el.replaceChildren(h("span", { class: "dot" }), h("span", { text }));
}

/* --------------------------------------------------------------------------
   Overview
   -------------------------------------------------------------------------- */
export function renderOverview() {
  const root = els.overviewView; if (!root) return;
  const p = state.overview;
  if (!p) { root.replaceChildren(h("div", { class: "panel", text: "正在加载..." })); return; }
  const c = p.counts || {}; const s = p.scheduler || {};
  const cfg = p.config_summary || {}; const inst = p.instances || [];
  const att = p.attention_items || [];

  // Metric cards with icons
  const metrics = h("div", { class: "metrics-grid" }, [
    metric("home", "调度器", s.running ? "运行中" : "已停用"),
    metric("list", "启用分组", `${c.enabled_groups || 0} / ${c.groups || 0}`),
    metric("user", "博主订阅", c.watch_users || 0),
    metric("hash", "搜索订阅", c.watch_queries || 0),
    metric("rss", "List 订阅", c.watch_lists || 0),
    metric("send", "推送目标", c.push_targets || 0),
  ]);

  // Attention items
  const attPanel = att.length ? h("div", { class: "panel" }, [
    h("div", { class: "panel-head" }, [
      h("h3", { text: "需要关注" }),
      h("span", { class: "badge badge-warn", text: `${att.length} 项` }),
    ]),
    ...att.map(item => h("div", {
      class: `alert-item ${item.level === "error" ? "danger" : item.level === "warn" ? "warn" : "info"}`,
    }, [
      h("span", {}, [
        h("strong", { text: `${item.title || ""}: ` }),
        item.detail || "",
      ]),
      item.group_id ? h("button", {
        class: "btn btn-ghost btn-sm",
        html: svgIcon("external", 14),
        onClick: () => { state.selectedGroupId = item.group_id; document.querySelector('[data-view="groups"]')?.click(); },
      }) : null,
    ])),
  ]) : null;

  // Instance & config summary
  const configPanel = h("div", { class: "panel" }, [
    h("div", { class: "panel-head" }, [h("h3", { text: "实例与配置" })]),
    h("div", { style: { display: "flex", flexWrap: "wrap", gap: "10px" } }, [
      h("div", { class: "field", style: { flex: "1 1 260px" } }, [
        h("span", { text: "已配置 Nitter 实例" }),
        inst.length
          ? h("div", { class: "chip-list" }, inst.map(u => h("span", { class: "chip mono chip-action", text: u, onClick: () => { if (els.mirrorInstance) els.mirrorInstance.value = u; document.querySelector('[data-view="mirror"]')?.click(); } })))
          : h("span", { class: "badge badge-warn", text: "未配置任何实例" }),
      ]),
      h("div", { class: "field", style: { flex: "1 1 200px" } }, [
        h("span", { text: "调度参数" }),
        h("div", { class: "chip-list" }, [
          badge(`检查间隔 ${cfg.check_interval_minutes || 0}m`),
          badge(`合并阈值 ${cfg.merge_tweet_threshold || 0}`),
          badge(`目标间隔 ${cfg.send_target_interval || 0}s`),
          badge(`并发 ${cfg.concurrent_fetch_enabled ? "开" : "关"}`),
        ]),
      ]),
    ]),
  ]);

  // Danger zone
  const dz = h("div", { class: "panel danger-zone" }, [
    h("div", { class: "panel-head" }, [
      h("h3", { text: "维护与缓存清理" }),
      h("span", { class: "badge badge-danger", text: "不可逆" }),
    ]),
    h("div", { class: "danger-grid" }, [
      h("div", { class: "danger-item" }, [
        h("h4", { text: "清理媒体缓存" }),
        h("p", { text: "删除临时下载的图片与视频附件" }),
        h("div", { class: "actions" }, [
          h("button", { class: "btn btn-danger btn-sm", text: "清理", onClick: confirmClearCache }),
        ]),
      ]),
      h("div", { class: "danger-item" }, [
        h("h4", { text: "重置推送记录 (Seen)" }),
        h("p", { text: "可能导致历史推文再次推送" }),
        h("div", { class: "actions" }, [
          h("select", { id: "seenSelect", style: { width: "auto" } }, [
            h("option", { value: "", text: "全部分组" }),
            ...state.groups.map(g => h("option", { value: g.group_id, text: g.name })),
          ]),
          h("button", { class: "btn btn-danger btn-sm", text: "重置", onClick: confirmClearSeen }),
        ]),
      ]),
    ]),
  ]);

  root.replaceChildren(metrics, attPanel, configPanel, dz);
}

function metric(icon, label, value) {
  return h("div", { class: "metric" }, [
    h("div", { class: "metric-icon", html: svgIcon(icon, 16) }),
    h("span", { class: "metric-label", text: label }),
    h("span", { class: "metric-value", text: String(value) }),
  ]);
}
function badge(text) { return h("span", { class: "badge", text }); }

/* --------------------------------------------------------------------------
   History — Tweet-style Feed
   -------------------------------------------------------------------------- */
export function renderHistory() {
  const root = els.historyView; if (!root) return;
  const data = state.history;
  const recs = (data && data.records) || [];

  // Sync group dropdown
  if (els.historyGroupSelect && !els.historyGroupSelect.children.length) {
    els.historyGroupSelect.replaceChildren(
      h("option", { value: "", text: "所有分组" }),
      ...state.groups.map(g => h("option", { value: g.group_id, text: g.name })),
    );
  }
  // Pager
  if (els.historyPageLabel && data) {
    els.historyPageLabel.textContent = `${data.page || 1} / ${data.total_pages || 1} 页 · 共 ${data.total_count || 0} 条`;
  }
  if (els.historyPrevBtn && data) els.historyPrevBtn.disabled = !data.has_prev;
  if (els.historyNextBtn && data) els.historyNextBtn.disabled = !data.has_next;

  const content = els.historyContent;
  if (!recs.length) {
    content.replaceChildren(h("div", { class: "panel", style: { textAlign: "center", color: "var(--text-muted)", padding: "32px" }, text: "暂无推送历史记录" }));
    return;
  }

  content.replaceChildren(...recs.map(r => {
    const st = r.delivery_status;
    const stBadge = h("span", { class: `badge ${st === "success" ? "badge-ok" : st === "partial_failed" ? "badge-warn" : "badge-danger"}`, text: st === "success" ? "已送达" : st === "partial_failed" ? "部分失败" : "发送失败" });
    const hasMedia = (r.text_preview || "").includes("[媒体]") || (r.text_preview || "").includes("图") || (r.text_preview || "").includes("视频");

    return h("div", { class: "tweet-card" }, [
      // Avatar placeholder
      h("div", { class: "tweet-avatar", html: svgIcon("user", 20) }),
      h("div", { class: "tweet-body" }, [
        // Meta line: @handle · time · status
        h("div", { class: "tweet-meta" }, [
          h("span", { class: "tweet-author", text: r.username || "unknown" }),
          h("span", { class: "tweet-handle mono", text: `@${r.username || "unknown"}` }),
          h("span", { text: "·" }),
          h("span", { class: "tweet-time mono", text: r.pushed_at || "-" }),
          stBadge,
        ]),
        // Tweet text
        h("div", { class: "tweet-text" }, [
          r.original_link ? h("a", { href: r.original_link, target: "_blank", class: "mono", text: r.status_id, style: { marginRight: "6px", fontWeight: "600" } }) : null,
          r.text_preview || "(无文字内容)",
        ]),
        // Footer: media badge + actions
        h("div", { class: "tweet-footer" }, [
          h("span", { class: "tweet-meta-badge" }, [
            iconEl("list", 14), `${r.group_name || r.group_id}`,
          ]),
          hasMedia ? h("span", { class: "tweet-meta-badge" }, [
            iconEl("image", 14), "含媒体",
          ]) : null,
          h("div", { class: "tweet-actions" }, [
            r.original_link ? h("button", {
              class: "btn-icon",
              title: "复制链接",
              html: svgIcon("copy", 16),
              onClick: () => copyText(r.original_link),
            }) : null,
            h("button", {
              class: "btn btn-ghost btn-sm",
              html: iconEl("refresh", 14).outerHTML,
              text: "重推",
              onClick: () => replayHistory(r.id, r.replay_target_options),
            }),
          ]),
        ]),
      ]),
    ]);
  }));
}

export async function loadHistoryPage(delta) {
  if (!state.history) return;
  const offset = delta < 0 ? state.history.prev_offset : state.history.next_offset;
  if (offset === null || offset === undefined) return;
  state.historyOffset = offset;
  await withAction(async () => {
    state.history = await apiGet("web/history", {
      group_id: state.historyGroupId || undefined,
      username: state.historyUsername || undefined,
      limit: state.historyLimit, offset: state.historyOffset,
    });
    renderHistory();
  }, "翻页完成", { reload: false });
}

export async function detectHistoryOrphans() {
  await withAction(async () => {
    const res = await apiGet("web/history/orphans");
    const ops = res.orphans || [];
    if (!ops.length) {
      els.historyOrphanResult.replaceChildren(h("div", { class: "badge badge-ok", text: "未检测到废弃分组的残留历史" }));
      return;
    }
    els.historyOrphanResult.replaceChildren(h("div", { class: "panel" }, [
      h("div", { class: "panel-head" }, [h("h3", { text: `废弃分组残留 (${ops.length})` })]),
      h("div", { class: "chip-list" }, ops.map(o => h("span", { class: "chip mono" }, [
        `${o.group_id} (${o.record_count}条)`,
        h("button", { class: "btn btn-danger btn-sm", text: "删除", onClick: () => confirmDeleteOrphan(o.group_id) }),
      ]))),
    ]));
  }, "检测完成", { reload: false });
}

function confirmDeleteOrphan(gid) {
  openConfirm({
    title: `删除废弃分组 [${gid}] 历史？`,
    desc: "该分组已不存在，删除后相关记录彻底清除。",
    danger: true,
    action: () => withAction(() => apiPost("web/history/orphans/delete", { group_id: gid, confirm: "DELETE" }), "删除成功", { reload: false, rerender: detectHistoryOrphans }),
  });
}

function replayHistory(id, options) {
  openConfirm({
    title: "重推此推文",
    desc: options?.length ? `将重推至 ${options.length} 个目标` : "将重推至原目标",
    action: () => withAction(() => apiPost("web/history/replay", { record_id: id }), "重推已触发"),
  });
}

/* --------------------------------------------------------------------------
   Mirror Probe
   -------------------------------------------------------------------------- */
export function renderMirrorBase() {
  if (!els.instanceList) return;
  const inst = (state.overview && state.overview.instances) || [];
  if (!inst.length) {
    els.instanceList.replaceChildren(h("span", { class: "badge badge-warn", text: "无已配置实例" }));
    return;
  }
  els.instanceList.replaceChildren(...inst.map(u => h("button", {
    class: "chip chip-action mono", text: u,
    onClick: () => { if (els.mirrorInstance) els.mirrorInstance.value = u; },
  })));
}

export async function probeMirror(e) {
  if (e) e.preventDefault();
  const payload = {
    username: els.mirrorUsername.value.trim() || "nasa",
    query: els.mirrorQuery.value.trim() || "nasa",
    list_id: els.mirrorListId.value.trim() || undefined,
    limit: parseInt(els.mirrorLimit.value, 10) || 5,
    instance: els.mirrorInstance.value.trim() || undefined,
  };
  els.mirrorResult.replaceChildren(h("div", { class: "panel", text: "探测中..." }));
  try {
    const res = await apiPost("web/mirror/probe", payload);
    const results = res.results || [];
    if (!results.length) {
      els.mirrorResult.replaceChildren(h("div", { class: "panel", text: "未返回结果" }));
      return;
    }
    els.mirrorResult.replaceChildren(...results.map(r => {
      const checks = r.checks || {};
      return h("div", { class: "probe-result" }, [
        h("div", { class: "probe-instance-head" }, [
          h("span", { class: "mono", style: { fontWeight: 700 }, text: r.instance }),
          h("span", { class: `badge ${r.success ? "badge-ok" : "badge-danger"}`, text: r.success ? "全部可用" : "有异常" }),
        ]),
        h("div", { class: "probe-checks" }, [
          probeCheck("RSS", checks.rss_user),
          probeCheck("HTML", checks.html_user),
          probeCheck("搜索", checks.search),
          checks.list ? probeCheck("List", checks.list) : null,
        ]),
      ]);
    }));
  } catch (err) {
    els.mirrorResult.replaceChildren(h("div", { class: "alert error", text: `探测失败: ${err.message}` }));
  }
}

function probeCheck(label, item) {
  if (!item) return null;
  const ok = item.success;
  return h("div", { class: `probe-check ${ok ? "ok" : "fail"}` }, [
    iconEl(ok ? "check" : "alert", 14),
    h("span", { text: label }),
    ok ? h("span", { text: `${item.tweet_count || 0}条 ${Math.round(item.duration_ms || 0)}ms` }) : h("span", { text: item.error || "失败", style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }),
  ]);
}

/* --------------------------------------------------------------------------
   Cleanup Actions
   -------------------------------------------------------------------------- */
export function confirmClearCache() {
  openConfirm({
    title: "清理媒体缓存？", desc: "删除临时下载的图片与视频附件，不影响推送记录。",
    danger: true,
    action: () => withAction(async () => {
      const res = await apiPost("web/cache/clear");
      return { message: `缓存清理完毕: 删除 ${res.result?.removed || 0} 个文件` };
    }, "缓存已清理"),
  });
}

export function confirmClearSeen() {
  const sel = document.getElementById("seenSelect");
  const gid = sel ? sel.value : "";
  const isAll = !gid;
  openConfirm({
    title: isAll ? "重置全部推送记录？" : `重置分组 [${gid}] 推送记录？`,
    desc: "重置后下次检查可能将当前推文视为未推送，可能导致重复发送。",
    danger: true, confirmText: "确认重置",
    action: () => withAction(() => apiPost("web/seen/clear", isAll ? { confirm: "CLEAR_ALL" } : { group_id: gid }), "推送记录已重置"),
  });
}
