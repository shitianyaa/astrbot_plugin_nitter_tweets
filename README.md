# Nitter 推文记录

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.6.2-blue" />
  <img alt="License" src="https://img.shields.io/github/license/shitianyaa/astrbot_plugin_nitter_tweets" />
  <img alt="AstrBot" src="https://img.shields.io/badge/AstrBot-plugin-00A86B" />
  <img alt="Nitter" src="https://img.shields.io/badge/Nitter-RSS-black" />
  <img alt="Media" src="https://img.shields.io/badge/media-xdown.app-orange" />
  <br />
  <img src="https://count.getloli.com/@astrbot-plugin-nitter-tweets?name=astrbot-plugin-nitter-tweets&theme=booru-jaypee&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="count" />
</p>

通过 Nitter RSS 获取指定 X/Twitter 用户公开推文，支持手动查询、图片附件、翻译、AI 评论、AI 识图和定时推送。

## 功能

- 手动查询指定用户最近公开推文。
- 定时检查 `watch_users`，发现新推文后推送到 `push_targets`。
- 支持图片附件发送；视频/GIF 可选发送，默认仅保留原帖链接。
- 支持非中文推文翻译。
- 支持按概率追加 AI 评论和 AI 识图描述。
- 支持多个 Nitter 实例按顺序重试。
- 支持多账号更新合并为一轮推送；OneBot v11 使用合并转发，其他平台使用普通消息链。

## 快速开始

### 手动查询

```text
/推文 nasa
/推文 nasa 5
/tweets nasa 5
/推文 https://twitter.com/nasa 5
```

### 定时推送

最小配置：

```text
schedule_enabled = true
watch_users = NASA, BBCWorld
push_targets = aiocqhttp:GroupMessage:123456
```

`push_targets` 是新推文本体的发送目标。执行 `/推文检查` 的会话只会收到检查摘要；如果当前会话不在 `push_targets` 中，不会收到新推文本体。

## 推送目标格式

在要接收推送的群聊或私聊里发送 `/sid`，复制返回的 UMO，填入 `push_targets`。

```text
aiocqhttp:GroupMessage:123456
aiocqhttp:FriendMessage:123456
lark:GroupMessage:oc_xxxxxxxxxxxxx
lark:FriendMessage:ou_xxxxxxxxxxxxx
telegram:GroupMessage:-1001234567890
telegram:FriendMessage:123456789
```

`push_targets` 每行填写一个 UMO。不同平台的前缀以 `/sid` 实际返回为准，不需要手动猜平台 ID。

## 命令

管理员命令：

| 命令 | 说明 |
| --- | --- |
| `/推文状态` | 查看调度器状态、关注账号、推送目标、无效目标和已记录账号数。 |
| `/推文检查` | 立即执行一次定时检查；新推文本体发送到 `push_targets`，命令会话收到检查摘要。 |
| `/推文订阅列表` | 查看当前 `watch_users` 的有效作者、重复项和无效项。 |
| `/推文订阅去重` | 规范化并去重 `watch_users`，移除重复作者和无效条目后保存配置。 |

命令别名：

```text
/nitter_status
/tweets_status
/nitter_check
/tweets_check
/nitter_list
/tweets_list
/nitter_dedup
/tweets_dedup
```

## 配置参考

完整默认值见 [_conf_schema.json](./_conf_schema.json)。

### 基础

| 配置 | 说明 |
| --- | --- |
| `instances` | Nitter 实例列表，建议把自建实例放在第一位。 |
| `request_timeout` | 单个 Nitter 实例超时秒数，超时后尝试下一个实例。 |
| `default_limit` | 手动查询默认获取条数。 |
| `max_limit` | 手动查询最大获取条数。 |
| `cooldown_seconds` | 同一会话同一用户的命令冷却时间。 |

### 定时推送

| 配置 | 说明 |
| --- | --- |
| `schedule_enabled` | 是否启用定时检查。 |
| `watch_users` | 关注账号列表，支持 `NASA`、`@NASA`、`https://x.com/NASA`。 |
| `push_targets` | 新推文本体发送目标；在目标会话发送 `/sid` 获取 UMO 后填入。 |
| `interval_check_enabled` | 是否启用间隔检查。 |
| `check_interval_minutes` | 每 N 分钟检查一次。 |
| `daily_check_enabled` | 是否启用每日固定时间检查。 |
| `daily_check_times` | 每日检查时间列表，格式 `HH:MM`。 |
| `scheduled_fetch_limit` | 定时检查时每个账号拉取最近多少条用于对比。 |
| `notify_no_updates` | 无新推文或首次记录账号时是否发送检查摘要。 |
| `check_on_startup` | 插件启动后是否立即检查一次。 |
| `merge_scheduled_updates` | 是否把本轮所有账号的新推文合并为一轮推送。 |
| `send_target_interval` | 多个目标之间的发送间隔。 |
| `send_user_interval` | 多个账号之间的发送间隔。 |

### 媒体

