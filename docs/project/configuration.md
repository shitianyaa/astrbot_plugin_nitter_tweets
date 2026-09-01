# 配置说明

配置真源是 `_conf_schema.json`。读取、迁移规则在 `config/compat.py`，分组解析规则在 `scheduler/config.py`。

## 分组

AstrBot WebUI 的 `tweet_groups` 添加时先选 **博主分组**（`blogger`）、**标签分组**（`tag`）或 **列表分组**（`list`）。
旧版单一模板 `group`（用户分组）启动时迁移为 `blogger`。

- `basic`: 自建 Nitter 实例、默认数量、冷却和基础平台字段。
- `media`: 图片、视频、传输编码、xdown、缓存。
- `ai_translation`: 翻译。
- `schedule`: 后台检查总开关和全局频率。
- `push`: `tweet_groups`、推送间隔、合并阈值和目标级作者黑名单。
- `performance`: 后台账号并发拉取和并发准备。
- `logging`: 日志模式。

## 实例配置

| 配置键 | 用途 | 说明 |
| --- | --- | --- |
| `instances`（`basic`） | RSS、HTML 搜索/List | 仅填写自建 Nitter，可配多个；无默认公共实例 |

同一自建实例同时承担 RSS 和 HTML。旧版 `search_instances`、`blogger_html_instances`、`concurrent_fetch_instances` 已删除，仅在启动日志中提示，不读取、不迁移、不写回。

关注对象较多时建议优先使用 Nitter List 分组，减少逐用户抓取造成的请求量和 429；RSS 与 HTML 共用 `retry_attempts` 和 `retry_delay_seconds`。

相关：`cooldown_seconds`、`search_max_limit`、`html_min_interval`、`html_max_pages`。`request_timeout`、`retry_attempts`、`retry_delay_seconds` 同时作用于 RSS 和 HTML。

`auto_parse_tweet_links_enabled`（`basic`，默认 `false`）：被动解析聊天中的公开 status 链接；不进 `tweet_groups` 模板。翻译与 `show_original_when_translated` 跟随全局 AI 配置。

Dashboard 实例测试一次检查统一 `instances` 的用户 RSS、用户 HTML、搜索和可选 List。URL 留空时按配置顺序测试全部实例；填写 URL 时只测试该站。

## `tweet_groups`

`tweet_groups` 是订阅和推送目标的主配置。

字段：

- `name`: 显示名，可用于命令。
- `group_id`: 存储 ID。新建默认分组为 `default`；由插件自动分配并保持稳定，已有值（包括旧 `global`）保留。缺失时，安全英文数字分组名会作为旧 ID 继承，否则自动补齐为 `group_N`。
- `group_type`: `blogger`（默认）、`tag` 或 `list`。创建后锁定；决定使用哪类订阅字段。Tag/List 组通过 HTML 搜索，Bot 使用私人 QQ 号时不建议启用定时搜索/推送。
- `enabled`: 是否启用。
- `watch_users`: **Blogger 组**博主订阅源；其他类型忽略。
- `watch_queries`: **Tag 组**搜索订阅列表。**落盘为字符串列表**（如 `#圣娅`、`蔚蓝档案`）。前导 `#` → tag，否则 phrase；phrase 禁止自动加 `#`。仍可读旧 `{query,type}` 对象，但会规范成字符串，避免 AstrBot `list` 显示 `[object Object]`。
- `watch_lists`: **List 组**正 `uint64` List ID 列表（`1` 至 `18446744073709551615`）；其他类型忽略。List 走统一 `instances`，不新增手动命令。
- `push_targets`: 分组推送目标 UMO。
- `interval_check_enabled`: 是否参与全局间隔检查。
- `daily_check_times`: 每日检查时间。
- `filter_reposts_enabled`: 分组级转发过滤子开关，默认 `true`；只有全局同名总开关也开启时才过滤。
- `filter_plain_text_enabled`: 是否过滤无作者媒体的纯文本推文（博主 RSS 与标签/HTML 路径均适用）。
- `omit_status_url`: 该分组定时发送时去除推文链接（默认 `true`）。开启后不附带原文 URL 明文，并去掉正文/译文中的 http(s)；关闭时普通正文/译文中的外部链接保留，但当前 Nitter 来源实例改写出的同站镜像链接仍会清理。Telegram 在作者头部使用 Markdown 链接到推文，并在底层发送时关闭网页预览。仅媒体模式不调用翻译。
- `hide_original_when_translated`: 分组级；有译文时隐藏原文（在全局 `show_original_when_translated=true` 时生效）。
- `media_only_enabled`: 定时推送只发送作者和成功准备的媒体；受全局媒体开关及单条媒体数量上限控制，全局不可用时回退完整内容。
- `send_target_interval` / `send_user_interval`: 分组级发送间隔（秒）；未填时回退全局同名配置，同时用于 Tag/List 订阅源之间的串行抓取间隔。
- `max_tweets_per_check`: 单个订阅源单次检查最多推送的推文条数（`0` 不限制，范围 0-200）；Blogger、Tag、List 均生效。Tag/List 扫描未完整且找不到旧基准时，`0` 跳过推送并自动重建当前第一页基准，正数按上限推送后再重建；发送准备失败、首屏基准无效或基准写入失败时保留旧水位，发送调用失败则跳过当前批次并推进 seen。

