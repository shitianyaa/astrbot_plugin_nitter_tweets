# 架构说明

## 模块关系

```text
main.py
  -> command_handlers/
  -> media_support.NitterClient / MediaService / html_backend
  -> delivery.TweetSender
  -> ai.TweetTranslator
  -> scheduler.NitterTweetScheduler
  -> plugin_api.NitterWebAPI
  -> shared.observability

NitterTweetScheduler
  -> scheduler.config.SchedulerConfigReader
  -> storage.StorageAdapter / SQLiteStorage
  -> media_support.NitterClient
  -> media_support.MediaService
  -> delivery.TweetSender
```

## `main.py`

`main.py` 只负责：

- `@register` 插件注册。
- 初始化配置迁移。
- 创建 Nitter、媒体、发送、AI、调度服务。
- 注册 AstrBot 命令。
- 生命周期启动和停止调度器。

不要把 RSS、媒体、AI、发送或调度细节写回 `main.py`。

## 命令层

`command_handlers/` 只负责命令参数、权限、用户提示和调用服务。

- `manual.py`: 手动查询和镜像测试。
- `maintenance.py`: 状态、检查、缓存、seen。
- `subscriptions.py`: 订阅导入、删除、导出、去重。
- `link_preview.py`: 被动 status 链接解析入口；只处理合法白名单链接，成功后才记录防抖状态。

命令必须调用 `event.stop_event()`。管理员命令必须加 AstrBot admin 权限装饰器。

## RSS 链路

1. 手动和后台都通过 `NitterService`；内部 RSS parser 处理用户 feed，HTML parser 处理用户后备、搜索和 List。
2. Blogger 按 `instances` 顺序请求 `/<username>/rss`；Tag/List 使用同一列表串行请求搜索或 List 页面。
3. 处理 HTTP/SSL/timeout、限流和普通错误页
4. 解析 RSS item 或 HTML item
5. 过滤转发（Blogger、Tag、List 均按“全局总开关 && 分组子开关”的有效值处理）
6. 可选过滤纯文本
7. 手动路径按请求数量停止；后台 Blogger 扫描首屏约 20 条并按 `Min-Id` 分页；Tag 最多保留 20 条候选；List 首轮最多 20 条，后续本轮扫描可超过 20 条并按旧水位分页到边界或游标结束

纯文本过滤只认当前作者区域的 `/pic/media`、`<video>` 和 Nitter 视频缩略图。引用推文和 `card_img` 不算当前作者媒体。

HTML 只分类真实时间线、空页、登录/维护/错误页和异常页面，不再实现或检测公共实例挑战。

## 后台检查链路

1. `scheduler.runner.NitterTweetScheduler._tick()` 找到到期分组。
2. 调度存储初始化由后台循环和手动/Plugin Pages 检查共享同一异步锁；迁移未完成时不会进入抓取或发送。
3. `run_check()` 加锁，避免并发检查；启动首检、手动检查和 WebUI 检查会等待已有检查完成，普通定时触发则返回已在运行。
4. 读取该分组 seen map 和独立扫描基准组。
5. Blogger 按 RSS 首屏与基准分页；Tag/List 都把旧扫描水位传给 HTML 分页器，在 `html_max_pages` 范围内寻找基准。扫描未完整且当前第一页有有效状态 ID 时，按 `max_tweets_per_check` 处理：上限为 0 时不推送并自动重建第一页基准，上限大于 0 时最多推送该数量，所有目标处理完后自动重建第一页基准；准备失败、基准无效或基准写入失败时保留旧水位，发送调用失败则按本轮跳过处理。Tag 使用 `q:`、List 使用 `list:` seen 键。
6. 首次订阅源初始化 seen 和最近最多 20 个扫描基准 ID，不推送历史；Tag/List 真正空首轮保持未初始化，有原始结果但全被过滤时记录空扫描水位。
7. 非首次订阅源按命中的基准 ID 确定时间边界，再用 seen 排除已处理的推文。
8. 按推文 ID 与 seen 做差集，所有新推文都在本轮准备；发送阶段再按每个目标 UMO 的共享作者黑名单生成允许子集。
9. 目标黑名单过滤的批次直接标记该目标已处理，实际发送只包含允许作者；发送成功或失败后目标都视为本轮已处理，所有目标处理完后更新 seen，扫描完整且本轮选中内容均已处理后替换当前扫描基准组。
10. 分页完整扫描后才发送新推文；Tag/List 分页预算耗尽且第一页有有效状态 ID 时按分组上限自动处理并重建第一页基准，准备失败时不跨过未处理推文，发送调用失败则跳过当前批次并清理普通缓存。

