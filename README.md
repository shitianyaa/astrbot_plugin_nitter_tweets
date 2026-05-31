# Nitter 推文记录

<div align="center">
  <img src="https://count.getloli.com/@astrbot-plugin-nitter-tweets?name=astrbot-plugin-nitter-tweets&theme=booru-jaypee&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="count" />
</div>

通过 Nitter RSS 获取指定 X/Twitter 用户最近公开推文，并以聊天记录/合并转发形式发送。

本项目由 GPT-5.5 协助完成开发与文档整理。

## 用法

```text
/推文 nasa
/推文 nasa 5
/tweets nasa 5
/推文 https://twitter.com/nasa 5
```

## 媒体下载

插件会先通过 Nitter RSS 拿到推文链接，再参考 `astrbot_plugin_parser-main` 的实现，把推文链接转成：

```text
https://x.com/<username>/status/<tweet_id>
```

然后请求 `xdown.app/api/ajaxSearch` 获取图片、MP4、GIF 下载地址。媒体会下载到插件目录下的 `cache/`，再作为本地 `Image` / `Video` 消息段放入合并转发节点。缓存默认保留 3 天，插件会自动清理超过保留时间的文件。

如果媒体解析或下载失败，推文文本和原始链接仍会正常发送，并在对应推文中显示媒体提示。

## 非中文推文翻译

开启 `translate_enabled` 后，插件会先用轻量规则判断推文是否不像中文；需要翻译时，会调用 AstrBot 已配置的大模型，把译文追加到推文节点中。

手动 `/推文` 查询会优先使用当前会话绑定的模型。定时推送没有真实触发会话，建议在 `translation_provider_id` 中选择一个固定模型；留空时会尝试使用第一个推送目标的默认模型。

可通过 `translate_prompt` 自定义翻译风格，例如要求保留术语、改成口语化中文等。提示词中需要包含 `{text}`，插件会把推文正文替换进去。

翻译链路会输出 `[NitterTweets] translation ...` 日志，可用于确认是否开启、是否匹配为非中文、使用了哪个 provider，以及模型是否返回译文。

## AI 评论与识图

开启 `comment_enabled` 后，插件会在发送前按 `comment_probability` 概率调用文本大模型，为每条推文追加一段 `AI评论`。开启 `vision_enabled` 后，会按 `vision_probability` 概率调用视觉模型识别推文中的图片（数量由 `vision_max_images` 控制），并追加 `AI识图`。多张图片会并发识别，结果以 `[1/N]` 格式拼接。

如果同一条推文同时触发识图和评论，插件会先识图，再把图片描述、推文原文和已有中文翻译一起交给评论模型。模型调用失败不会影响原推文、媒体和链接发送。

`comment_provider_id` 和 `vision_provider_id` 可分别选择模型。识图模型留空时会优先使用 AstrBot 全局图片描述模型 `default_image_caption_provider_id`；仍找不到时再尝试会话默认模型或第一个 provider。

## 配置

- `instances`：Nitter 实例列表，建议把自建实例放在第一位。
- `default_limit`：默认获取条数。
- `max_limit`：单次最大条数。
- `download_media`：是否解析并下载推文媒体。
- `download_images`：是否下载图片。
- `download_videos`：是否下载视频和 GIF。
- `max_media_per_tweet`：单条推文最多发送多少个媒体。
- `media_max_size_mb`：单个媒体大小上限。
- `media_cache_retention_days`：媒体缓存保留天数，默认 3 天；设为 0 可关闭自动清理。
- `xdown_api_url`：Twitter/X 媒体解析 API。
- `translate_enabled`：是否翻译非中文推文。
- `translation_provider_id`：翻译使用的大模型，支持在 WebUI 选择现有 provider。
- `translate_chinese_ratio_threshold`：中文占比低于该值时判定为非中文。
- `translate_prompt`：翻译提示词，需包含 `{text}`。
- `comment_enabled`：是否启用 AI 评论。
- `comment_provider_id`：AI 评论使用的大模型。
- `comment_probability`：每条推文触发 AI 评论的概率，范围 0-1。
- `comment_prompt`：评论提示词，可使用 `{text}`、`{translation}`、`{image_caption}`、`{link}`。
- `vision_enabled`：是否启用 AI 识图。
- `vision_provider_id`：AI 识图使用的视觉模型，留空优先使用 AstrBot 全局图片描述模型。
- `vision_probability`：每条推文触发 AI 识图的概率，范围 0-1。
- `vision_max_images`：每条推文最多识别几张图片，范围 1-12，默认 1。
- `vision_prompt`：识图提示词。

## 定时检查

开启 `schedule_enabled` 后，插件会定时检查 `watch_users` 是否有新推文，并推送到 `push_targets`。

首次启用某个账号时，只会记录当前 RSS 中已有的推文 ID，不会推送历史内容，避免刷屏。之后发现新 ID 才会推送。