全局 `filter_reposts_enabled` 是 Blogger、Tag、List 后台检查的总开关。实际过滤条件为“全局总开关 && 分组子开关”；二者默认均开启，旧分组缺少子开关时按开启处理。全局关闭时任何分组都不能单独强制开启。手动命令不读取分组子开关。

全局 AI：

- `show_original_when_translated`（默认 `true`）：有译文时是否显示原文；关闭则全平台隐藏原文。

全局推送：

- `manual_send_interval`（默认 `0`）：手动命令逐条发送间隔秒数。
- `target_blocked_users`：隐藏列表配置，每项为完整 UMO 与其用户名列表；同一目标跨多个分组共享，命令和 Dashboard 维护，发送阶段按目标过滤。目标 UMO 需完整格式（如 `aiocqhttp:GroupMessage:123`）。

`watch_users` 和 `push_targets` 顶层字段是旧版兼容字段，启动后迁移到默认分组。

后台**博主**检查固定扫描 RSS 首屏约 20 条；首屏未命中上次最多 20 个扫描基准 ID 时按 `Min-Id` 翻页直到命中任意基准，然后按推文 ID 与 seen 做差集并发送全部新推文。旧配置中的 `scheduled_fetch_limit` 会在迁移时清理，不再作为运行参数。

后台**Tag/List**检查：每个 `watch_query` 或 `watch_list` 走 `instances` 的 HTML，组内串行、订阅源之间按 `send_user_interval` 等待。首轮最多取 20 条建立基准；已有水位时本轮扫描可超过 20 条，并按 `html_max_pages` 翻页到旧水位或游标结束，持久化水位仍最多保存 20 个 ID。达到页数上限仍未命中旧基准时，`max_tweets_per_check=0` 会跳过推送并自动重建当前第一页基准，正数会按上限推送后再重建；首屏没有有效状态 ID、发送准备失败或基准写入失败时保留旧水位，发送调用失败则跳过当前批次并推进 seen。二者都按全局和分组双层开关决定是否过滤转发，可选纯文本/仅媒体，再与 seen（`q:...` / `list:...`）差集后发送新帖（`max_tweets_per_check > 0` 时按该上限截断，默认不限制）。首次有可用结果只 init 不推历史；真正空首轮不初始化 seen 或扫描水位；有原始结果但全被过滤时记录空扫描水位。

`check_on_startup=true` 时，调度存储初始化完成后按分组顺序首检所有启用且同时配置订阅源和有效推送目标的分组；仅每日定点、仅间隔和没有定时槽位的分组都执行一次。首检完成后锚定当前间隔/每日槽位，避免同一轮重复触发。手动 `/推文检查` 仍要求当前会话属于该分组的 `push_targets`，只是会等待同一套存储初始化完成。

批次摘要和检查结果使用类型化术语：Blogger 为“n 位博主”、Tag 为“n 个搜索订阅”、List 为“n 个 List”；内部 `q:` / `list:` seen 键不会出现在用户可见的检查、失败或历史文案中。

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

全新的字段没有旧扁平形态可迁移，只需进 `CONFIG_GROUP_BY_KEY`，**不要**加入 `MIGRATABLE_CONFIG_KEYS`，
也不必在 schema 里补 `invisible` 扁平镜像。`media_transport_*` 三项即按此处理。

## 媒体传输编码

`media` 分组下的三项只影响私人号 OneBot 的媒体投递，行为见
[平台发送指南](./platform-delivery.md#媒体传输编码)：

| 配置键 | 默认 | 说明 |
| --- | --- | --- |
| `media_transport_mode` | `auto` | `auto` / `path_only` / `base64_first`；非法值回落 `auto` |
| `media_transport_base64_max_mb` | `8.0` | clamp 到 `0.5-32`；同时约束图片和视频 |
| `media_transport_url_fallback` | `false` | 开启会让协议端直连 Twitter CDN |

解析函数在 `config/compat.py`：`resolve_media_transport_mode`、
`resolve_media_transport_base64_max_mb`、`resolve_media_transport_url_fallback`；
`TransportConfig.from_config()` 负责组装。

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
