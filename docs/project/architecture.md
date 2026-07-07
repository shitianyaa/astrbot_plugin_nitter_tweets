# 架构说明

## 模块关系

```text
main.py
  -> command_handlers/
  -> media_support.NitterClient / MediaService
  -> delivery.TweetSender
  -> ai.TweetTranslator / TweetEnricher
  -> scheduler.NitterTweetScheduler
  -> plugin_api.NitterWebAPI

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
- `maintenance.py`: 状态、检查、缓存、seen、队列、发布。
- `subscriptions.py`: 订阅导入、删除、导出、去重。

命令必须调用 `event.stop_event()`。管理员命令必须加 AstrBot admin 权限装饰器。

## RSS 链路

1. `NitterClient.fetch_tweets()` 或 `fetch_tweets_with_stats()`
2. 按实例顺序请求 `/<username>/rss`
3. 处理 HTTP/SSL/timeout 重试
4. 解析 RSS item
5. 过滤转发
6. 可选过滤纯文本
7. 根据 cursor 翻页

纯文本过滤只认当前作者区域的 `/pic/media`、`<video>` 和 Nitter 视频缩略图。引用推文和 `card_img` 不算当前作者媒体。

## 后台检查链路

1. `scheduler.runner.NitterTweetScheduler._tick()` 找到到期分组。
2. `run_check()` 加锁，避免并发检查。
3. 读取该分组 seen map。
4. 按账号抓取 RSS。
5. 首次账号初始化 seen，不推送历史。
6. 非首次账号按 seen 找新推文。
7. 立即模式准备并发送；暂存模式写入 pending queue。
8. 发送成功后更新 seen 或标记 pending。
9. 清理普通缓存，保留需要重试的暂存缓存。

## 发送链路

`delivery.sender.TweetSender` 统一入口：

- Event 路径：手动命令当前会话。
- UMO 路径：后台推送目标。
- OneBot/QQ：按阈值使用合并转发。
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
5. 下载到普通缓存或移动到暂存缓存
6. 普通媒体发送后清理

升级到发送后删除策略时会自动执行一次普通缓存清理。暂存缓存位于 `cache/staged/<group_id>/<status_id>/`，不能被普通缓存清理误删。

## 存储链路

- SQLite 是运行期存储。
- 旧 KV seen 只用于迁移。
- seen 按 `group_id + username` 隔离。
- pending queue 记录 tweet、media、delivered targets、失败状态。
- 发布成功后清理 sent rows。

不要把运行时 SQLite、缓存、`data/` 提交到 Git。

## 包结构

- `scheduler/`: 调度状态机、分组配置、调度结果模型、日志和消息格式。
- `plugin_api/`: AstrBot Plugin Pages 后端 API 和 WebUI 分组编辑。
- `delivery/`: `TweetSender`、平台识别和平台适配器。
- `media_support/`: Nitter RSS、xdown、媒体下载、缓存和视频探测。
- `storage/`: SQLite、pending queue、push history、旧 KV seen 迁移。
- `ai/`: 翻译、AI 识图、AI 评论。
- `rendering/`: 推文文本、MessageChain、OneBot raw nodes 渲染。
- `config/`: 配置读取、分组迁移和旧字段兼容。
- `shared/`: 推文数据模型、group id 和通用工具。
