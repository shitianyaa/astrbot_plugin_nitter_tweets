# Nitter 推文记录

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.7.0-blue" />
  <img alt="License" src="https://img.shields.io/github/license/shitianyaa/astrbot_plugin_nitter_tweets" />
  <img alt="AstrBot" src="https://img.shields.io/badge/AstrBot-plugin-00A86B" />
  <img alt="Nitter" src="https://img.shields.io/badge/Nitter-RSS-black" />
  <img alt="Media" src="https://img.shields.io/badge/media-xdown.app-orange" />
  <br />
  <img src="https://count.getloli.com/@astrbot-plugin-nitter-tweets?name=astrbot-plugin-nitter-tweets&theme=booru-jaypee&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="count" />
</p>

通过 Nitter RSS 获取指定 X/Twitter 用户公开推文，支持手动查询、图片附件、翻译、AI 评论、AI 识图和定时推送。

## 功能

- 手动查询指定用户最近公开推文，并提供独立的 Nitter 镜像站测试命令。
- 定时检查 `watch_users`，发现新推文后推送到 `push_targets`；也可在插件配置里通过 `tweet_groups` 配置多个独立推文分组。
- 支持图片附件发送；视频/GIF 可选发送，默认仅保留原帖链接。
- 支持非中文推文翻译。
- 支持按概率追加 AI 评论和 AI 识图描述。
- 支持多个 Nitter 实例按顺序重试。
- 支持为 QQ/`aiocqhttp` 按新推文数量阈值启用 OneBot v11 `Node/Nodes` 合并转发；飞书/Lark、Telegram 和微信 OC 始终走普通逐账号发送，其中飞书会优先把单个账号的正文和图片放入同一条原生 `post` 消息。

## 快速开始

### 手动查询

```text
/推文 nasa
/推文 nasa 5
/推文 https://twitter.com/nasa 5
```

省略数量时使用 `default_limit`，数量会被限制在 `1` 到 `max_limit` 之间。

### 镜像测试

```text
/镜像测试 nitter.top
/镜像测试 3 nitter.top
/镜像测试 nasa nitter.top
/镜像测试 nasa 3 nitter.top
```

`/镜像测试` 默认测试 `nasa`，默认获取 `1` 条；用户名和数量都可以省略，镜像站只影响本次测试，不会写入 `instances` 配置。

### 定时推送

最小配置：

```text
schedule_enabled = true
watch_users = NASA, BBCWorld
push_targets = aiocqhttp:GroupMessage:123456
```

`push_targets` 是新推文本体的发送目标。执行 `/推文检查` 的会话只会收到检查摘要；如果当前会话不在 `push_targets` 中，不会收到新推文本体。

自定义分组可在插件配置的 `tweet_groups` 中添加。每个分组都有独立的关注账号、推送目标、间隔检查、每日定点、拉取条数和发送间隔；不填写 `tweet_groups` 时只使用上面的全局定时配置。

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

## 平台支持与要求

| 平台 | 适配器类型 | 特殊要求/说明 |
| --- | --- | --- |
| QQ | `aiocqhttp` | 支持文本、图片和 OneBot v11 `Node/Nodes` 合并转发；合并转发失败时会降级重试。 |
| Feishu / Lark | `lark` | 普通逐账号发送；优先使用飞书原生 `post` 将正文和本地图片放在同一条消息中，失败时降级为 `text` 正文加普通媒体附件；暂不支持 QQ 式合并转发。 |
| Telegram | `telegram` | 走 AstrBot 通用消息链发送；在群聊中使用前建议确认 BotFather 隐私模式和群内权限。 |
| 微信 OC | `weixin_oc` | 走 AstrBot 通用消息链发送；媒体附件是否可用取决于微信 OC 适配器的上传能力、会话 token 和平台限制。 |

## 命令

常用命令：

