const bridge = window.AstrBotPluginPage;

const state = {
  view: "overview",
  loading: false,
  actionBusy: false,
  overview: null,
  groups: [],
  pending: null,
  selectedGroupId: "",
  pendingGroupId: "",
  seenGroupId: "",
  pendingAction: null,
  lastUpdated: "",
};

const els = {
  tabs: document.querySelectorAll(".tab"),
  views: document.querySelectorAll(".view"),
  refreshBtn: document.getElementById("refreshBtn"),
  lastUpdated: document.getElementById("lastUpdated"),
  alert: document.getElementById("alert"),
  overviewView: document.getElementById("overviewView"),
  groupsContent: document.getElementById("groupsContent"),
  groupActionSelect: document.getElementById("groupActionSelect"),
  subscriptionInput: document.getElementById("subscriptionInput"),
  importBtn: document.getElementById("importBtn"),
  deleteBtn: document.getElementById("deleteBtn"),
  pendingGroupSelect: document.getElementById("pendingGroupSelect"),
  pendingRefreshBtn: document.getElementById("pendingRefreshBtn"),
  publishSelectedBtn: document.getElementById("publishSelectedBtn"),
  pendingContent: document.getElementById("pendingContent"),
  mirrorForm: document.getElementById("mirrorForm"),
  mirrorUsername: document.getElementById("mirrorUsername"),
  mirrorLimit: document.getElementById("mirrorLimit"),
  mirrorInstance: document.getElementById("mirrorInstance"),
  mirrorProbeBtn: document.getElementById("mirrorProbeBtn"),
  instanceList: document.getElementById("instanceList"),
  mirrorResult: document.getElementById("mirrorResult"),
  clearCacheBtn: document.getElementById("clearCacheBtn"),
  clearSeenBtn: document.getElementById("clearSeenBtn"),
  seenGroupSelect: document.getElementById("seenGroupSelect"),
  cacheResult: document.getElementById("cacheResult"),
  seenResult: document.getElementById("seenResult"),
  confirmDialog: document.getElementById("confirmDialog"),
  confirmKicker: document.getElementById("confirmKicker"),
  confirmTitle: document.getElementById("confirmTitle"),
  confirmDesc: document.getElementById("confirmDesc"),
  cancelConfirmBtn: document.getElementById("cancelConfirmBtn"),
  confirmActionBtn: document.getElementById("confirmActionBtn"),
};

const icons = {
  refresh:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a9 9 0 0 1-15.6 6.1"/><path d="M3 12a9 9 0 0 1 15.6-6.1"/><path d="M18 3v4h-4"/><path d="M6 21v-4h4"/></svg>',
  plus:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14"/><path d="M5 12h14"/></svg>',
  trash:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>',
  send:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>',
  probe:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.1 0l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1"/><path d="M14 11a5 5 0 0 0-7.1 0l-2 2a5 5 0 0 0 7.1 7.1l1.1-1.1"/></svg>',
  erase:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 21-4-4 10-10 4 4L7 21Z"/><path d="m14 6 4-4 4 4-4 4"/><path d="M16 21h6"/></svg>',
  play:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7Z"/></svg>',
};

function mountIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    node.innerHTML = icons[node.dataset.icon] || "";
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function apiResult(result) {
  if (!result) return {};
  if (result.success === false) {
    throw new Error(result.error || "请求失败");
  }
  return result;
}

async function apiGet(endpoint, params) {
  return apiResult(await bridge.apiGet(endpoint, params));
}

async function apiPost(endpoint, body) {
  return apiResult(await bridge.apiPost(endpoint, body || {}));
}

function showAlert(message, type = "success") {
  els.alert.textContent = message;
  els.alert.className = `alert ${type}`;
  els.alert.hidden = false;
}

function hideAlert() {
  els.alert.hidden = true;
  els.alert.textContent = "";
}

function setBusy(isBusy) {
  state.loading = isBusy;
  const noGroups = !state.groups.length;
  const groupDependentButtons = [
    els.importBtn,
    els.deleteBtn,
    els.pendingRefreshBtn,
    els.publishSelectedBtn,
  ];
  [
    els.refreshBtn,
    els.importBtn,
    els.deleteBtn,
    els.pendingRefreshBtn,
    els.publishSelectedBtn,
    els.mirrorProbeBtn,
    els.clearCacheBtn,
    els.clearSeenBtn,
  ].forEach((button) => {
    if (button) {
      button.disabled =
        isBusy ||
        state.actionBusy ||
        (noGroups && groupDependentButtons.includes(button));
    }
  });
}

