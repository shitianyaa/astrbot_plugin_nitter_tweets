// views.js - Overview, History Table, Mirror Probe & Danger Zone
import { state, els, h, withAction, openConfirm, apiGet, apiPost, copyText, showToast } from "./core.js";

/* --------------------------------------------------------------------------
   1. Overview Tab
   -------------------------------------------------------------------------- */
export function renderOverview() {
  if (!els.overviewView) return;
  const p = state.overview;
  if (!p) {
    els.overviewView.replaceChildren(h("div", { class: "panel", text: "正在加载控制台总览..." }));
    return;
  }

  const counts = p.counts || {};
  const scheduler = p.scheduler || {};
  const config = p.config_summary || {};
  const instances = p.instances || [];
  const attention = p.attention_items || [];

  // Metrics Bar
  const metrics = h("div", { class: "metrics-grid" }, [
    h("div", { class: "metric-card" }, [
      h("span", { class: "metric-label", text: "调度器" }),
      h("span", { class: "metric-value", text: scheduler.running ? "运行中" : "已停用" }),
    ]),
    h("div", { class: "metric-card" }, [
      h("span", { class: "metric-label", text: "订阅分组 (启用/总数)" }),
      h("span", { class: "metric-value", text: `${counts.enabled_groups || 0} / ${counts.groups || 0}` }),
    ]),
    h("div", { class: "metric-card" }, [
      h("span", { class: "metric-label", text: "博主订阅" }),
      h("span", { class: "metric-value", text: counts.watch_users || 0 }),
    ]),
    h("div", { class: "metric-card" }, [
      h("span", { class: "metric-label", text: "搜索订阅" }),
      h("span", { class: "metric-value", text: counts.watch_queries || 0 }),
    ]),
    h("div", { class: "metric-card" }, [
      h("span", { class: "metric-label", text: "List 订阅" }),
      h("span", { class: "metric-value", text: counts.watch_lists || 0 }),
    ]),
    h("div", { class: "metric-card" }, [
      h("span", { class: "metric-label", text: "推送目标 UMO" }),
      h("span", { class: "metric-value", text: counts.push_targets || 0 }),
    ]),
  ]);

  // Attention Items (异常直达)
  const attentionPanel = attention.length
    ? h("div", { class: "panel" }, [
        h("div", { class: "panel-head" }, [
          h("h3", { text: "待处理事项 / 异常诊断" }),
          h("span", { class: "badge warn", text: `${attention.length} 项需关注` })
        ]),
        h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } },
          attention.map(item => h("div", {
            class: `alert ${item.level === "error" ? "error" : "warn"}`,
            style: { display: "flex", justifyContent: "space-between", alignItems: "center" }
          }, [
            h("span", {}, [
              h("strong", { text: `${item.title}: ` }),
              item.detail
            ]),
            // 若包含 group_id 则支持点击直达
            item.group_id ? h("button", {
              class: "button small primary",
              text: "前往处理",
              onClick: () => {
                state.selectedGroupId = item.group_id;
                document.querySelector('[data-view="groups"]')?.click();
              }
            }) : null
          ]))
        )
      ])
    : null;

  // Config & Instances
  const configPanel = h("div", { class: "panel" }, [
    h("div", { class: "panel-head" }, [h("h3", { text: "运行摘要与自建实例" })]),
    h("div", { class: "editor-grid" }, [
      h("div", { class: "field" }, [
        h("span", { text: "已配置 Nitter 实例" }),
        instances.length
          ? h("div", { class: "chip-list" }, instances.map(url => h("span", { class: "chip mono", text: url })))
          : h("span", { class: "badge warn", text: "未配置任何实例" })
      ]),
      h("div", { class: "field" }, [
        h("span", { text: "核心调度参数" }),
        h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } }, [
          h("span", { class: "badge", text: `检查间隔: ${config.check_interval_minutes || 0}m` }),
          h("span", { class: "badge", text: `合并阈值: ${config.merge_tweet_threshold || 0}条` }),
          h("span", { class: "badge", text: `目标间隔: ${config.send_target_interval || 0}s` }),
          h("span", { class: "badge", text: `并发抓取: ${config.concurrent_fetch_enabled ? "开" : "关"}` }),
        ])
      ])
    ])
  ]);

  // Danger Zone (从原 cleanup tab 移入)
  const dangerZone = h("div", { class: "panel danger-zone" }, [
    h("div", { class: "panel-head" }, [
      h("h3", { text: "维护与缓存清理 (Danger Zone)" }),
      h("span", { class: "badge danger", text: "不可逆操作" })
    ]),
    h("div", { class: "cleanup-grid" }, [
      h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } }, [
        h("div", { style: { fontWeight: "500" }, text: "清理本地媒体缓存" }),
        h("div", { style: { fontSize: "11px", color: "var(--text-muted)" }, text: "删除临时下载的图片、视频和音视频文件。" }),
        h("button", {
          class: "button danger small",
          style: { width: "fit-content" },
          text: "清理所有媒体缓存",
          onClick: confirmClearCache
        })
      ]),
      h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } }, [
        h("div", { style: { fontWeight: "500" }, text: "重置推送状态 (Seen 游标)" }),
        h("div", { style: { fontSize: "11px", color: "var(--text-muted)" }, text: "清空已读记录可能导致历史推文再次推送，请谨慎操作。" }),
        h("div", { style: { display: "flex", gap: "6px" } }, [
          h("select", { id: "seenGroupSelectCore" }, [
            h("option", { value: "", text: "全部（所有分组）" }),
            ...state.groups.map(g => h("option", { value: g.group_id, text: `${g.name} (${g.group_id})` }))
          ]),
          h("button", {
            class: "button danger small",
            text: "重置 Seen 记录",
            onClick: confirmClearSeen
          })
        ])
      ])
    ])
  ]);

  els.overviewView.replaceChildren(metrics, attentionPanel, configPanel, dangerZone);
}

