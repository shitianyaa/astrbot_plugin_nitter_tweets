# AGENTS.md

面向后续 AI agent 的项目开发规范。改代码前先读本文件，再读相关模块和测试。

## 文档入口

- 用户使用说明：`README.md`
- 用户进阶说明：`docs/advanced.md`
- 文档索引：`docs/README.md`
- 项目事实：`docs/project/`
- 平台发送指南：`docs/project/platform-delivery.md`
- 开发、测试、维护纪律：`docs/dev/`

`AGENTS.md` 是 agent 快速入口。业务细节优先维护在 `docs/project/`、`docs/advanced.md` 和 `_conf_schema.json`，不要把新的完整专题继续堆进本文件。

## 项目定位

这是 AstrBot 插件 `astrbot_plugin_nitter_tweets`。

核心能力：
- 通过 Nitter RSS 获取公开 X/Twitter 推文。
- 支持手动 `/推文`、`/镜像测试`。
- 支持按 `tweet_groups` 分组定时检查、即时推送、暂存发布。
- 支持图片、视频/GIF、翻译、AI 识图、AI 评论。
- 支持 QQ/OneBot 合并转发、Telegram、Lark/Feishu、weixin_oc 和默认平台发送。
- 使用 SQLite 存储 seen 索引和 pending queue。

## 代码地图

- `main.py`: AstrBot 插件入口、命令注册、服务编排。不要把复杂业务逻辑塞进这里。
- `command_handlers/`: 命令实现。
  - `manual.py`: `/推文`、`/镜像测试`。
  - `maintenance.py`: `/推文状态`、`/推文检查`、缓存、seen、队列、发布。
  - `subscriptions.py`: 订阅导入、删除、导出、去重。
- `scheduler/`: 后台检查、seen 对比、暂存发布、推送编排。高风险模块。
  - `runner.py`: `NitterTweetScheduler` 主状态机。
  - `config.py`: 分组配置解析，生成 `ScheduleGroup`。
  - `models.py`: 调度结果、批次模型。
  - `formatting.py`: 调度日志和消息格式。
- `config/compat.py`: AstrBot 配置分组读取、旧配置迁移、默认分组迁移。
- `media_support/client.py`: Nitter RSS 抓取、分页、转发过滤、纯文本过滤。
- `media_support/network.py`: 直接请求、代理配置解析、认证和多代理故障切换。
- `media_support/service.py`: xdown 解析、媒体候选归一化、下载、视频时长/分辨率限制。
- `media_support/cache.py`: 普通缓存、暂存缓存、发送后清理。
- `media_support/extensions.py`: 媒体类型和扩展名分类。
- `delivery/`: 平台适配器。
  - `delivery/sender.py`: 发送编排、合并转发、降级、平台能力判断入口。
  - `platforms.py`: UMO 和 AstrBot 平台能力识别。
  - `onebot.py`: OneBot/QQ 合并转发。
  - `lark.py`: Lark/Feishu 原生 post 和降级发送。
  - `lark_support.py`: Lark/Feishu client、post、媒体发送工具。
  - `telegram.py`: Telegram flood control retry。
  - `default.py`: AstrBot 通用 MessageChain 发送。
- `rendering/tweets.py`: 推文文本、MessageChain、OneBot raw nodes 渲染。
- `ai/enrichment.py`: 翻译、AI 识图、AI 评论。
- `storage/`: SQLite 存储、pending queue、push history 和旧 KV 迁移。
  - `sqlite.py`: SQLite schema 和查询。
  - `adapter.py`: 异步存储适配层。
  - `seen.py`: 旧 KV seen 迁移和 seen ID 合并规则。
- `shared/`: `TweetItem`、`TweetMedia`、group id 和通用工具。
- `plugin_api/`: Plugin Pages 后端 API 和 WebUI 分组编辑。
- `_conf_schema.json`: AstrBot WebUI 配置 schema。
- `README.md`, `docs/advanced.md`, `CHANGELOG.md`: 用户文档。
- `scripts/probe_nitter_fetch.py`: 本地诊断 Nitter RSS 抓取。
- `scripts/probe_proxy_fetch.py`: 使用单条显式代理诊断 RSS、xdown 和媒体下载完整链路。

## 必守规则

- 保持 `main.py` 轻量。新增功能优先放到对应 service、scheduler、command mixin、delivery adapter 或 renderer。
- 命令处理函数必须 `event.stop_event()`，并通过 `event.send(event.plain_result(...))` 或 sender 封装返回。
- 管理类命令需要 `@filter.permission_type(filter.PermissionType.ADMIN)`。
- 不要硬编码 provider ID、平台 token、群号、用户 ID、Nitter 实例或本机路径。
- 不要把运行数据提交进仓库。尤其不要提交 `data/`、缓存、SQLite 数据库、下载文件。
- 不要改动用户未要求的功能、格式和文案。这个仓库已有大量行为测试，优先保持兼容。
- 代码需要同时支持包内相对导入和测试环境的顶层导入；新增模块参考现有 `try: from .x import ... except ImportError` 模式。
- 提交信息只写真实变更描述，不要加入 AI attribution、`Generated with ...`、`Co-Authored-By`。