默认情况下，没有新推文时只写日志，不往群里发消息。若希望每次检查都有可见反馈，可开启 `notify_no_updates`，插件会在无更新或首次记录账号时向 `push_targets` 发送检查摘要。

默认情况下，插件重启后不会立刻检查新推文，而是等待下一个间隔检查或每日定点时间。若希望启动后立即补查，可开启 `check_on_startup`。

默认情况下，多个关注账号同时有更新时会按账号分别发送聊天记录。若希望“本轮检查发现的所有新推文”合并到一条聊天记录，可开启 `merge_scheduled_updates`。

### 关键配置

- `watch_users`：关注账号列表，支持 `NASA`、`@NASA`、`https://x.com/NASA`；运行时会按规范化用户名去重。
- `push_targets`：推送目标列表，支持：
  - `group:123456`
  - `private:123456`
  - `aiocqhttp:group:123456`
  - `aiocqhttp:GroupMessage:123456`
- `platform_id`：`group:ID` / `private:ID` 未指定平台时使用，留空自动检测。
- `interval_check_enabled` + `check_interval_minutes`：每 N 分钟检查一次。
- `daily_check_enabled` + `daily_check_times`：每天固定时间检查，可与间隔检查同时开启。
- `scheduled_fetch_limit`：定时检查时每个账号拉取最近多少条用于对比。
- `notify_no_updates`：无新推文或首次记录账号时是否向推送目标发送检查摘要，默认关闭。
- `check_on_startup`：插件启动后是否立即检查一次，默认关闭。
- `merge_scheduled_updates`：是否把本轮所有账号的新推文合并成一条聊天记录发送，默认关闭。
- `send_target_interval`：多个目标之间的发送间隔。
- `send_user_interval`：多个账号之间的发送间隔。

### 诊断命令

以下命令仅管理员可用：

```text
/推文状态
/nitter_status
/tweets_status
/推文检查
/nitter_check
/tweets_check
/推文订阅列表
/nitter_list
/tweets_list
/推文订阅去重
/nitter_dedup
/tweets_dedup
```

- `/推文状态`：查看调度器是否运行、定时开关、关注账号、推送目标、无效目标和已记录账号数。
- `/推文检查`：立即执行一次定时检查；如发现新推文，会按 `push_targets` 正常推送，并向命令发起者返回检查摘要。
- `/推文订阅列表`：列出当前 `watch_users` 中的有效订阅作者，并显示重复项和无效项统计。
- `/推文订阅去重`：规范化并去重 `watch_users`，会移除重复作者和无效条目，然后保存配置。

## 说明

- 公共 Nitter 实例不适合高频抓取，长期稳定使用建议自建实例。
- 视频/GIF 比图片更容易触发平台大小、格式或风控限制；如果合并转发失败，插件会自动去掉视频重试一次，受影响推文会显示原文链接，日志和 `/推文检查` 会提示本次发送已降级；仍失败则回退为普通文本。
- 本插件不依赖 `astrbot_plugin_parser-main` 运行，只参考了它的 Twitter 媒体解析思路。
- 翻译功能使用 AstrBot 的 `context.llm_generate(...)` 接口；大模型输出质量和费用取决于你选择的 provider。
- AI 评论与识图也使用 AstrBot 的 `context.llm_generate(...)` 接口；识图只分析已下载到本地的图片，不分析视频内容。

## 致谢

本插件在实现过程中参考和借鉴了以下项目与服务，在此表示感谢：

- [`astrbot_plugin_parser`](https://github.com/Zhalslar/astrbot_plugin_parser)：参考了其中 Twitter/X 媒体解析、媒体下载与消息发送分层的实现思路。
- [Nitter](https://github.com/zedeus/nitter) 及各公共实例维护者：提供公开推文 RSS 的访问方式。公共实例不建议用于高频抓取，长期使用请自建实例并控制请求频率。
- [xdown.app](https://xdown.app/)：提供 Twitter/X 推文媒体解析接口，本插件通过该接口获取图片、MP4、GIF 下载地址。
- [count.getloli.com](https://count.getloli.com/)：提供 README 访问计数图片。
- [AstrBot](https://github.com/Soulter/AstrBot)、OneBot/aiocqhttp 生态：提供插件运行、消息组件与合并转发能力。

本插件与 X/Twitter、Nitter、xdown.app 均无官方关联。推文文本、图片、视频等内容版权归原作者或权利方所有，请遵守相关平台规则和当地法律法规。

## 更新日志

详见 [CHANGELOG.md](./CHANGELOG.md)。

## License

本项目代码采用 MIT License，详见 [LICENSE](./LICENSE)。

许可证仅覆盖本插件源码，不覆盖通过 Nitter、xdown.app 或 X/Twitter 获取的第三方内容，也不改变外部服务各自的使用条款。