/* --------------------------------------------------------------------------
   2. Rail Status
   -------------------------------------------------------------------------- */
export function renderRailStatus() {
  const p = state.overview;
  if (!p) return;
  const s = p.scheduler || {};
  const counts = p.counts || {};

  if (els.railSchedulerStatus) {
    els.railSchedulerStatus.className = `status-indicator ${s.running ? "status-ok" : "status-warn"}`;
    els.railSchedulerStatus.replaceChildren(
      h("span", { class: "status-dot" }),
      h("span", { text: s.running ? "运行中" : "未启动" })
    );
  }
  if (els.railScheduleStatus) {
    els.railScheduleStatus.className = `status-indicator ${s.schedule_enabled ? "status-ok" : "status-warn"}`;
    els.railScheduleStatus.replaceChildren(
      h("span", { class: "status-dot" }),
      h("span", { text: s.schedule_enabled ? "已开启" : "已关闭" })
    );
  }
  if (els.railTargetStatus) {
    const invalid = counts.invalid_push_targets || 0;
    els.railTargetStatus.className = `status-indicator ${invalid > 0 ? "status-danger" : "status-ok"}`;
    els.railTargetStatus.replaceChildren(
      h("span", { class: "status-dot" }),
      h("span", { text: invalid > 0 ? `${invalid} 个异常` : "正常" })
    );
  }
}

/* --------------------------------------------------------------------------
   3. History Tab (Dense Data Table)
   -------------------------------------------------------------------------- */
