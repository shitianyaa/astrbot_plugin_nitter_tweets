# 配置说明

配置真源是 `_conf_schema.json`。读取、迁移规则在 `config/compat.py`，分组解析规则在 `scheduler/config.py`。

## 分组

- `basic`: Nitter 实例、代理列表、默认数量、冷却、基础平台字段。
- `media`: 图片、视频、xdown、缓存。
- `ai_translation`: 翻译。
- `ai_comment`: AI 评论。
- `ai_vision`: AI 识图。
- `schedule`: 后台检查总开关和全局频率。
- `deferred`: 暂存发布全局参数。
- `push`: `tweet_groups`、推送间隔、合并阈值。
- `performance`: 后台账号并发拉取、并发准备和专用镜像池。
- `logging`: 日志模式。

## `tweet_groups`

`tweet_groups` 是订阅和推送目标的主配置。

字段：
- `name`: 显示名，可用于命令。
- `group_id`: 存储 ID。新建默认分组为 `default`；由插件自动分配并保持稳定，已有值（包括旧 `global`）保留。缺失时，安全英文数字分组名会作为旧 ID 继承，否则自动补齐为 `group_N`。
- `enabled`: 是否启用。
- `watch_users`: 分组关注账号。
- `push_targets`: 分组推送目标 UMO。
- `interval_check_enabled`: 是否参与全局间隔检查。
- `daily_check_times`: 每日检查时间。
- `deferred_publish_enabled`: 是否启用暂存发布。
- `filter_plain_text_enabled`: 是否过滤无作者媒体的纯文本推文。

`watch_users` 和 `push_targets` 顶层字段是旧版兼容字段，启动后迁移到默认分组。

## `proxies`

`proxies` 位于 `basic`，使用 AstrBot `template_list`，模板键为 `proxy`。列表项包含：

- `enabled`: 是否启用。
- `type`: `http`、`https`、`socks5`、`socks5h`。
- `host`, `port`: 代理地址。
- `username`, `password`: 可选用户名密码认证；HTTP/HTTPS 遵循 Basic Latin-1 限制，SOCKS 两项必须同时填写。

运行时由 `NetworkClient` 解析一次并保持原列表顺序。配置了启用代理时不回退直连；无启用代理时沿用原有网络行为。用户名和密码不得进入日志。该字段是全新配置，没有旧扁平发布事实，不加入 `MIGRATABLE_CONFIG_KEYS`。

## 媒体重试

- `media_retry_attempts`: xdown 解析和单个媒体下载的最大尝试次数，默认 `3`，范围 `1-10`。
- `media_retry_delay_seconds`: 两次尝试之间的等待秒数，默认 `5`，范围 `0-60`。

两项位于 `media` 分组，同时保留顶层 invisible 兼容读取。下载重试会删除失败的 UUID 临时文件并从头下载，不进行断点续传；这是为了避免签名 CDN URL 或不稳定 `Range` 支持造成文件拼接损坏。

## 新增配置项清单

新增字段必须同步：

- `_conf_schema.json`
- `config.compat.CONFIG_GROUP_BY_KEY`
- `config.compat.MIGRATABLE_CONFIG_KEYS`（需要兼容旧扁平全局字段时）
- `config.compat.DEFAULT_GROUP_MIGRATION_KEYS`（需要迁移旧默认分组字段时）
- `scheduler.config.ScheduleGroup`（新增调度或 `tweet_groups` 字段时）
- `SchedulerConfigReader.parse_schedule_group()`（新增调度或 `tweet_groups` 字段时）
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