| 命令 | 说明 |
| --- | --- |
| `/推文 用户名 [数量]` | 查询指定公开 X/Twitter 用户最近推文。 |
| `/镜像测试 [用户名] [数量] 镜像站` | 用临时 Nitter 镜像站测试获取推文；默认用户名 `nasa`，默认数量 `1`。 |
| `/推文状态` | 查看调度器状态、全局分组、自定义分组、关注账号、推送目标、无效目标和已记录账号数。 |
| `/推文检查 [分组名]` | 立即执行一次定时检查；不填时检查全局分组，也可填写自定义分组名称、分组 ID 或别名。 |
| `/推文订阅列表` | 查看当前 `watch_users` 的有效作者、重复项和无效项。 |
| `/推文订阅去重` | 规范化并去重 `watch_users`，移除重复作者和无效条目后保存配置。 |

## 配置参考

完整默认值见 [_conf_schema.json](./_conf_schema.json)。

### 基础

| 配置 | 说明 |
| --- | --- |
| `instances` | Nitter 实例列表，建议把自建实例放在第一位。 |
| `request_timeout` | 单个 Nitter 实例超时秒数，超时后尝试下一个实例。 |
| `default_limit` | 手动 `/推文` 查询默认获取条数。 |
| `max_limit` | 手动查询最大获取条数。 |
| `cooldown_seconds` | 同一会话同一用户的命令冷却时间。 |

### 定时推送

| 配置 | 说明 |
| --- | --- |
| `schedule_enabled` | 是否启用定时检查。 |
| `watch_users` | 关注账号列表，支持 `NASA`、`@NASA`、`https://x.com/NASA`。 |
| `push_targets` | 新推文本体发送目标；在目标会话发送 `/sid` 获取 UMO 后填入。 |
| `tweet_groups` | 自定义推文分组列表；每组可单独配置 `watch_users`、`push_targets`、间隔检查、每日定点、拉取条数和发送间隔。 |
| `interval_check_enabled` | 是否启用间隔检查。 |
| `check_interval_minutes` | 每 N 分钟检查一次。 |
| `daily_check_enabled` | 是否启用每日固定时间检查。 |
| `daily_check_times` | 每日检查时间列表，格式 `HH:MM`。 |
| `scheduled_fetch_limit` | 定时检查时每个账号拉取最近多少条用于对比。 |
| `notify_no_updates` | 无新推文或首次记录账号时是否发送检查摘要。 |
| `check_on_startup` | 插件启动后是否立即检查一次。 |
| `merge_tweet_threshold` | QQ/`aiocqhttp` 新推文总数达到多少条时启用合并转发；`0` 关闭，默认 `2`。 |
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
- 现有顶层定时配置会作为 `global` 全局分组运行；`tweet_groups` 中的自定义分组会独立运行，并拥有独立的已见推文 ID。旧的按账号已见记录会自动兼容到全局分组。
- 没有新推文时默认只写日志，不往目标会话发送消息。
- 公共 Nitter 实例不稳定，长期使用建议自建实例。
- 多个 Nitter 实例会按配置顺序尝试；全部失败时日志会显示尝试数量和最后几个错误。
- 图片解析或下载失败时，推文文本和原始链接仍会发送。
- 推文正文里的普通链接会保留在原文位置；Nitter 改写出的 `piped.video` 会还原为 `youtu.be`；翻译只处理去除 URL 后的正文，避免重复链接。
- QQ 合并转发由 `merge_tweet_threshold` 控制；达到阈值时 OneBot v11/`aiocqhttp` 使用 `Node/Nodes` 合并转发，单次推文较多时会按每批最多 8 条自动分批，避免大合并包漏节点。飞书/Lark、Telegram、微信 OC 和其他平台不受该阈值影响，始终逐账号普通发送；飞书逐账号发送时会优先用原生 `post` 同框发送正文和图片。
- OneBot 合并转发超时或网络回包状态不确定时，插件会按可能已送达处理，跳过降级重发，避免同一轮出现完整版和纯文本/去视频版重复推送；定时推送只在日志记录短提示。
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

## 更新日志

详见 [CHANGELOG.md](./CHANGELOG.md)。

## 许可证

本项目代码采用 MIT License，详见 [LICENSE](./LICENSE)。

许可证仅覆盖本插件源码，不覆盖通过 Nitter、xdown.app 或 X/Twitter 获取的第三方内容，也不改变外部服务各自的使用条款。
