# 标签分组 + HTML 搜索/回退 — 整体实现计划（待确认）

> 状态：**待用户确认后再写业务代码**  
> 分支：`feat/tag-query-search`（基于 `origin/tag-tweet-fetch` / `7c2b2ed`）  
> 规范来源：插件 `AGENTS.md`、CF `AGENTS.md`、CF Progress 限订文档  
> 不使用 superpowers 流程；小步实现、相关测试、schema/文档同步

---

## 1. 目标（本轮范围 = A）

在插件内落地一整套「搜索类能力」，与现有博主推送对等：

1. **HTML 后端**（从 `D:\Python\QQBOT\CF\html_nitter` 迁入适配）  
2. **博主分组**：RSS 失败 → HTML 用户页回退（默认开）  
3. **标签分组**：与博主分组对位的**分组类型**，定时搜索推送  
4. **手动 `/推文搜索`**（非管理员）  
5. **Dashboard 前端 + Web API** 支持分组类型与 query 编辑  

**本轮要做齐**：配置、调度、seen、发送、WebUI、命令、文档、测试。  
**不做**：Playwright / CF Turnstile 主路径、`html_proxy`、恢复已删 AI/暂存功能、改 `support_platforms` 猜测。

---

## 2. 产品模型（核心）

### 2.1 分组类型对位

每个 `tweet_groups[]` 项有：

| 字段 | 含义 |
|------|------|
| `group_type` | **`blogger` \| `tag`**（必填语义；缺省兼容为 `blogger`） |

| 类型 | 订阅字段 | 拉取 | 不混用 |
|------|----------|------|--------|
| **博主分组** `blogger` | `watch_users` | RSS →（可选）HTML 用户页 | 忽略 `watch_queries` |
| **标签分组** `tag` | `watch_queries` | 仅 HTML `search()` | 忽略 `watch_users`（保存时可清空或只读隐藏） |

共用：`group_id`、`name`、`enabled`、`push_targets`、间隔/定点、`media_only_enabled`、`filter_plain_text_enabled` 等调度壳。

> 命名说明：产品文案用「标签分组」，配置值用 `tag`。组内单条查询仍分 `type: tag | phrase`（见下）。若嫌 `group_type=tag` 与 query `type=tag` 易混，实现时可用 `group_type: blogger | search`，**文案仍显示「标签」**——**确认时二选一（默认 `blogger`/`tag`）**。

### 2.2 标签分组内的订阅项

```yaml
watch_queries:
  - query: "#圣娅"
    type: tag          # tag | phrase，必填（可保存时推断）
  - query: "python programming"
    type: phrase
```

| 规则 | 说明 |
| ------ | ------ |
| 禁止自动加 `#`（phrase） | 用户写啥搜啥 |
| 前导 `#` → 保存为 `type=tag` | tag 规范化可补一个 `#` |
| 无前导 `#` → `phrase` | 仅 `/search`，不走 `/hashtag/` |
| 运行时 | **只信存盘 `type`**，不每次猜 |
| 老数据缺 `type` | 按 `#` 推断并自愈回写 |

### 2.3 手动搜索

```text
/推文搜索 <query>
```

- 与 `/推文` 同级权限（非强制 ADMIN）  
- kind 由 `query.startswith("#")` 推断  
- 冷却与 `/推文` 分离（默认约 30s）  
- 可不定时入库；与标签分组共用 `search()` 管道  

### 2.4 三列表（禁止混用）

| 列表 | 用途 | 默认 |
| ------ | ------ | ------ |
| `basic.instances`（现有） | 仅博主 RSS | 含 nitter.net 可 |
| `blogger_html_instances` | 仅 `/{user}` HTML 回退 | tiekoetter → poast → kareem |
| `search_instances` | 仅搜索 HTML | 同上；**不要 nitter.net** |

### 2.5 seen / 扫描

| 类型 | 键 |
|------|-----|
| 博主 | 现有：`group_id + username` |
| 标签 query | `group_id + q:<casefold(normalized query)>`（与 CF 约定一致） |

