# AGENTS.md

面向后续 AI agent 的项目开发规范。改代码前先读本文件，再读相关模块和测试。

## 文档入口

- 用户：`README.md`、`docs/advanced.md`、`docs/twitter-lists.md`、`docs/README.md`
- 项目事实：`docs/project/`（架构、配置、平台发送）
- 开发：`docs/dev/`（setup、testing、maintenance）
- 配置真源：`_conf_schema.json`；迁移：`config/compat.py`

业务细节写在 `docs/project/`、`docs/advanced.md`、schema，**不要**继续把完整专题堆进本文件。

## 工作方式（用户约定）

- **先规划，用户同意后再改代码**（文档小补丁除外，若用户已明确「直接改」）。
- 多步实现用 `Progress/YYYY-MM-DD-*.md` 记清单与验证；不擅自 commit Progress。
- 不使用 obra/superpowers 技能套件；以本文件 + `docs/` + Progress 为准。

## 项目定位

AstrBot 插件 `astrbot_plugin_nitter_tweets`：Nitter RSS / HTML 搜索获取公开推文；手动查询与搜索；按 `tweet_groups` 定时推送（`blogger` / `tag` / `list`）；可选被动解析聊天中的 status 链接；图片/视频/翻译；多平台发送；SQLite seen + push history。

## 代码入口（细节见 architecture）

| 区域 | 职责 |
| --- | --- |
| `main.py` | 生命周期、命令/regex 注册、委派。保持轻量。 |
| `command_handlers/` | `manual` / `maintenance` / `subscriptions` / **`link_preview`**（被动链接） |
| `scheduler/` | 高风险：检查、seen、推送编排 |
| `media_support/` | RSS client、`html_backend`、媒体、**`status_link` / `status_resolve`** |
| `delivery/` | 多平台发送；`force_media` 仅链接预览等显式路径 |
| `rendering/`、`ai/`、`storage/`、`plugin_api/`、`shared/` | 渲染、翻译、SQLite、WebUI API、模型 |

完整模块关系：`docs/project/architecture.md`。

## 必守规则

- 复杂逻辑不进 `main.py`；命令 `event.stop_event()` + `event.send(...)` / sender。
- 管理命令：`@filter.permission_type(ADMIN)`，并继续做场景校验。
- 双导入：`try: from .x import ... except ImportError: from x import ...`。
- 不硬编码 provider、token、群号、实例、本机路径；不提交 `data/`、缓存、DB、下载物。
- 不改用户未要求的行为/文案；优先兼容现有测试。
- 提交只用真实变更描述；无 AI 署名、`Co-Authored-By`、`Generated with ...`。
- 禁止丢改动的 git 命令（`reset --hard` 等），除非用户明确要求。

## 配置与迁移

新增配置必须同步：`_conf_schema.json`、`CONFIG_GROUP_BY_KEY` / `MIGRATABLE_*`（若适用）、`ScheduleGroup` 解析、README 或 advanced、相关测试。

分层：`basic` / `media` / `ai_translation` / `schedule` / `push` / `performance` / `logging`。

### `tweet_groups`

- `group_id` 稳定；默认新建 `default`。
- `group_type`：`blogger` | `tag` | **`list`**。创建后勿改；字段分别用 `watch_users` / `watch_queries` / **`watch_lists`**，勿混用。
- seen：`group_id + account_key`；博主=用户名；标签=`q:<casefold>`；List=`list:<id>`（用 `normalize_seen_account_key`）。
- 转发过滤：`全局 filter_reposts_enabled && 分组 filter_reposts_enabled`；手动命令不读分组子开关。
- List 必须 Public；ID 为纯数字；走 `search_instances` HTML。

### 实例三义（禁止混用）

- `instances`：仅博主 RSS（默认可含 nitter.net）。
- `search_instances`：搜索/List HTML（默认勿放 nitter.net）。
- 无独立博主 HTML 池；`user_html_fallback` 默认关，开启会占用搜索实例。

### 被动链接解析

- 配置：`auto_parse_tweet_links_enabled`（**默认 false**）。
- 入口：`@filter.regex` → `LinkPreviewMixin`；**无新命令**。
- 忽略 Bot 自身消息；合法 status 链才 `stop_event`。
- 解析：FxTwitter → VxTwitter → Syndication（`status_resolve`）；URL 白名单在 `status_link`。
- 翻译跟全局 `translate_*`；原文显隐只跟全局 `show_original_when_translated`（无分组 hide）。
- 媒体：`force_all_media` / send `force_media`（无视全局图视频开关与 `max_media_per_tweet`，仍受大小/时长/超时）。
- 单消息最多 3 链；防抖同 UMO+status_id（实现上应在**成功后**再记；见 Progress/审查）。
- 注意：共享 `TweetSender` 上临时改 media flags 有并发串扰风险；优先局部 force。

## RSS / HTML / 过滤（摘要）

- 手动 `fetch_tweets` 默认不跳纯文本、保留转发；后台可用 `skip_plain_text` 与双层转发过滤。
- 纯文本过滤只影响后台：作者上传媒体才算；`card_img`、Article 封面、**引用推媒体**不算。
- 整页被滤但仍有 cursor 须翻页；真·空 feed 才 empty。
- 诊断：`python scripts/probe_nitter_fetch.py nasa 5`（可加 `--skip-plain-text` / `--include-reposts`）。

## 调度与 seen

- 首次账号/查询只 init seen，不推历史；Tag/List 真空首轮可不 init。
- **seen 仅发送成功后更新**；失败/取消须清本轮普通媒体缓存。
- 改 `ScheduleGroup` / `ScheduledCheckResult` 时同步 status/log/message 格式与测试。

## 媒体 / 平台 / AI

- 有视频/GIF 时跳过同条封面图；下载失败不挡文本。
- 普通媒体发送后清理；统计 removed/failed 等。
- UMO 用 `/sid` 完整值；平台类型用 `PlatformResolver`，勿只看 UMO 第一段。
- QQ 合并转发有降级与「可能已送达」处理；TG flood retry；Lark 优先原生 post。
- 处理顺序：翻译 → 媒体；provider 不硬编码。

## 文档同步

用户可见变更同步：`README.md`、`docs/advanced.md`（及 List 专题）、`_conf_schema.json`、`CHANGELOG.md`、`metadata.yaml`（版本/能力）。

## 测试与工具

```powershell
python -m pytest -q
ruff check .
ruff format --check .
```

- Ruff：**0.16+**；根目录 `ruff.toml` 忽略 `BLE001`（边界宽捕获有意保留）。
- 链接解析：`tests/test_status_link_preview.py`
- List：`tests/test_list_support.py`、`tests/test_scheduler_list_delivery.py`
- 标签调度：`tests/test_scheduler_tag_delivery.py`
- HTML/搜索：`tests/test_html_backend_query.py`、`tests/test_watch_queries_config.py`
- 改 `delivery/sender.py`、`scheduler/`、`config/compat.py` 或公共模型 → **全量 pytest**。

完整矩阵：`docs/dev/testing.md`。

## Review 清单

- 只改任务相关文件；手动 vs 后台行为差异保留。
- 无提前写 seen；缓存已清理；非 OneBot 平台未误用合并转发。
- 引用媒体未当作者媒体；schema/compat/docs/测试已同步；对应测试已跑。
