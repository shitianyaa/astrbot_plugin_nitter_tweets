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

然后请求 `xdown.app/api/ajaxSearch` 获取图片、MP4、GIF 下载地址。媒体会下载到插件目录下的 `cache/`，再作为本地 `Image` / `Video` 消息段放入合并转发节点。

如果媒体解析或下载失败，推文文本和原始链接仍会正常发送。

## 非中文推文翻译

开启 `translate_enabled` 后，插件会先用轻量规则判断推文是否不像中文；需要翻译时，会调用 AstrBot 已配置的大模型，把译文追加到推文节点中。

手动 `/推文` 查询会优先使用当前会话绑定的模型。定时推送没有真实触发会话，建议在 `translation_provider_id` 中选择一个固定模型；留空时会尝试使用第一个推送目标的默认模型。

可通过 `translate_prompt` 自定义翻译风格，例如要求保留术语、改成口语化中文等。提示词中需要包含 `{text}`，插件会把推文正文替换进去。

翻译链路会输出 `[NitterTweets] translation ...` 日志，可用于确认是否开启、是否匹配为非中文、使用了哪个 provider，以及模型是否返回译文。

## 配置

- `instances`：Nitter 实例列表，建议把自建实例放在第一位。
- `default_limit`：默认获取条数。
- `max_limit`：单次最大条数。
- `download_media`：是否解析并下载推文媒体。
- `download_images`：是否下载图片。
- `download_videos`：是否下载视频和 GIF。
- `max_media_per_tweet`：单条推文最多发送多少个媒体。
- `media_max_size_mb`：单个媒体大小上限。
- `xdown_api_url`：Twitter/X 媒体解析 API。
- `translate_enabled`：是否翻译非中文推文。
- `translation_provider_id`：翻译使用的大模型，支持在 WebUI 选择现有 provider。
- `translate_chinese_ratio_threshold`：中文占比低于该值时判定为非中文。
- `translate_prompt`：翻译提示词，需包含 `{text}`。

## 定时检查

开启 `schedule_enabled` 后，插件会定时检查 `watch_users` 是否有新推文，并推送到 `push_targets`。

首次启用某个账号时，只会记录当前 RSS 中已有的推文 ID，不会推送历史内容，避免刷屏。之后发现新 ID 才会推送。

### 关键配置

- `watch_users`：关注账号列表，支持 `NASA`、`@NASA`、`https://x.com/NASA`。
- `push_targets`：推送目标列表，支持：
  - `group:123456`
  - `private:123456`
  - `aiocqhttp:group:123456`
  - `aiocqhttp:GroupMessage:123456`
- `platform_id`：`group:ID` / `private:ID` 未指定平台时使用，留空自动检测。
- `interval_check_enabled` + `check_interval_minutes`：每 N 分钟检查一次。
- `daily_check_enabled` + `daily_check_times`：每天固定时间检查，可与间隔检查同时开启。
- `scheduled_fetch_limit`：定时检查时每个账号拉取最近多少条用于对比。
- `send_target_interval`：多个目标之间的发送间隔。
- `send_user_interval`：多个账号之间的发送间隔。

## 说明

- 公共 Nitter 实例不适合高频抓取，长期稳定使用建议自建实例。
- 视频/GIF 比图片更容易触发平台大小、格式或风控限制；如果合并转发失败，插件会回退为普通文本。
- 本插件不依赖 `astrbot_plugin_parser-main` 运行，只参考了它的 Twitter 媒体解析思路。
- 翻译功能使用 AstrBot 的 `context.llm_generate(...)` 接口；大模型输出质量和费用取决于你选择的 provider。

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