export function renderHistory() {
  if (!els.historyView) return;
  const hData = state.history;
  const records = (hData && hData.records) || [];

  // 渲染筛选下拉
  if (els.historyGroupSelect && els.historyGroupSelect.children.length <= 1) {
    els.historyGroupSelect.replaceChildren(
      h("option", { value: "", text: "所有分组" }),
      ...state.groups.map(g => h("option", { value: g.group_id, text: g.name }))
    );
  }

  // 翻页标签
  if (els.historyPageLabel && hData) {
    const page = hData.page || 1;
    const total = hData.total_pages || 1;
    els.historyPageLabel.textContent = `${page} / ${total} 页 (${hData.total_count || 0} 条)`;
  }
  if (els.historyPrevBtn && hData) els.historyPrevBtn.disabled = !hData.has_prev;
  if (els.historyNextBtn && hData) els.historyNextBtn.disabled = !hData.has_next;

  if (!records.length) {
    els.historyContent.replaceChildren(h("div", { class: "panel", text: "暂无符合条件的推送历史。" }));
    return;
  }

  // 紧凑数据表格
  const table = h("table", { class: "data-table" }, [
    h("thead", {}, [
      h("tr", {}, [
        h("th", { style: { width: "120px" }, text: "推送时间" }),
        h("th", { style: { width: "100px" }, text: "分组" }),
        h("th", { style: { width: "110px" }, text: "订阅源" }),
        h("th", { text: "内容摘要" }),
        h("th", { style: { width: "100px" }, text: "送达状态" }),
        h("th", { style: { width: "80px", textAlign: "right" }, text: "操作" }),
      ])
    ]),
    h("tbody", {}, records.map(r => {
      const isSuccess = r.delivery_status === "success";
      const isPartial = r.delivery_status === "partial_failed";
      const statusBadge = h("span", {
        class: `badge ${isSuccess ? "ok" : isPartial ? "warn" : "danger"}`,
        text: isSuccess ? "成功" : isPartial ? "部分失败" : "失败"
      });

      return h("tr", {}, [
        h("td", { class: "mono", style: { color: "var(--text-muted)" }, text: r.pushed_at || "-" }),
        h("td", {}, [h("span", { class: "badge", text: r.group_name || r.group_id })]),
        h("td", { class: "mono", text: `@${r.username}` }),
        h("td", { style: { maxWidth: "340px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, title: r.text_preview }, [
          r.original_link ? h("a", { href: r.original_link, target: "_blank", text: r.status_id, class: "mono", style: { marginRight: "6px" } }) : null,
          r.text_preview || "(无文字)"
        ]),
        h("td", {}, [statusBadge]),
        h("td", { style: { textAlign: "right" } }, [
          h("button", {
            class: "button ghost small",
            text: "重推",
            onClick: () => replayHistory(r.id, r.replay_target_options)
          })
        ])
      ]);
    }))
  ]);

  els.historyContent.replaceChildren(table);
}

export async function loadHistoryPage(offsetDelta) {
  if (!state.history) return;
  const targetOffset = offsetDelta < 0 ? state.history.prev_offset : state.history.next_offset;
  if (targetOffset === null || targetOffset === undefined) return;
  state.historyOffset = targetOffset;
  state.history = await apiGet("web/history", {
    group_id: state.historyGroupId || undefined,
    username: state.historyUsername || undefined,
    limit: state.historyLimit,
    offset: state.historyOffset,
  });
  renderHistory();
}

export async function detectHistoryOrphans() {
  await withAction(async () => {
    const res = await apiGet("web/history/orphans");
    const orphans = res.orphans || [];
    if (!orphans.length) {
      els.historyOrphanResult.replaceChildren(h("div", { class: "badge ok", text: "未检测到已删除分组的残留历史。" }));
      return;
    }
    els.historyOrphanResult.replaceChildren(
      h("div", { class: "panel", style: { gap: "8px" } }, [
        h("span", { style: { fontWeight: "500" }, text: `发现 ${orphans.length} 个废弃分组的残留记录：` }),
        h("div", { class: "chip-list" }, orphans.map(o => h("span", { class: "chip", style: { display: "inline-flex", gap: "6px" } }, [
          `${o.group_id} (${o.record_count}条)`,
          h("button", {
            class: "button danger small",
            text: "删除",
            onClick: () => confirmDeleteHistoryOrphan(o.group_id)
          })
        ])))
      ])
    );
  }, "检测完成", { reload: false });
}

function confirmDeleteHistoryOrphan(groupId) {
  openConfirm({
    title: `删除废弃分组 [${groupId}] 的历史记录？`,
    desc: "该分组已不存在于当前配置中。删除后所有相关推送记录将彻底清除。",
    danger: true,
    action: () => withAction(() => apiPost("web/history/orphans/delete", { group_id: groupId, confirm: "DELETE" }), "删除成功", {
      reload: false,
      rerender: detectHistoryOrphans
    })
  });
}

function replayHistory(recordId, options = []) {
  openConfirm({
    title: "重推此推文记录",
    desc: options && options.length
      ? `即将重推至 ${options.length} 个历史目标。确认执行？`
      : "确认重推此记录到原目标？",
    action: () => withAction(() => apiPost("web/history/replay", { record_id: recordId }), "重推已触发")
  });
}

/* --------------------------------------------------------------------------
   4. Mirror Probe Tab
   -------------------------------------------------------------------------- */
export function renderMirrorBase() {
  if (!els.instanceList) return;
  const p = state.overview;
  const instances = (p && p.instances) || [];
  if (!instances.length) {
    els.instanceList.replaceChildren(h("span", { class: "badge warn", text: "无已配置实例" }));
    return;
  }
  els.instanceList.replaceChildren(...instances.map(inst => h("button", {
    type: "button",
    class: "chip chip-action mono",
    text: inst,
    onClick: () => { if (els.mirrorInstance) els.mirrorInstance.value = inst; }
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

  els.mirrorResult.replaceChildren(h("div", { class: "panel", text: "正在探测实例能力，请稍候..." }));
  try {
    const res = await apiPost("web/mirror/probe", payload);
    const results = res.results || [];
    if (!results.length) {
      els.mirrorResult.replaceChildren(h("div", { class: "panel", text: "未返回任何实例探测结果。" }));
      return;
    }

    els.mirrorResult.replaceChildren(h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
      results.map(r => {
        const checks = r.checks || {};
        return h("div", { class: "panel" }, [
          h("div", { class: "panel-head" }, [
            h("span", { class: "mono", style: { fontWeight: "600" }, text: r.instance }),
            h("span", { class: `badge ${r.success ? "ok" : "danger"}`, text: r.success ? "全部可用" : "存在异常" })
          ]),
          h("div", { style: { display: "flex", gap: "12px", flexWrap: "wrap", fontSize: "12px" } }, [
            renderCheckItem("RSS 用户", checks.rss_user),
            renderCheckItem("HTML 用户", checks.html_user),
            renderCheckItem("搜索", checks.search),
            checks.list ? renderCheckItem("List", checks.list) : null
          ])
        ]);
      })
    ));
  } catch (err) {
    els.mirrorResult.replaceChildren(h("div", { class: "alert error", text: `探测失败: ${err.message}` }));
  }
}

function renderCheckItem(label, item) {
  if (!item) return null;
  const ok = item.success;
  return h("div", { class: `badge ${ok ? "ok" : "danger"}`, style: { display: "inline-flex", gap: "6px" } }, [
    h("span", { style: { fontWeight: "600" }, text: label }),
    h("span", { text: ok ? `${item.tweet_count || 0}条 (${item.duration_ms || 0}ms)` : (item.error || "失败") })
  ]);
}

/* --------------------------------------------------------------------------
   5. Cleanup Operations
   -------------------------------------------------------------------------- */
export function confirmClearCache() {
  openConfirm({
    title: "清理媒体缓存？",
    desc: "将删除本地保存的推文图片与视频附件临时文件。不影响已推送的消息和数据库记录。",
    danger: true,
    action: () => withAction(async () => {
      const res = await apiPost("web/cache/clear");
      const r = res.result || {};
      return { message: `缓存清理完毕: 删除文件 ${r.removed || 0} 个` };
    }, "缓存清理完成")
  });
}

export function confirmClearSeen() {
  const sel = document.getElementById("seenGroupSelectCore");
  const gid = sel ? sel.value : "";
  const isAll = !gid;

  openConfirm({
    title: isAll ? "重置全部推送记录 (Seen)？" : `重置分组 [${gid}] 的推送记录？`,
    desc: "重置后，下次检查将把当前最新推文视为未推送，可能引起短时间内重复发送！请确认是否继续。",
    danger: true,
    confirmText: "确认重置",
    action: () => withAction(() => {
      // 严格遵守后端参数规范：清全部传 confirm="CLEAR_ALL"，单组只传 group_id
      return apiPost("web/seen/clear", isAll ? { confirm: "CLEAR_ALL" } : { group_id: gid });
    }, "推送记录已重置")
  });
}
