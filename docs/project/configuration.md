# 配置说明

配置真源是 `_conf_schema.json`。读取、迁移规则在 `config/compat.py`，分组解析规则在 `scheduler/config.py`。

## 分组

AstrBot WebUI 的 `tweet_groups` 添加时先选 **博主分组**（`blogger`）或 **标签分组**（`tag`）。
旧版单一模板 `group`（用户分组）启动时迁移为 `blogger`。

- `basic`: Nitter 实例、默认数量、冷却、基础平台字段；HTML 回退与搜索相关键（见下「三列表」）。
- `media`: 图片、视频、xdown、缓存。
- `ai_translation`: 翻译。
- `schedule`: 后台检查总开关和全局频率。
- `push`: `tweet_groups`、推送间隔、合并阈值。
- `performance`: 后台账号并发拉取、并发准备和专用镜像池。
- `logging`: 日志模式。

## 三列表（禁止混用）

| 配置键 | 用途 | 说明 |
| --- | --- | --- |
| `instances`（`basic`） | 博主 RSS | 可含 nitter.net |
| `blogger_html_instances` | 博主 HTML 用户页回退 | `user_html_fallback` 开启且 RSS 失败/空时使用 |
| `search_instances` | HTML 搜索 | `/推文搜索` 与标签分组定时；默认不要放 nitter.net |

相关：`search_enabled`、`search_cooldown_seconds`、`search_default_limit`、`search_max_limit`、`html_min_interval`、`html_max_pages`、`html_request_timeout`。

## `tweet_groups`

`tweet_groups` 是订阅和推送目标的主配置。

字段：

- `name`: 显示名，可用于命令。
- `group_id`: 存储 ID。新建默认分组为 `default`；由插件自动分配并保持稳定，已有值（包括旧 `global`）保留。缺失时，安全英文数字分组名会作为旧 ID 继承，否则自动补齐为 `group_N`。
- `group_type`: `blogger`（默认）或 `tag`。创建后锁定；决定使用哪类订阅字段。标签组：Bot 使用私人 QQ 号时不建议启用定时搜索/推送。
- `enabled`: 是否启用。
- `watch_users`: **博主组**关注账号；标签组忽略。
- `watch_queries`: **标签组**搜索订阅列表。**落盘为字符串列表**（如 `#圣娅`、`蔚蓝档案`）。前导 `#` → tag，否则 phrase；phrase 禁止自动加 `#`。仍可读旧 `{query,type}` 对象，但会规范成字符串，避免 AstrBot `list` 显示 `[object Object]`。
- `push_targets`: 分组推送目标 UMO。
- `interval_check_enabled`: 是否参与全局间隔检查。
- `daily_check_times`: 每日检查时间。
- `filter_plain_text_enabled`: 是否过滤无作者媒体的纯文本推文（博主 RSS 与标签/HTML 路径均适用）。
- `omit_status_url`: 发送时去除推文链接（默认 `true`）。开启后不附带原文 URL 明文，并去掉正文/译文中的 http(s)；Telegram 用正文摘要 Markdown 链到推文。仅媒体模式不调用翻译。
- `hide_original_when_translated`: 分组级；有译文时隐藏原文（在全局 `show_original_when_translated=true` 时生效）。
- `media_only_enabled`: 定时推送只发送作者和成功准备的媒体；受全局媒体开关及单条媒体数量上限控制，全局不可用时回退完整内容。

全局 AI：

- `show_original_when_translated`（默认 `true`）：有译文时是否显示原文；关闭则全平台隐藏原文。

全局推送：

- `manual_send_interval`（默认 `0`）：手动命令逐条发送间隔秒数。

`watch_users` 和 `push_targets` 顶层字段是旧版兼容字段，启动后迁移到默认分组。

后台**博主**检查固定扫描 RSS 首屏约 20 条；首屏未命中上次最多 20 个扫描基准 ID 时按 `Min-Id` 翻页直到命中任意基准，然后按推文 ID 与 seen 做差集并发送全部新推文。旧配置中的 `scheduled_fetch_limit` 会在迁移时清理，不再作为运行参数。

后台**标签**检查：每个 `watch_query` 走 HTML 搜索（`search_instances`），组内串行；`fetch_limit` 固定 20、默认约 1 页（`html_max_pages`）；固定滤纯转推；可选纯文本/仅媒体；与 seen（`q:...`）差集后**新帖全发**（无每轮 5 条上限）；首次启用只 init 不推历史；标签首次空结果不初始化 seen。

## 新增配置项清单

新增字段必须同步：

- `_conf_schema.json`
- `config.compat.CONFIG_GROUP_BY_KEY`
- `config.compat.MIGRATABLE_CONFIG_KEYS`
- `config.compat.DEFAULT_GROUP_MIGRATION_KEYS`
- `scheduler.config.ScheduleGroup`
- `SchedulerConfigReader.parse_schedule_group()`
- README 或 `docs/advanced.md`
- `tests/test_subscription_import.py`

如果字段只属于某个 `tweet_groups` 项，不要加入全局 `CONFIG_GROUP_BY_KEY`，除非还需要旧顶层字段迁移。

## 兼容规则

- `config_get()` 优先读取分组对象里的值，再 fallback 到扁平字段。
- `migrate_legacy_grouped_config()` 将旧扁平全局配置复制到新分组对象。
- `migrate_default_group_config()` 将旧顶层订阅和默认分组字段迁移到新默认分组；已有 `tweet_groups[].group_id` 保留，缺失时补齐。
- `__template_key` 必须保留，供 AstrBot `template_list` 使用。

## 文档同步

配置字段新增、删除、默认值变化、范围变化或 hint 变化时，同步：

- `README.md` 常用配置或行为要点。
- `docs/advanced.md` 完整配置说明。
- 本文件。
- 相关测试。