| 配置 | 说明 |
| --- | --- |
| `send_image_attachments` | 是否发送图片附件；默认开启。 |
| `send_video_attachments` | 是否发送视频/GIF 附件；默认关闭，当前仍在优化，建议先只保留原帖链接。 |
| `max_media_per_tweet` | 单条推文最多发送多少个媒体。 |
| `media_max_size_mb` | 单个媒体大小上限。 |
| `media_cache_retention_days` | 媒体缓存保留天数；设为 `0` 可关闭自动清理。 |
| `xdown_api_url` | Twitter/X 媒体解析 API。 |

### AI

| 配置 | 说明 |
| --- | --- |
| `translate_enabled` | 是否翻译非中文推文。 |
| `translation_provider_id` | 翻译使用的大模型。 |
| `translate_prompt` | 翻译提示词，必须包含 `{text}`；插件会用去除 URL 后的正文替换。 |
| `comment_enabled` | 是否启用 AI 评论。 |
| `comment_provider_id` | AI 评论使用的大模型。 |
| `comment_probability` | 每条推文触发 AI 评论的概率，范围 `0-1`。 |
| `comment_prompt` | 评论提示词，可使用 `{text}`、`{translation}`、`{image_caption}`、`{link}`。 |
| `vision_enabled` | 是否启用 AI 识图。 |
| `vision_provider_id` | AI 识图使用的视觉模型。 |
| `vision_probability` | 每条推文触发 AI 识图的概率，范围 `0-1`。 |
| `vision_max_images` | 每条推文最多识别几张图片，范围 `1-12`。 |
| `vision_prompt` | 识图提示词。 |

## 行为说明

- 首次启用某个账号时，只记录当前 RSS 中已有的推文 ID，不推送历史内容。
- 没有新推文时默认只写日志，不往目标会话发送消息。
- 公共 Nitter 实例不稳定，长期使用建议自建实例。
- 多个 Nitter 实例会按配置顺序尝试；全部失败时日志会显示尝试数量和最后几个错误。
- 图片解析或下载失败时，推文文本和原始链接仍会发送。
- 推文正文里的普通链接会保留在原文位置；Nitter 改写出的 `piped.video` 会还原为 `youtu.be`；翻译只处理去除 URL 后的正文，避免重复链接。
- 合并转发节点仅 OneBot v11/`aiocqhttp` 使用；飞书会优先用飞书原生 `text` 消息发送正文，再发送图片/视频附件；其他平台会自动改用普通消息链发送。
- OneBot 合并转发超时或网络回包状态不确定时，插件会按可能已送达处理，跳过降级重发，避免同一轮出现完整版和纯文本/去视频版重复推送；定时推送会额外发送告警摘要。
- 视频/GIF 附件发送默认关闭，因为目前不太成熟，还在优化中；关闭时会保留原帖链接并提示打开原文查看。开启后仍可能受平台大小、格式、CDN 上传或本地文件权限限制，失败时会去掉视频重试。
- 翻译、AI 评论、AI 识图都使用 AstrBot 的 `context.llm_generate(...)` 接口；模型输出质量和费用取决于所选 provider。

## 常见问题

### 为什么 `/推文检查` 只看到检查结果，没有看到新推文？

`/推文检查` 会把检查摘要回复给命令发起会话。新推文本体只发送到 `push_targets`。如果当前会话不在 `push_targets` 中，当前会话不会收到新推文本体。

### 为什么第一次启用账号不推送历史推文？

插件会先记录当前 RSS 已有推文 ID，之后只推送新出现的 ID，避免首次启用时刷屏。

### 为什么日志里有 HTTP 403？

公共 Nitter 实例可能拒绝访问或返回异常内容。插件会继续尝试下一个实例；如果所有实例都失败，本轮该账号检查失败。

### 为什么媒体没有发出来？

图片和视频附件依赖 `xdown.app` 解析，下载后还会受平台大小、格式和风控限制。附件失败不会阻止推文文本和原文链接发送。

## 致谢

- [`astrbot_plugin_parser`](https://github.com/Zhalslar/astrbot_plugin_parser)：参考了 Twitter/X 媒体解析、媒体下载与消息发送分层思路。
- [Nitter](https://github.com/zedeus/nitter)：提供公开推文 RSS 访问方式。
- [xdown.app](https://xdown.app/)：提供 Twitter/X 媒体解析接口。
- [count.getloli.com](https://count.getloli.com/)：提供 README 访问计数图片。
- [AstrBot](https://github.com/Soulter/AstrBot)、OneBot/aiocqhttp 生态：提供插件运行、消息组件与合并转发能力。
- AI 工具：辅助完成部分代码实现、问题排查与文档整理；最终设计、配置和发布由维护者确认。

## 更新日志

详见 [CHANGELOG.md](./CHANGELOG.md)。

## 许可证

本项目代码采用 MIT License，详见 [LICENSE](./LICENSE)。

许可证仅覆盖本插件源码，不覆盖通过 Nitter、xdown.app 或 X/Twitter 获取的第三方内容，也不改变外部服务各自的使用条款。