## 配置和迁移

新增配置项时必须同步：
- `_conf_schema.json`
- `config.compat.CONFIG_GROUP_BY_KEY`，如果是分组后的全局配置
- `config.compat.MIGRATABLE_CONFIG_KEYS`，如果需要从旧扁平配置迁移
- `config.compat.DEFAULT_GROUP_MIGRATION_KEYS`，如果是默认分组旧字段
- `scheduler.config.ScheduleGroup` 和 `SchedulerConfigReader`，如果是调度或 `tweet_groups` 字段
- README 或 `docs/advanced.md`
- `tests/test_subscription_import.py`

配置分层约定：
- `basic`: Nitter、代理列表、默认数量、冷却、平台基础项。
- `media`: 图片、视频、xdown、缓存。
- `ai_translation`, `ai_comment`, `ai_vision`: AI 相关。
- `schedule`: 后台检查总开关、全局检查频率。
- `deferred`: 暂存发布全局参数。
- `push`: `tweet_groups`、推送间隔、合并阈值。
- `performance`: 后台账号并发拉取、并发准备和专用镜像池。
- `logging`: 日志模式。

`tweet_groups` 是分组行为的主入口。`watch_users` 和 `push_targets` 顶层字段只是旧版兼容字段。

分组字段规则：
- `group_id` 是存储 ID，必须稳定。新建默认分组使用 `default`。
- 已有 `group_id` 必须保留；旧 `global` 可作为显式存储 ID 保留，也作为默认分组旧别名兼容。
- 旧配置缺失 `group_id` 时，安全英文数字分组名（如 `coser`）是旧运行时事实 ID，必须继承；普通显示名才生成 `group_N`。
- seen 索引按 `group_id + username` 隔离。
- 每个分组的 `watch_users`、`push_targets`、`enabled`、`interval_check_enabled`、`daily_check_times`、`deferred_publish_enabled`、`filter_plain_text_enabled` 都是独立行为。

## RSS 抓取和过滤

`media_support/client.py` 是 RSS 行为入口。

必须保持：
- `fetch_tweets(username, limit)` 默认不跳过纯文本，供手动 `/推文` 和 `/镜像测试` 使用。
- `fetch_tweets_with_stats(..., skip_plain_text=True)` 供后台检查统计 filtered 数量。
- 转发过滤比较 RSS item 主链接作者和订阅账号；作者不同视为转发。
- 整页被转发或纯文本过滤时，如果有下一页 cursor，必须继续翻页。
- 真正空 RSS feed 才能触发 empty feed。

纯文本过滤规则：
- 只在后台定时/暂存发布按分组开关启用。
- 手动 `/推文`、`/镜像测试` 不受影响。
- `/pic/media` 和 `<video>` 算作者上传媒体。
- `/pic/card_img` 不算作者上传媒体。
- Twitter Article（长文）封面图包在 `<a href="/i/article/...">` 里，不算作者上传媒体。
- 引用推文里的媒体不算当前作者上传媒体。
- 修改 `_AuthorMediaDetector` 时必须补 Nitter RSS HTML 片段回归测试。

本地诊断：

```powershell
python scripts/probe_nitter_fetch.py nasa 5
python scripts/probe_nitter_fetch.py nasa 5 --include-reposts
python scripts/probe_nitter_fetch.py ss11_moon 20 --skip-plain-text --timeout 20 --retry-delay 0
```

## 调度、seen 和暂存发布

`scheduler/` 是高风险目录。修改前先读对应测试。

行为约束：
- 首次启用账号只初始化 seen，不推送历史。
- 后台检查先发现本轮所有新推文，再按目标类型发送。
- 普通目标可以逐条即时发送；QQ/OneBot 目标会按阈值缓冲到后面合并发送。
- `force_immediate=True` 的手动 `/推文检查` 必须绕过暂存队列，只发当前会话。
- 暂存发布开启时，本轮新推文写入 SQLite pending queue。
- 暂存媒体应移动到 `cache/staged/<group_id>/<status_id>/`。
- 发布成功后清理 sent rows 和暂存媒体；目标失败时保留待重试记录。
- seen 更新时机不能提前到发送成功之前，避免准备或发送失败导致漏推。
- 取消、异常、发送失败路径必须清理本轮普通缓存，但不能误删暂存媒体。

新增调度字段或结果字段时同步：
- `ScheduleGroup`
- `ScheduledCheckResult`
- `status_summary()`
- `format_log_summary()`
- `format_brief_log_lines()`
- `format_message()`
- 相关测试

## 媒体和缓存

媒体流程：
- RSS 只提供文本和链接。
- `MediaService` 通过 xdown 解析媒体候选。
- 发现视频/GIF 时，跳过同条推文里的图片候选，避免发送封面图。
- 视频/GIF 默认关闭；开启后按分辨率、时长和大小限制下载。
- 图片/视频下载失败不能阻止文本和原文链接发送。

