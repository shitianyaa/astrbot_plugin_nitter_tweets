'use strict';
/* Dashboard 分片（经典 script 按序加载）：作用域化数据刷新
加载顺序见 index.html 与 core.js 头注。 */

/* ==========================================================================
   9. 数据加载：作用域化刷新（替代“任何动作都全量 reload”）
   reloadAll 只用于 boot 与手动刷新；动作收尾按当前视图刷新对应数据，
   内容保留在原地（stale-while-revalidate），不再先清屏再等数据。
   ========================================================================== */
async function reloadOverviewData() {
  state.overview = await apiGet("web/overview");
  markData("overview");
}

/* 分组 + 黑名单 + 概览一起拉（目标黑名单随 targets 区块展示，概览驱动健康徽标
   与顶部 pill）；count/attention 变化联动总览与历史下拉 */
async function reloadGroupState() {
  const [groups, blacklists, overview] = await Promise.all([
    apiGet("web/groups"), apiGet("web/target-blacklists"), apiGet("web/overview"),
  ]);
  state.groups = groups.groups || [];
  state.targetBlacklists = blacklists.target_blacklists || [];
  state.overview = overview;
  if (!state.selectedGroupId || !state.groups.some(g => g.group_id === state.selectedGroupId)) {
    state.selectedGroupId = state.groups[0]?.group_id || "";
  }
  syncGroupDrafts();
  markData("groups");
  markData("overview");
}

async function reloadConfigState() {
  const cf = await apiGet("web/config/schema");
  state.config = cf;
  state.configError = false;
  try {
    const pv = await apiGet("web/config/providers");
    state.providers = pv.providers || [];
  } catch (err) {
    // Provider 下拉数据源:失败静默降级为空列表(仅支持"留空 = 自动选择")
    state.providers = [];
  }
  buildConfigIndex();
  markData("config");
}

async function refreshHistoryData() {
  const data = await apiGet("web/history", {
    group_id: state.historyGroupId || undefined,
    username: state.historyUsername || undefined,
    limit: state.historyLimit, offset: state.historyOffset,
    status: state.historyStatus || undefined,
  });
  state.history = data;
  state.historySelection.clear();
  markData("history");
  return data;
}

/* 总览「最新推送记录」：固定取全局最新的 5 条（无筛选、offset=0）。
   此前直接切历史页快照的前 5 条，历史页一翻页或加筛选，总览显示的行就与
   state.history 脱钩，点开时 openHistoryDetail 的 find 落空而静默无反应。 */
const RECENT_PUSH_LIMIT = 5;

async function refreshRecentPushes() {
  const data = await apiGet("web/history", { limit: RECENT_PUSH_LIMIT, offset: 0 });
  state.recentPushes = data.records || [];
  markData("recent");
  return state.recentPushes;
}

async function refreshViewData(view) {
  try {
    if (view === "groups") {
      // 分组增删会联动清理历史，概览计数也随之变化：三路并行刷新
      const results = await Promise.allSettled([
        reloadGroupState(), refreshHistoryData(), refreshRecentPushes(),
      ]);
      const failed = results.find(r => r.status === "rejected");
      if (failed) throw failed.reason;
      return true;
    }
    if (view === "config") { await reloadConfigState(); return true; }
    if (view === "history") { await refreshHistoryData(); return true; }
    if (view === "storage") {
      // 存储运维只用概览里的 maintenance，不需要再拉最近推送
      await reloadOverviewData();
      return true;
    }
    await Promise.all([reloadOverviewData(), refreshRecentPushes()]);
    return true;
  } catch (err) {
    showAlert(`数据刷新失败：${err.message || "请求失败"}`, "warn");
    return false;
  }
}

async function withAction(action, successText, { reload = true, rerender = null } = {}) {
  if (state.actionBusy) return null;
  state.actionBusy = true; setBusy(true); hideAlert();
  try {
    const res = await action();
    if (reload) {
      state.busyLabel = "正在刷新…";
      setBusy(true);
      const ok = await refreshViewData(state.view);
      if (!ok) return res;
    } else if (rerender) await rerender();
    if (successText !== false && (successText || res?.message)) {
      showAlert(successText || res?.message);
    }
    return res;
  } catch (err) { showAlert(err.message || "操作失败", "error"); return null; }
  finally { state.actionBusy = false; state.busyLabel = ""; setBusy(false); }
}

async function reloadAll(options = {}) {
  const ownBusyLabel = !state.actionBusy && !state.busyLabel;
  if (ownBusyLabel) state.busyLabel = "正在加载…";
  setBusy(true); hideAlert();
  try {
    await bridge.ready();
    if (options.preserveDrafts === false) {
      state.groupDrafts = {}; state.configDraft = {}; state.targetProbeResults = {};
      configDirtyKeys.clear();
    }
    const results = await Promise.allSettled([
      reloadGroupState(), reloadConfigState(), refreshHistoryData(), refreshRecentPushes(),
    ]);
    const labels = ["分组加载失败", "配置加载失败", "历史加载失败", "最近推送加载失败"];
    const errors = [];
    results.forEach((r, i) => {
      if (r.status === "rejected") {
        if (i === 1) state.configError = true;
        errors.push(`${labels[i]}：${r.reason?.message || "请求失败"}`);
      }
    });
    renderRailStatus();
    if (errors.length) showAlert(`部分数据未加载：${errors.join("；")}`, "warn");
    return errors.length === 0;
  } catch (err) { showAlert(err.message, "error"); return false; }
  finally {
    if (ownBusyLabel) state.busyLabel = "";
    setBusy(false);
  }
}