- 首次启用 query：**只初始化 seen，不推历史**（对齐博主）  
- 发送成功后再写 seen；临时失败不越过扫描缺口（对齐仅媒体策略精神）  
- 标签分组 `filter_plain_text` / `media_only`：对搜索结果同样适用（媒体判定复用已有能力或 HTML 侧媒体字段）

### 2.6 HTML 限流（全局共享）

- HTML 全局串行（并发 1）  
- host 最小间隔（默认 3s；kareem 可更长）  
- 429：冷却 30s 起 → 封顶 5min，换源，不在同请求内干等  
- Cookie/session 落在 `StarTools.get_data_dir`  

---

## 3. 架构落点

```text
main.py                          # 注入 HtmlBackend；注册 /推文搜索
media_support/html_backend/      # 从 CF html_nitter 迁入适配
  modes.py / http_session.py / rate_limit.py / parser.py / pool.py / service.py
media_support/client.py          # 仍只做 RSS
command_handlers/manual.py       # /推文 HTML 回退；/推文搜索
scheduler/config.py              # ScheduleGroup.group_type + watch_queries
scheduler/runner.py              # 按类型分支：user RSS/HTML vs search
storage/*                        # seen 支持 q: 账户键（尽量复用 username 列语义或扩展）
plugin_api/groups.py + api.py    # 序列化/创建/更新/诊断
pages/dashboard/app.js(+css)     # 类型选择 + 条件表单
_conf_schema.json + config/compat.py
README / docs/advanced / CHANGELOG
tests/...
```

**依赖方向：**  
`domain/shared TweetItem` ← html_backend 解析  
`application` 调度/命令 → html service + 现有 MediaService/Sender  
禁止业务层复制三套爬虫。

---

## 4. 配置草案

### 4.1 全局（建议挂 `basic` 或独立 `html` 分组，实现时选一处并进 compat）

| Key | 默认 |
| ----- | ------ |
| `user_html_fallback` | `true` |
| `blogger_html_instances` | 三站 |
| `search_enabled` | `true` |
| `search_instances` | 三站 |
| `search_cooldown_seconds` | `30` |
| `search_default_limit` | `5` |
| `search_max_limit` | `10` |
| `html_min_interval` | `3.0` |
| `html_max_pages` | `1` |
| `html_request_timeout` | `35` |

### 4.2 分组字段新增

| Key | 默认 / 说明 |
|-----|-------------|
| `group_type` | `blogger`（兼容旧组） |
| `watch_queries` | `[]`；项为 `{query, type}` |

AstrBot schema：`tweet_groups` template 增加上述字段；Dashboard 为主编辑面，schema 同步可见。

---

## 5. 前端（Dashboard）改动

文件：`pages/dashboard/app.js`、`style.css`（必要时 `index.html` 文案）  
API：`plugin_api/groups.py`、`plugin_api/api.py`（`_serialize_group`、create/update、overview 诊断）

### 5.1 列表

- 分组列表显示类型徽章：`博主` / `标签`  
- 统计：博主组计 `watch_users`；标签组计 `watch_queries`；overview 分别汇总  

### 5.2 创建

- 新建时**必选**类型（默认博主，或弹层二选一）  
- 创建后 `group_type` **建议锁定不可改**（避免 seen/数据语义错乱）；若允许改类型，必须清空另一侧订阅并提示  

### 5.3 编辑器条件渲染

**博主组（现有）：**

- 关注账号 chips / 导入 / 删除订阅  
- 无效/重复账号  

**标签组（新增）：**

- 查询列表：展示 `query` + `type`（tag/phrase）  
- 添加：输入框 + 自动推断 type；允许手动改 type  
- 删除单条 query  
- **隐藏**账号导入 UI（或禁用并说明）  
- 无效 query（空串）提示  

**共用：** 名称、开关、推送目标、间隔/定点、仅媒体、纯文本过滤、立即检查、保存/删除  

### 5.4 立即检查 / 清空 seen

- 标签组 `web/check` 走 search 调度路径  
- 清空 seen 按 `group_id` 清该组全部键（含 `q:`）  

### 5.5 校验

