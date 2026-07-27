# Twitter List 订阅支持 — 移植计划

**日期**: 2026-07-27
**目标插件**: `astrbot_plugin_nitter_tweets`（当前版本 metadata.yaml `0.17.1`）
**来源原型**: `D:\Python\QQBOT\CF\html_nitter\`（`list` 命令已在 CF 验证通过）
**状态**: 📋 计划阶段 — **尚未改代码**

---

## 0. 现状核对（已实测，非假设）

移植前先核对了插件与 CF 的真实差异，避免重复劳动：

| 能力 | 插件现状 | 说明 |
|------|----------|------|
| HTML 后端基础设施 | ✅ **已存在** | `media_support/html_backend/`（pool/service/modes/parser/http_session/rate_limit/query）已迁入 |
| 门禁 anubis / poast_sha1 / plain / auto | ✅ 已存在 | `modes.py` |
| `fetch_user`（博主 HTML 回退） | ✅ 已存在 | `pool.py:242`、`service.py:130` |
| `search`（标签/短语搜索） | ✅ 已存在 | `pool.py:328`、`service.py:144` |
| `/推文搜索` 命令 | ✅ 已存在 | `main.py:238`，`command_handlers/manual.py` |
| 三列表（RSS / 博主 HTML / 搜索） | ✅ 已存在 | `_conf_schema.json` + `_build_html_backend()` |
| `user_html_fallback` 配置 | ✅ 已存在 | 默认 false |
| **`fetch_list`（List 时间线）** | ❌ **缺失** | 插件 `pool.py` 无此方法 |
| **`group_type: list`** | ❌ **缺失** | `scheduler/config.py` 只有 blogger/tag |
| **`/推文列表` 命令** | ❌ **缺失** | — |
| **`watch_lists` 配置字段** | ❌ **缺失** | — |

> 结论：CF 融入计划里的 **Phase 1（HTML 后端 + 搜索）此前已通过 PR #36 / #51 合入插件**。
> **本次唯一真正的新工作是 Twitter List 支持**。CF 原型 `html_nitter/pool.py:249 fetch_list` / `:267 _paginate_list` 是移植参考。

---

## 1. 需求与方案

**需求**：订阅 Twitter List（如"我关注的所有人"聚合时间线），而不是逐个博主订阅。

**方案**：
- 用户在 Twitter 创建 **Public** List，把关注对象加进去。
- 通过 Nitter `/i/lists/{list_id}` 路由抓取 List 时间线。
- List 页 HTML 结构与用户时间线一致 → **复用现有 `parse_timeline_html()`**。
- List 走 **HTML 后端**（与搜索共享实例池、门禁、限流），因此**必须串行**抓取，保护公共实例。

**为什么 List 是独立 group_type（不并入 blogger/tag）**：
- 语义不同：blogger=单人、tag=关键词、list=用户组聚合。
- 配置清晰：`watch_lists` vs `watch_users` vs `watch_queries`。
- 便于未来独立扩展（List 级过滤等）。

---

## 2. 文件变更清单（按实施顺序）

### Phase A — 底层抓取能力

#### A1. `media_support/html_backend/pool.py`（新增 ~80 行）
参考 CF `html_nitter/pool.py:249/267`，与现有 `fetch_user` / `search` 保持同构：
- [ ] `fetch_list(list_id, limit, *, instance=None)`
  - 复用现有全局重试框架（`max_global_retries` / `_hosts_for_rotation`）。
  - 支持 `instance` 参数（镜像探针单站模式）。
- [ ] `_fetch_list_once(...)`：一轮实例轮换 + 错误处理。
- [ ] `_paginate_list(base, list_id, limit)`：
  - 路由 `/i/lists/{quote(list_id)}`，翻页 `?cursor=...`。
  - 复用 `parse_timeline_html()`；返回 `HtmlSearchResult`（带 raw/filtered 统计，和 search 一致）。
- [ ] 复用 `filter_reposts` 逻辑（List 聚合他人推文，默认**不**过滤转发 — 待确认，见 §5）。

#### A2. `media_support/html_backend/service.py`（新增 ~10 行）
- [ ] 暴露 `fetch_list(list_id, limit, *, instance=None)` 门面，转调 pool。
- [ ] `__init__.py` 无需改（导出的是类）。

### Phase B — 手动命令（快速验证 A）

#### B1. `command_handlers/manual.py`（新增 ~80 行）
- [ ] `_cmd_tweets_list_impl(event, list_id, limit)`：
  - 校验 `list_id` 为纯数字（长度约 15~20 位，宽松校验）。
  - 冷却复用 search 冷却域（`scope="search"`，共享 HTML 资源）。
  - 调 `self.html_backend.fetch_list(...)`。
  - 复用现有 `_send_tweets_response()` / 媒体准备 / 翻译 / 发送逻辑（与 `/推文` 一致）。

#### B2. `main.py`（新增 ~6 行）
- [ ] 注册命令（**注意命名冲突**，见 §5）：
  ```python
  @filter.command("推文列表")   # 待定：现有 /订阅列表 已占用"列表"语义，避免混淆
  async def cmd_tweets_fetch_list(self, event, list_id: str = "", limit: str = ""):
      return await self._cmd_tweets_list_impl(event, list_id, limit)
  ```

### Phase C — 后台定时推送

#### C1. `scheduler/config.py`（新增 ~70 行 / 改 ~10 行）
- [x] 常量 `GROUP_TYPE_LIST = "list"`。
- [x] 新 dataclass `WatchListsInfo`（对齐 `WatchUsersInfo` 结构：raw_count/list_ids/duplicates/invalid_entries/changed）。
- [x] `ScheduleGroup` 增 `lists_info` 字段 + `is_list_group` 属性。
- [x] `account_keys` 统一返回 `f"list:{lid}"`（用于 seen 存储键）。
- [x] `_normalize_group_type()` 识别 `list` / `lists`。
- [x] 配置解析处理 `watch_lists`；List ID 校验（纯数字）→ 无效进 `invalid_entries`；去重。
- [x] **额外完成**: `config/compat.py` 迁移逻辑识别 `list` 类型（`TWEET_GROUP_TEMPLATE_KEY_LIST`、`_resolve_tweet_group_type` 支持 `watch_lists`、`_ensure_tweet_group_template_key` 清理冲突字段）。

#### C2. `scheduler/runner_fetch.py`（新增 ~55 行 / 改 ~5 行）
- [ ] `_fetch_group_user()` 增 list 分支 → `_fetch_group_list()`。
- [ ] `_fetch_group_list(group, index, list_id, fetch_limit, *, skip_plain_text)`：
  - 调 `html_backend.fetch_list()`。
  - 返回 `UserFetchResult(username=f"list:{list_id}", ...)` 复用推送/seen 链路。
  - **串行执行**（`is_list_group` 时禁并发，同 tag）。
- [ ] 核对 `runner_status.py` / `runner_seen.py` 是否需要感知 list 键（大概率复用 tag 路径即可，实施时确认）。

### Phase D — 配置 Schema

#### D1. `_conf_schema.json`（改 ~20 行）
- [ ] `tweet_groups.items.group_type` 枚举/hint 加 `list`。
- [ ] 新增 `watch_lists` 字段（type list，默认 []，hint 写明：纯数字 ID、从 `/i/lists/{id}` 取、必须 Public）。

### Phase E — WebUI（可选，二级优先）
- [ ] `plugin_api/` 概览/分组订阅页：分组类型下拉加 list、渲染 `watch_lists`。
  - 若本轮不做，需在文档标注"List 暂只支持配置文件/命令，WebUI 二期"。

### Phase F — 文档
- [ ] `README.md`：常用命令表加 `/推文列表`；功能概览提 List。
- [ ] `docs/advanced.md` 或新建 `docs/lists.md`：创建 List、取 ID、Public 要求、延迟生效、成员上限、推送频率控制、故障排查。
- [ ] `metadata.yaml` / README 版本号：`0.17.1` → 下一个版本（建议 `0.18.0`，新增功能）。

### Phase G — 测试
- [ ] `tests/test_list_support.py`：
  - `fetch_list` mock HTTP → 解析/翻页。
  - List ID 校验（有效/无效/空）。
  - `group_type: list` 配置解析（正常/缺失/重复/无效）。
  - 调度器 list 分支返回 `UserFetchResult`。
- [ ] `scripts/probe_nitter_fetch.py` 可选加 `--list` 联网探针（对齐现有 probe 风格）。

---

## 3. 集成数据流

```
/推文列表 <id> [n]  或  group_type=list 定时
  → 校验 list_id（纯数字）
  → html_backend.fetch_list(id, n)         # 走 search_instances 池
      → 门禁 ensure (anubis/poast_sha1/plain)
      → GET /i/lists/{id}[?cursor=]         # 串行 + 限流
      → parse_timeline_html()               # 复用
  → （可选）过滤纯文本
  → 媒体准备（pbs 直下 / xdown 视频）        # 复用 MediaService
  → 翻译（可选）                             # 复用 TweetTranslator
  → 发送（QQ 合并转发 / 其他普通）            # 复用 TweetSender
  → 定时路径：seen 去重键 = group_id + "list:{id}"