当 `check_on_startup=true` 时，存储初始化完成后按分组顺序执行一次独立 `startup` 检查，覆盖仅每日、仅间隔和无定时槽位的启用分组；首检结束后锚定当前槽位，避免下一轮重复触发。

## 发送链路

`delivery.sender.TweetSender` 统一入口：

- Event 路径：手动命令当前会话。
- UMO 路径：后台推送目标。
- 私人号 OneBot：按阈值使用合并转发；QQ Official 走 `QQOfficialDeliveryAdapter`，正文 Event/UMO 使用官方 Markdown，媒体独立发送并在 Markdown 被拒时降级为纯文本，不使用 OneBot 合并转发。
- Lark/Feishu：优先 native post。
- Telegram：处理 flood control。
- 其他平台：默认 MessageChain。

平台识别必须通过 `PlatformResolver`，不要只看 UMO 第一段。

平台发送开发细节见 `docs/project/platform-delivery.md`。

## 媒体链路

1. `MediaService.attach_media()`
2. xdown 解析候选
3. 视频/GIF 优先，跳过同条推文里的图片候选
4. 分辨率、时长、大小限制
5. 下载到普通缓存
6. 普通媒体发送后清理

定时分组可开启 `media_only_enabled`：RSS 先过滤没有当前作者媒体的推文，媒体准备结果区分 `ready`、`transient_failure`、`policy_skipped` 和 `no_candidate`。`transient_failure` 与 `no_candidate` 不写 seen 且不推进扫描基准，下轮重试；`policy_skipped` 允许基准推进。手动命令和历史重推始终使用完整内容。

升级到发送后删除策略时会自动执行一次普通缓存清理。

## 存储链路

- SQLite 是运行期存储。
- 旧 KV seen 只用于迁移。
- seen 按 `group_id + username` 隔离。
- scan watermark 基准组按 `group_id + username` 独立存储，保存最近最多 20 个 status ID，负责分页边界和首次初始化状态；它不等同于 seen 最大 ID，也不随本轮扫描条数无限增长。
- push history 记录成功、部分失败和发送失败的推送快照，供 WebUI 历史查看和重推。

不要把运行时 SQLite、缓存、`data/` 提交到 Git。

## 包结构

- `scheduler/`: 调度状态机、分组配置、调度结果模型、日志和消息格式。
- `plugin_api/`: AstrBot Plugin Pages 后端 API 和 WebUI 分组编辑。
- `delivery/`: `TweetSender`、平台识别和平台适配器。
- `delivery/media_transport.py` + `delivery/sender_transport.py`: 媒体线上编码梯度（path / base64 / url / skip）与其执行；只有 OneBot 适配器启用，见[平台发送指南](./platform-delivery.md#媒体传输编码)。
- `media_support/`: Nitter RSS、xdown、媒体下载、缓存和视频探测。
- `storage/`: SQLite、push history、旧 KV seen 迁移。
- `ai/`: 翻译。
- `rendering/`: 推文文本、平台安全 Markdown、MessageChain、OneBot raw nodes 渲染。
- `config/`: 配置读取、分组迁移和旧字段兼容。
- `shared/`: 推文数据模型、group id 和通用工具。
- `shared/observability.py`: 脱敏日志字段、结构化任务摘要和安全日志辅助函数。