缓存规则：
- 普通缓存位于 AstrBot 插件数据目录。
- 普通媒体在本轮发送流程结束后删除。
- 暂存缓存不能被普通发送后清理误删。
- 清理逻辑要统计 removed、failed、images、videos、other、empty_dirs。

修改媒体逻辑时优先补：
- `tests/test_media_resolution.py`
- `tests/test_media_cleanup.py`
- 必要时补 `tests/test_deferred_scheduler.py`

## 平台发送

平台目标使用 `/sid` 返回的完整 UMO：`platform_id:MessageType:session_id`。

发送规则：
- OneBot/QQ 目标支持合并转发，阈值由 `merge_tweet_threshold` 控制。
- OneBot 合并转发失败时会尝试去视频重试或纯文本降级。
- OneBot 合并转发遇到不确定送达错误时，按可能已送达处理，避免重复推送。
- Lark/Feishu 优先原生 post，失败再降级。
- Telegram 需要处理 flood control retry。
- weixin_oc 和其他平台走 default adapter。
- 不要只按 UMO 第一段判断平台类型；使用 `PlatformResolver`。

修改平台发送时优先补：
- `tests/test_deferred_scheduler.py` 中 custom platform、OneBot、Telegram、video split 相关测试。
- `tests/test_subscription_import.py` 中 Lark 标题和命令行为测试。

## AI 处理

处理顺序：
- 翻译
- 媒体下载
- AI 识图
- AI 评论

规则：
- 翻译和评论 provider 通过配置读取，不要硬编码。
- 评论不会仅凭原文触发；必须有翻译结果或识图结果。
- AI 失败需要区分正常跳过和用户可见 warning。
- 手动查询按单条推文准备后立即发送，避免一条慢推文阻塞全部结果。

修改 AI 行为时优先补 `tests/test_subscription_import.py` 的 `TweetEnricherTest` 相关测试。

## 文档同步

用户可见行为变更必须同步：
- `README.md`: 首页功能、命令、常用配置、行为要点。
- `docs/advanced.md`: 平台差异、流程、完整配置、边界行为。
- `_conf_schema.json`: WebUI 文案、默认值、hint。
- `CHANGELOG.md`: 发布前补变更记录。
- `metadata.yaml`: 版本或能力描述变化时同步。

文档风格：
- 直接写行为和用法，不写泛泛介绍。
- 配置名、命令、文件名使用反引号。
- 行为边界必须明确，例如“手动命令不受影响”“暂存发布只由分组开关控制”。

## 测试选择矩阵

通用快速检查：

```powershell
python -m pytest -q
ruff check .
python -m py_compile main.py scheduler/__init__.py scheduler/runner.py scheduler/config.py scheduler/models.py media_support/client.py media_support/service.py delivery/sender.py
```

按变更类型选择：
- RSS、分页、转发过滤、纯文本过滤：`python -m pytest -q tests/test_nitter_pagination.py`
- 调度、seen、暂存、发送顺序、平台发送：`python -m pytest -q tests/test_deferred_scheduler.py`
- 配置 schema、迁移、命令解析、订阅维护、AI：`python -m pytest -q tests/test_subscription_import.py`
- 媒体解析、视频限制、下载重试：`python -m pytest -q tests/test_media_resolution.py`
- 缓存和暂存媒体清理：`python -m pytest -q tests/test_media_cleanup.py`
- SQLite pending queue：`python -m pytest -q tests/test_pending_storage.py`
- 存储适配和旧 KV 迁移：`python -m pytest -q tests/test_storage_adapter.py`
- SQLite 线程安全：`python -m pytest -q tests/test_sqlite_threading.py`

如果改了公共模型、`delivery/sender.py`、`scheduler/` 或 `config/compat.py`，优先跑全量测试。

## 本地调试

RSS 抓取：

```powershell
python scripts/probe_nitter_fetch.py nasa 5
python scripts/probe_nitter_fetch.py nasa 5 --skip-plain-text
python scripts/probe_nitter_fetch.py nasa 5 --include-reposts
python scripts/probe_proxy_fetch.py socks5h://127.0.0.1:1080
```

视频下载诊断：

```powershell
python scripts/test_video_download.py
```

不要把诊断产生的缓存、数据库、`data/` 内容加入提交。

## Review 清单

提交前检查：
- 是否只改了任务相关文件。
- 是否保留手动命令和后台调度的行为差异。
- 是否没有提前写 seen 导致失败后漏推。
- 是否没有把暂存媒体当普通缓存删除。
- 是否没有把 Lark/Telegram/weixin_oc 当 OneBot 处理。
- 是否没有把引用推文媒体当当前作者媒体。
- 是否同步 schema、`config/compat.py`、README/docs、测试。
- 是否跑了对应测试。
- `git status --short` 是否只有预期文件。

## Git 规范

- 不要使用 `git reset --hard`、`git checkout --` 等会丢用户改动的命令，除非用户明确要求。
- 只暂存本次任务相关文件。
- 不提交 `data/`、缓存、数据库、下载产物。
- 提交信息使用简短祈使句，例如 `Ignore quoted media in plain-text filter`。
- 不写 `Generated with ...`。
- 不写 `Co-Authored-By`。