- `node --check pages/dashboard/app.js`  
- 手工/浏览器：创建两类组、切换编辑、保存回读、徽章与诊断  

---

## 6. 后端任务分解（确认后执行顺序）

### Task 1 — `html_backend` 核心

- 迁入/适配 CF：parser、rate_limit、modes、http_session、pool、service  
- 输出插件 `TweetItem`；`search(query, kind=None)` / `fetch_user(username)`  
- 单测：kind 推断、解析 fixture、冷却、换源 mock  

### Task 2 — 配置与 `ScheduleGroup`

- schema + compat  
- `ScheduleGroup.group_type`、`queries_info`（或等价结构）  
- 解析/规范化 `watch_queries`；缺 `type` 自愈  
- 旧组无 `group_type` → `blogger`  

### Task 3 — 存储 seen

- 确认 SQLite `seen` 是否可用 `username` 列存 `q:...`；否则最小扩展  
- 迁移/同步分组时包含 query 键  
- 单测：键格式、首次只初始化  

### Task 4 — 调度

- `runner`：blogger 路径 = 现逻辑 + HTML 回退  
- tag 路径：对每个 query `search` → 新推文发现 → 准备媒体 → 发送 → seen  
- 与全局 HTML 限流共享；并发策略：标签组内 query 串行优先（降压公共实例）  
- 状态摘要/日志区分类型  

### Task 5 — 命令

- `/推文`：RSS 全失败且开关开 → HTML user  
- `/推文搜索`：搜索管道 + 冷却 + 发送（完整内容，非 media_only）  

### Task 6 — Web API + Dashboard

- 序列化字段、create/update 校验（类型与字段匹配）  
- 诊断：标签组无 query / 博主组无 user 分开提示  
- 前端条件 UI  

### Task 7 — 文档

- README 命令与分组类型  
- `docs/advanced.md`：三列表、门禁、query 规则、seen  
- CHANGELOG Unreleased  

### Task 8 — 验证

```text
相关 pytest（html / schedule / config / plugin_api / dashboard）
python -m pytest -q   # 或按 AGENTS 矩阵
ruff check .
py_compile 关键模块
python -m json.tool _conf_schema.json
node --check pages/dashboard/app.js
```

未要求不 commit / 不 push。

---

## 7. 明确不做（本轮）

- 一站一套爬虫、Playwright 默认依赖  
- 搜索实例塞 nitter.net  
- 同一分组同时维护 users + queries 混跟  
- 自动把短语当 hashtag  
- 版本号大跳（除非你要求发版）  

---

## 8. 风险与决策点（请你拍板）

| # | 问题 | 建议默认 |
| --- | ------ | ---------- |
| D1 | `group_type` 取值 `blogger`/`tag` 还是 `blogger`/`search`？ | **`blogger` / `tag`**，UI 文案「博主/标签」 |
| D2 | 创建后是否允许改分组类型？ | **不允许**（防 seen 混乱） |
| D3 | 标签组是否默认开启 `media_only`？ | **否**，与博主一样默认 false |
| D4 | 标签组内多 query：串行还是有限并发？ | **串行**（护公共实例） |
| D5 | 历史记录表 `username` 列对 query 存什么？ | 存规范化 query 或 `q:...` 显示友好串，与 seen 一致并在 UI 标明 |

---

## 9. 验收标准

- [ ] 可创建并保存「标签分组」，WebUI 只显示 query 编辑  
- [ ] 可创建「博主分组」，行为与现网一致 + RSS 失败可 HTML 回退  
- [ ] 定时：标签组新帖推送到 `push_targets`，首次不刷屏  
- [ ] `/推文搜索 #xxx` 与短语均可返回；不自动加 `#`  
- [ ] 三列表独立；限流/换源可测  
- [ ] 测试与文档同步；前端 `node --check` 通过  

---

## 10. 确认清单（回复即可）

请回复例如：

```text
确认计划
D1=tag, D2=锁定类型, D3=默认false, D4=串行, D5=按建议
```

或指出要改的条目。  
**你确认后我再动业务代码。**