function formatBool(value) {
  return value ? "已开启" : "已关闭";
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

function formatTime(value) {
  if (!value) return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  const date = new Date(number * 1000);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function compactList(values, empty = "无") {
  const list = Array.isArray(values) ? values.filter(Boolean) : [];
  if (!list.length) return `<span class="muted">${empty}</span>`;
  return list.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("");
}

function selectedGroupId() {
  return els.groupActionSelect.value || state.selectedGroupId || "";
}

function selectedPendingGroupId() {
  return els.pendingGroupSelect.value || state.pendingGroupId || "";
}

function groupOptions(includeAll = false) {
  const allOption = includeAll ? '<option value="">全部分组</option>' : "";
  return (
    allOption +
    state.groups
      .map(
        (group) =>
          `<option value="${escapeHtml(group.group_id)}">${escapeHtml(group.name)} (${escapeHtml(group.group_id)})</option>`,
      )
      .join("")
  );
}

function syncSelectors() {
  const currentGroup = selectedGroupId() || state.groups[0]?.group_id || "";
  const currentPending = selectedPendingGroupId() || currentGroup;
  const currentSeen = els.seenGroupSelect.value || state.seenGroupId || "";
  els.groupActionSelect.innerHTML = groupOptions(false);
  els.pendingGroupSelect.innerHTML = groupOptions(false);
  els.seenGroupSelect.innerHTML = groupOptions(true);
  els.groupActionSelect.value = currentGroup;
  els.pendingGroupSelect.value = currentPending;
  els.seenGroupSelect.value = currentSeen;
  if (!els.groupActionSelect.value && state.groups[0]) {
    els.groupActionSelect.value = state.groups[0].group_id;
  }
  if (!els.pendingGroupSelect.value && state.groups[0]) {
    els.pendingGroupSelect.value = state.groups[0].group_id;
  }
  state.selectedGroupId = els.groupActionSelect.value;
  state.pendingGroupId = els.pendingGroupSelect.value;
  state.seenGroupId = els.seenGroupSelect.value;
}

function renderOverview() {
  const payload = state.overview;
  if (!payload) {
    els.overviewView.innerHTML = emptyState("正在加载概览");
    return;
  }
  const counts = payload.counts || {};
  const scheduler = payload.scheduler || {};
  const features = payload.features || {};
  const configSummary = payload.config_summary || {};
  const attentionItems = payload.attention_items || [];
  const stats = [
    ["调度器", scheduler.running ? "运行中" : "未运行"],
    ["后台检查", scheduler.schedule_enabled ? "已开启" : "已关闭"],
    ["用户分组", `${formatNumber(counts.groups)} / 启用 ${formatNumber(counts.enabled_groups)}`],
    ["关注账号", formatNumber(counts.watch_users)],
    ["推送目标", formatNumber(counts.push_targets)],
    ["无效推送目标", formatNumber(counts.invalid_push_targets)],
    ["待发布推文", formatNumber(counts.pending_tweets)],
    ["失败待发布", formatNumber(counts.failed_pending_tweets)],
  ];
  const featureRows = [
    ["图片附件", formatBool(features.images)],
    ["视频/GIF", formatBool(features.videos)],
    ["翻译", formatBool(features.translation)],
    ["AI 识图", formatBool(features.ai_vision)],
    ["AI 评论", formatBool(features.ai_comment)],
    ["暂存发布分组", formatNumber(features.deferred_publish_groups)],
  ];
  const configRows = [
    ["Nitter 实例", formatNumber(configSummary.nitter_instance_count)],
    ["手动默认数量", formatNumber(configSummary.default_limit)],
    ["后台拉取数量", formatNumber(configSummary.scheduled_fetch_limit)],
    ["检查间隔", `${formatNumber(configSummary.check_interval_minutes)} 分钟`],
    ["合并阈值", formatNumber(configSummary.merge_tweet_threshold)],
    ["目标间隔", `${formatNumber(configSummary.send_target_interval)} 秒`],
    ["暂存批量", formatNumber(configSummary.deferred_publish_batch_limit)],
    ["并发拉取", formatBool(configSummary.concurrent_fetch_enabled)],
    ["并发准备", formatBool(configSummary.concurrent_prepare_enabled)],
  ];
  els.overviewView.innerHTML = `
    <div class="metrics-grid">
      ${stats
        .map(
          ([label, value]) => `
            <div class="metric">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(value)}</strong>
            </div>
          `,
        )
        .join("")}
    </div>
    <div class="two-column">
      <div class="panel">
        <h2>运行状态</h2>
        <table class="info-table">
          <tbody>
            <tr><th>原始关注项</th><td>${formatNumber(counts.raw_watch_users)}</td></tr>
            <tr><th>重复关注项</th><td>${formatNumber(counts.duplicate_watch_users)}</td></tr>
            <tr><th>无效关注项</th><td>${formatNumber(counts.invalid_watch_users)}</td></tr>
            <tr><th>暂存媒体</th><td>${formatNumber(counts.pending_media)}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h2>功能开关</h2>
        <table class="info-table">
          <tbody>
            ${featureRows
              .map(
                ([label, value]) =>
                  `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`,
              )
              .join("")}
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h2>配置摘要</h2>
        <table class="info-table">
          <tbody>
            ${configRows
              .map(
                ([label, value]) =>
                  `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`,
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </div>
    <div class="panel attention-panel">
      <h2>需要关注</h2>
      <div class="attention-list">
        ${attentionItems
          .map(
            (item) => `
              <div class="attention-item ${escapeHtml(item.level || "info")}">
                <strong>${escapeHtml(item.title || "")}</strong>
                <span>${escapeHtml(item.detail || "")}</span>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderGroups() {
  if (!state.groups.length) {
    els.groupsContent.innerHTML = emptyState("暂无用户分组");
    return;
  }
  els.groupsContent.innerHTML = state.groups
    .map(
      (group) => `
        <article class="group-row">
          <div class="group-main">
            <div>
              <h2>${escapeHtml(group.name)}</h2>
              <p>${escapeHtml(group.group_id)} · ${group.enabled ? "启用" : "停用"}</p>
              ${
                (group.attention_items || []).length
                  ? `
                    <div class="group-alerts">
                      ${(group.attention_items || [])
                        .map(
                          (item) => `
                            <span class="attention-badge ${escapeHtml(item.level || "info")}" title="${escapeHtml(item.detail || "")}">
                              ${escapeHtml(item.title || "")}
                            </span>
                          `,
                        )
                        .join("")}
                    </div>
                  `
                  : ""
              }
            </div>
            <div class="row-actions">
              <button class="button secondary small" type="button" data-check-group="${escapeHtml(group.group_id)}" ${group.enabled ? "" : 'disabled title="分组停用时不能立即检查"'}>
                <span class="icon" data-icon="play"></span>
                立即检查
              </button>
              <button class="button primary small" type="button" data-publish-group="${escapeHtml(group.group_id)}">
                <span class="icon" data-icon="send"></span>
                发布暂存
              </button>
            </div>
          </div>
          <div class="group-stats">
            <span>关注账号 <strong>${formatNumber(group.watch_user_count)}</strong></span>
            <span>推送目标 <strong>${formatNumber(group.push_target_count)}</strong></span>
            <span>无效推送目标 <strong>${formatNumber(group.invalid_push_target_count)}</strong></span>
            <span>待发布 <strong>${formatNumber(group.pending_summary?.pending_count)}</strong></span>
          </div>
          <div class="details-grid">
            <div><b>关注账号</b><div class="chip-list">${compactList(group.watch_users)}</div></div>
            <div><b>无效关注账号</b><div class="chip-list bad">${compactList(group.invalid_watch_users)}</div></div>
            <div><b>重复关注项</b><div class="chip-list warn">${compactList(group.duplicate_watch_users)}</div></div>
            <div><b>推送目标</b><div class="chip-list mono">${compactList(group.push_targets)}</div></div>
            <div><b>无效推送目标</b><div class="chip-list bad">${compactList(group.invalid_push_targets)}</div></div>
            <div><b>分组别名</b><div class="chip-list">${compactList(group.aliases)}</div></div>
          </div>
          <table class="info-table compact-table">
            <tbody>
              <tr><th>间隔检查</th><td>${formatBool(group.interval_check_enabled)} / ${formatNumber(group.check_interval_minutes)} 分钟</td></tr>
              <tr><th>每日检查</th><td>${compactList(group.daily_check_times)}</td></tr>
              <tr><th>暂存发布</th><td>${formatBool(group.deferred_publish_enabled)} / ${compactList(group.deferred_publish_times)}</td></tr>
              <tr><th>纯文本过滤</th><td>${formatBool(group.filter_plain_text_enabled)}</td></tr>
            </tbody>
          </table>
        </article>
      `,
    )
    .join("");
  mountIcons(els.groupsContent);
}

function renderPending() {
  const payload = state.pending;
  if (!payload) {
    els.pendingContent.innerHTML = emptyState("正在加载暂存队列");
    return;
  }
  const summaries = payload.summaries || [];
  const records = payload.records || [];
  els.pendingContent.innerHTML = `
    <div class="summary-strip">
      ${summaries
        .map(
          (item) => `
            <div class="summary-item">
              <span>${escapeHtml(item.group_name)}</span>
              <strong>${formatNumber(item.pending_count)}</strong>
              <small>失败 ${formatNumber(item.failed_count)} · 媒体 ${formatNumber(item.media_count)}</small>
              <small>最早 ${escapeHtml(formatTime(item.oldest_created_at))} · 最新 ${escapeHtml(formatTime(item.newest_created_at))}</small>
              ${
                (item.user_counts || []).length
                  ? `
                    <div class="summary-users" aria-label="账号队列分布">
                      ${(item.user_counts || [])
                        .map(
                          (entry) =>
                            `<span>@${escapeHtml(entry.username)} ${formatNumber(entry.count)}</span>`,
                        )
                        .join("")}
                    </div>
                  `
                  : ""
              }
            </div>
          `,
        )
        .join("")}
    </div>
    ${
      records.length
        ? `
          <div class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>账号</th>
                  <th>推文</th>
                  <th>入队</th>
                  <th>计划</th>
                  <th>失败</th>
                  <th>已送达推送目标</th>
                  <th>媒体</th>
                </tr>
              </thead>
              <tbody>
                ${records
                  .map(
                    (row) => `
                      <tr>
                        <td>@${escapeHtml(row.username)}</td>
                        <td>
                          <a href="${escapeHtml(row.original_link)}" target="_blank" rel="noreferrer">${escapeHtml(row.status_id || row.original_link)}</a>
                          <span>${escapeHtml(row.text_preview || "")}</span>
                        </td>
                        <td>${escapeHtml(formatTime(row.created_at))}</td>
                        <td>${escapeHtml(formatTime(row.scheduled_at))}</td>
                        <td>${formatNumber(row.fail_count)}${row.last_error ? `<span class="error-text">${escapeHtml(row.last_error)}</span>` : ""}</td>
                        <td>${formatNumber(row.delivered_target_count)}</td>
                        <td>${formatNumber(row.media_count)} ${escapeHtml((row.media_kinds || []).join(", "))}</td>
                      </tr>
                    `,
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        `
        : emptyState("当前分组没有待发布推文")
    }
  `;
}

function renderMirrorBase() {
  const instances = state.overview?.instances || [];
  const fromGroups = state.groups.length ? state.groups : [];
  if (!els.mirrorInstance.value && instances.length) {
    els.mirrorInstance.value = instances[0];
  }
  els.instanceList.innerHTML = instances.length
    ? compactList(instances)
    : `<span class="muted">${fromGroups.length ? "未返回实例列表" : "未加载"}</span>`;
}

function renderCleanupSelectors() {
  els.seenGroupSelect.innerHTML = groupOptions(true);
  els.seenGroupSelect.value = state.seenGroupId;
  state.seenGroupId = els.seenGroupSelect.value;
}

function emptyState(text) {
  return `<div class="empty"><strong>${escapeHtml(text)}</strong></div>`;
}

function renderAll() {
  syncSelectors();
  renderOverview();
  renderGroups();
  renderPending();
  renderMirrorBase();
  renderCleanupSelectors();
  mountIcons();
}

async function loadPending(groupId = selectedPendingGroupId()) {
  state.pendingGroupId = groupId;
  state.pending = await apiGet("web/pending", { group_id: groupId, limit: 80 });
  renderPending();
}

async function reloadAll() {
  setBusy(true);
  hideAlert();
  try {
    await bridge.ready();
    const [overview, groups] = await Promise.all([
      apiGet("web/overview"),
      apiGet("web/groups"),
    ]);
    state.overview = overview;
    state.groups = Array.isArray(groups.groups) ? groups.groups : [];
    if (!state.selectedGroupId && state.groups[0]) {
      state.selectedGroupId = state.groups[0].group_id;
      state.pendingGroupId = state.groups[0].group_id;
    }
    syncSelectors();
    await loadPending(state.pendingGroupId);
    state.lastUpdated = new Date().toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    els.lastUpdated.textContent = `更新于 ${state.lastUpdated}`;
    renderAll();
    return true;
  } catch (error) {
    showAlert(error.message || "加载失败", "error");
    return false;
  } finally {
    setBusy(false);
  }
}

function switchView(view) {
  state.view = view;
  els.tabs.forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-pressed", String(active));
  });
  els.views.forEach((section) => {
    section.classList.toggle("active", section.id === `${view}View`);
  });
}

function openConfirm({ kicker = "确认操作", title, desc, confirmText, danger = true, action }) {
  state.pendingAction = action;
  els.confirmKicker.textContent = kicker;
  els.confirmTitle.textContent = title;
  els.confirmDesc.textContent = desc;
  els.confirmActionBtn.textContent = confirmText || "确认";
  els.confirmActionBtn.classList.toggle("danger", danger);
  els.confirmDialog.hidden = false;
  els.cancelConfirmBtn.focus();
}

function closeConfirm() {
  els.confirmDialog.hidden = true;
  state.pendingAction = null;
}

async function withAction(action, successText, options = {}) {
  state.actionBusy = true;
  setBusy(true);
  hideAlert();
  try {
    const result = await action();
    const successMessage = successText || result.message || "操作完成";
    if (options.reload !== false) {
      const reloaded = await reloadAll();
      if (reloaded === false) {
        return result;
      }
    }
    showAlert(successMessage, "success");
    return result;
  } catch (error) {
    showAlert(error.message || "操作失败", "error");
    return null;
  } finally {
    state.actionBusy = false;
    setBusy(false);
  }
}

async function runGroupCheck(groupId) {
  await withAction(
    () => apiPost("web/check", { group_id: groupId }),
    "检查完成",
  );
}

function confirmPublish(groupId) {
  const group = state.groups.find((item) => item.group_id === groupId);
  openConfirm({
    kicker: "发布暂存",
    title: "发布暂存队列？",
    desc: `${group?.name || groupId} 的待发布推文会发送到该分组的推送目标。`,
    confirmText: "发布",
    danger: false,
    action: () =>
      withAction(
        () => apiPost("web/publish", { group_id: groupId }),
        "发布完成",
      ),
  });
}

function confirmDeleteSubscriptions() {
  const entries = els.subscriptionInput.value.trim();
  const groupId = selectedGroupId();
  if (!entries) {
    showAlert("请填写要删除的关注账号", "error");
    return;
  }
  openConfirm({
    kicker: "删除关注账号",
    title: "删除关注账号？",
    desc: "只会从所选用户分组移除关注账号，不会删除推送目标、暂存队列或媒体文件。",
    confirmText: "删除",
    action: () =>
      withAction(async () => {
        const result = await apiPost("web/subscriptions/delete", {
          group_id: groupId,
          entries,
        });
        els.subscriptionInput.value = "";
        return result;
      }),
  });
}

async function importSubscriptions() {
  const entries = els.subscriptionInput.value.trim();
  if (!entries) {
    showAlert("请填写要导入的关注账号", "error");
    return;
  }
  await withAction(async () => {
    const result = await apiPost("web/subscriptions/import", {
      group_id: selectedGroupId(),
      entries,
    });
    els.subscriptionInput.value = "";
    return result;
  });
}

async function probeMirror(event) {
  event.preventDefault();
  state.actionBusy = true;
  setBusy(true);
  hideAlert();
  try {
    const result = await apiPost("web/mirror/probe", {
      username: els.mirrorUsername.value.trim(),
      limit: Number(els.mirrorLimit.value || 5),
      instance: els.mirrorInstance.value.trim(),
    });
    els.mirrorResult.innerHTML = `
      <div class="panel">
        <h2>@${escapeHtml(result.username)} · ${escapeHtml(result.instance)}</h2>
        <p class="muted">获取 ${formatNumber(result.tweet_count)} 条</p>
        <div class="probe-list">
          ${(result.tweets || [])
            .map(
              (tweet) => `
                <a href="${escapeHtml(tweet.link)}" target="_blank" rel="noreferrer">
                  <strong>${escapeHtml(tweet.status_id || tweet.link)}</strong>
                  <span>${escapeHtml(tweet.text_preview || "")}</span>
                </a>
              `,
            )
            .join("")}
        </div>
      </div>
    `;
  } catch (error) {
    showAlert(error.message || "镜像测试失败", "error");
  } finally {
    state.actionBusy = false;
    setBusy(false);
  }
}

function confirmClearCache() {
  openConfirm({
    kicker: "缓存清理",
    title: "清理媒体缓存？",
    desc: "普通媒体缓存会被删除，暂存队列使用的媒体会保留。",
    confirmText: "清理",
    action: () =>
      withAction(async () => {
        const result = await apiPost("web/cache/clear");
        const detail = result.result || {};
        const parts = [
          `已删除 ${formatNumber(detail.removed)} 个`,
          `图片 ${formatNumber(detail.removed_images)}`,
          `视频 ${formatNumber(detail.removed_videos)}`,
          `其他 ${formatNumber(detail.removed_other)}`,
          `空目录 ${formatNumber(detail.removed_empty_dirs)}`,
          `跳过目录 ${formatNumber(detail.skipped_dirs)}`,
          `失败 ${formatNumber(detail.failed)}`,
        ];
        els.cacheResult.textContent = parts.join("，");
        return result;
      }, "媒体缓存清理完成"),
  });
}

function confirmClearSeen() {
  const groupId = els.seenGroupSelect.value;
  const group = state.groups.find((item) => item.group_id === groupId);
  openConfirm({
    kicker: "推送记录",
    title: "清理推送记录？",
    desc: "不会删除关注账号、推送目标、暂存队列或媒体文件，但旧推文可能重新参与检查。",
    confirmText: "清理",
    action: () =>
      withAction(async () => {
        const result = await apiPost("web/seen/clear", { group_id: groupId });
        els.seenResult.textContent = `${group?.name || "全部分组"}：删除 ${formatNumber(result.deleted)} 条`;
        return result;
      }, "推送记录清理完成"),
  });
}

function bindEvents() {
  els.tabs.forEach((tab) => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  });
  els.refreshBtn.addEventListener("click", reloadAll);
  els.importBtn.addEventListener("click", importSubscriptions);
  els.deleteBtn.addEventListener("click", confirmDeleteSubscriptions);
  els.pendingRefreshBtn.addEventListener("click", () =>
    withAction(
      () => loadPending(selectedPendingGroupId()),
      "暂存队列已刷新",
      { reload: false },
    ),
  );
  els.publishSelectedBtn.addEventListener("click", () =>
    confirmPublish(selectedPendingGroupId()),
  );
  els.pendingGroupSelect.addEventListener("change", (event) => {
    state.pendingGroupId = event.target.value;
    withAction(
      () => loadPending(state.pendingGroupId),
      "暂存队列已刷新",
      { reload: false },
    );
  });
  els.groupActionSelect.addEventListener("change", (event) => {
    state.selectedGroupId = event.target.value;
  });
  els.seenGroupSelect.addEventListener("change", (event) => {
    state.seenGroupId = event.target.value;
  });
  els.groupsContent.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (target.dataset.checkGroup) runGroupCheck(target.dataset.checkGroup);
    if (target.dataset.publishGroup) confirmPublish(target.dataset.publishGroup);
  });
  els.mirrorForm.addEventListener("submit", probeMirror);
  els.clearCacheBtn.addEventListener("click", confirmClearCache);
  els.clearSeenBtn.addEventListener("click", confirmClearSeen);
  els.cancelConfirmBtn.addEventListener("click", closeConfirm);
  els.confirmDialog.addEventListener("click", (event) => {
    if (event.target === els.confirmDialog) closeConfirm();
  });
  els.confirmActionBtn.addEventListener("click", async () => {
    const action = state.pendingAction;
    closeConfirm();
    if (typeof action === "function") await action();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !els.confirmDialog.hidden) closeConfirm();
  });
}

mountIcons();
bindEvents();
reloadAll();