```

---

## 4. 已知限制（写入文档）

1. **Private List 不可访问** — Nitter 无法读取需登录的 List，必须 Public。
2. **新 List 延迟生效** — 建议等 10~30 分钟。
3. **List 成员上限 5000** / 每账号最多 1000 个 List。
4. **推送频率** — List 聚合多人可能刷屏，建议配 `max_tweets_per_check` + 拉长检查间隔，或拆多个小 List。
5. **成员变更非实时** — Nitter 缓存，通常 5~10 分钟。

---

## 5. 待用户确认的决策点

| # | 议题 | 备选 | 倾向 |
|---|------|------|------|
| 1 | 命令名 | `/推文列表` vs 其他 | ⚠️ 现有 `/订阅列表`（管理员查订阅）已用"列表"，`/推文列表`（取 List 推文）易混淆。倾向换名，如 `/推文清单` 或 `/推文list` |
| 2 | List 是否过滤转发 | 过滤 / 不过滤 | 倾向**不过滤**（List 本就是看聚合动态，含转发更合理），但与博主 `filter_reposts_enabled` 语义需说明 |
| 3 | 本轮是否含 WebUI | 含 / 二期 | 倾向**二期**，先命令 + 配置文件跑通，降低本轮范围 |
| 4 | 交付方式 | 一批 / 分阶段 | 计划支持分阶段（A→B 可先验证联网，再 C→D 上定时） |
| 5 | 目标版本号 | `0.18.0` | 新功能，建议 minor +1 |

---

## 6. 工作量估算

| 阶段 | 文件 | 新增 | 改 | 难度 |
|------|------|------|----|------|
| A | pool.py / service.py | ~90 | 0 | 中（复用现有模式） |
| B | manual.py / main.py | ~86 | ~2 | 低 |
| C | config.py / runner_fetch.py | ~125 | ~15 | 中 |
| D | _conf_schema.json | ~20 | ~2 | 低 |
| E | plugin_api（可选） | ~40 | ~10 | 中 |
| F | README / docs | ~200 | ~20 | 低 |
| G | tests | ~120 | 0 | 中 |
| **合计** | | **~680** | **~50** | — |

预估 3~5 小时（不含联网真机验证与文档打磨）。

---

## 7. 验收清单

**手动命令**
- [ ] `/推文列表 1553232306718257152 5` 返回 5 条（CF 已验证该 List 可用）
- [ ] `/推文列表 abc` 友好报错（格式无效）
- [ ] Private / 未生效 List → 友好提示（非崩溃）

**定时推送**
- [ ] `group_type: list` + `watch_lists` 正确解析
- [ ] 后台检查按 List 抓取并推送到目标会话
- [ ] seen 去重键 `list:{id}` 独立，不与 blogger 冲突
- [ ] 首次启用 List 只记录基线，不推历史

**回归**
- [ ] `/推文`、`/推文搜索` 行为不变
- [ ] 现有 blogger/tag 分组不受影响
- [ ] 全量 `tests/` 通过

---

## 8. 参考

- CF 原型: `D:\Python\QQBOT\CF\html_nitter\pool.py`（`fetch_list` 已验证）
- CF 进度: `D:\Python\QQBOT\CF\Progress\2026-07-27-twitter-list-support.md`
- 测试 List（CF 已验证可用）: `https://x.com/i/lists/1553232306718257152`
- Nitter 路由: `/i/lists/{list_id}`

---

*本文件仅为计划，未修改任何插件业务代码。*

---

## 9. 本轮执行决策（2026-07-27）

- 已创建实现分支：`twitter-list-support`（无任何前缀）。
- 本轮不做手动命令，只做 `group_type=list` 定时订阅。
- List 作为 `tweet_groups` 中独立分组块，配置体验对齐 `tag` 分组。
- 用户主要填写：`name`、`watch_lists`、`push_targets`、`enabled`；建议设置 `max_tweets_per_check` 防刷屏。
- `watch_lists` 只接受公开 X/Twitter List 的纯数字 ID，例如 `2081623084780671084`。
- 翻页复用全局 `html_max_pages`；最终推送条数复用分组 `max_tweets_per_check`。
- List 抓取走现有 HTML 后端与 `search_instances`，共享门禁、限流和冷却。
- 转发过滤跟随现有全局 `filter_reposts_enabled`，不新增 List 独立开关。
- CF 可用性验证：`python -m html_nitter.cli list 2081623084780671084 --limit 100` 返回 `COUNT 91`，来源 `https://nitter.tiekoetter.com`，本次未触发 429。
