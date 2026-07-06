# Nitter 推文记录

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.14.0-blue" />
  <img alt="License" src="https://img.shields.io/github/license/shitianyaa/astrbot_plugin_nitter_tweets" />
  <img alt="AstrBot" src="https://img.shields.io/badge/AstrBot-plugin-00A86B" />
  <img alt="Nitter" src="https://img.shields.io/badge/Nitter-RSS-black" />
  <img alt="Media" src="https://img.shields.io/badge/media-xdown.app-orange" />
  <br />
  <img src="https://count.getloli.com/@astrbot-plugin-nitter-tweets?name=astrbot-plugin-nitter-tweets&theme=booru-jaypee&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="count" />
</p>

通过 Nitter RSS 获取指定 X/Twitter 用户公开推文，支持手动查询、镜像测试、图片附件、翻译、AI 评论、AI 识图、定时推送、暂存发布和 SQLite 推送记录/暂存队列存储。

## 功能

- 手动查询指定用户最近公开推文，支持用户名或 X/Twitter 链接。
- 独立 `/镜像测试` 命令，用临时 Nitter 实例验证账号抓取结果。
- 默认过滤博主转发他人的推文，保留博主自己发布的引用或评论推文。
- 后台按 `tweet_groups` 分组检查关注账号，并推送到对应目标。
- QQ/OneBot 支持按阈值使用合并转发；飞书/Lark、Telegram、微信 OC 和其他平台走普通逐账号发送。
- 支持图片附件；视频/GIF 附件默认关闭，开启后会按大小、时长和平台能力尽量发送。
- 支持非中文推文翻译、AI 识图作为评论上下文、按概率追加 AI 评论。
- 支持暂存定时发布、队列查看、手动发布、缓存清理和推送记录清理。
- 提供 AstrBot Plugin Pages 运维面板，可查看概览、分组订阅、暂存队列、最近推送、镜像测试和缓存清理。
- Nitter RSS 抓取和媒体下载遇到临时错误会重试。
- 后台检查可选启用账号 RSS 并发拉取、媒体和模型并发准备；默认关闭，开启后仍按关注账号和推文顺序发送。

## 快速开始

### 手动查询

```text
/推文 nasa
/推文 nasa 5
/推文 https://twitter.com/nasa 5
```

省略数量时使用 `default_limit`；填写数量时按用户输入获取，不额外截断。开启转发过滤、Nitter RSS 返回不足或部分内容解析失败时，最终发送数量可能少于请求数量。

### 镜像测试

```text
/镜像测试 https://nitter.net
/镜像测试 3 https://nitter.net
/镜像测试 nasa https://nitter.net
/镜像测试 nasa 3 https://nitter.net
```

`/镜像测试` 默认测试 `nasa`，默认获取 `default_limit` 条。镜像站必须填写完整 `http://` 或 `https://` 地址，只影响本次测试，不会写入 `instances` 配置。

### 后台推送

最小配置：

```text
schedule_enabled = true
tweet_groups:
  - name: 默认分组
    group_id: default
    watch_users: NASA, BBCWorld
    push_targets: aiocqhttp:GroupMessage:123456
```

每个用户分组都有自己的 `watch_users` 和 `push_targets`。手动 `/推文检查` 会按当前会话 UMO 匹配已启用分组；当前会话必须写在该分组 `push_targets` 中才会执行。

### 本地诊断脚本

```text
python scripts\probe_nitter_fetch.py nasa 5
python scripts\probe_nitter_fetch.py nasa 5 --include-reposts
```

该脚本复用插件的 Nitter RSS 抓取和转发过滤逻辑。`--include-reposts` 会临时关闭转发过滤，便于对比 Nitter RSS 原始返回。

## 推送目标

在要接收推送的群聊或私聊里发送 `/sid`，复制返回的 UMO，填入 `push_targets`。

```text
aiocqhttp:GroupMessage:123456
aiocqhttp:FriendMessage:123456
lark:GroupMessage:oc_xxxxxxxxxxxxx
lark:FriendMessage:ou_xxxxxxxxxxxxx
telegram:GroupMessage:-1001234567890
telegram:FriendMessage:123456789
```

`push_targets` 每行填写一个 UMO。不同平台的前缀以 `/sid` 实际返回为准，不需要手动猜平台 ID；自定义 QQ 平台 ID 也应直接使用 `/sid` 返回的完整 UMO。

## WebUI 运维面板

AstrBot 插件页面中会显示 `Nitter 推文面板`，用于查看和执行常用运维操作：

- `概览`：查看调度器、后台检查、关注账号、推送目标、暂存队列、功能开关、关键配置摘要和常见配置诊断。
- `分组订阅`：改为左侧分组列表 + 右侧详情编辑；支持新建分组、编辑分组名称/启停/每日检查/暂存开关/纯文本过滤/推送目标，并继续支持导入和删除关注账号；推送目标可做轻量检测，不发送测试消息。
- `暂存队列`：查看待发布推文、账号分布、最早/最新入队时间、失败次数、已送达推送目标数量和媒体数量；支持按分组发布暂存队列。
- `最近推送`：查看成功送达历史，支持按分组、博主和每页数量筛选，多个推送目标会合并展示；重推时使用当前分组当前选中的推送目标。
- `镜像测试`：用完整 `http://` 或 `https://` 镜像 URL 临时测试 RSS 抓取，不修改配置。
- `缓存清理`：清理普通媒体缓存或推送记录；不会删除关注账号、推送目标、暂存队列或暂存媒体。

`group_id` 由插件自动分配并只读展示；已有配置里的 `group_id` 会保留，缺失时会自动补齐，默认分组不可删除。`检查间隔分钟数` 和 `暂存发布时间` 仍是全局配置，页面里只读显示为“继承全局”。推送目标可以在分组详情里新增或删除，保存后写回当前分组配置；“检测目标”只校验 UMO 格式、平台实例是否存在和是否支持合并转发，不会向目标发送消息。

WebUI 仍不替代 AstrBot 设置页；Nitter 实例、媒体限制、AI provider、提示词、并发与限流等复杂配置仍在 `_conf_schema.json` 对应的 AstrBot 配置界面维护。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `/推文 用户名 [数量]` | 查询指定公开 X/Twitter 用户最近推文。 |
| `/镜像测试 [用户名] [数量] 镜像站URL` | 用临时 Nitter 镜像站测试获取推文。 |
| `/推文状态` | 查看调度器状态、分组、目标、无效项和推送记录索引数。 |
| `/推文检查 [分组名]` | 立即执行一次当前会话有权限的分组检查。 |
| `/推文缓存清理` | 清理普通图片/视频缓存，不删除暂存队列媒体。 |
| `/推文记录清理 确认` | 清理全部分组推送记录；也支持指定分组。 |
| `/推文队列 [分组名]` | 查看暂存队列数量、失败重试数量和发布时间。 |
| `/推文发布 [分组名]` | 立即发布暂存队列中的推文。 |
| `/订阅列表` | 查看默认分组有效账号、重复项和无效项。 |
| `/订阅导入 账号1,账号2 [分组名]` | 批量追加订阅账号。 |
| `/订阅删除 账号1,账号2 [分组名]` | 批量删除订阅账号。 |
| `/订阅导出` | 按分组导出订阅账号。 |
| `/订阅去重` | 规范化并去重默认分组关注账号。 |

## 常用配置

完整默认值和 WebUI 文案见 [_conf_schema.json](./_conf_schema.json)。

| 配置 | 说明 |
| --- | --- |
| `instances` | Nitter 实例列表，按顺序尝试，建议把自建实例放在第一位。 |
| `request_timeout` | 单次 RSS 请求等待某个 Nitter 实例响应的最长秒数；同一实例初次请求失败后最多再重试 1 次，仍失败才尝试下一个实例。 |
| `default_limit` | 手动 `/推文` 和 `/镜像测试` 未填写数量时的默认获取条数。 |
| `filter_reposts_enabled` | 是否过滤博主转发他人的推文，默认开启。 |
| `schedule_enabled` | 后台检查总开关；关闭后不会触发分组间隔检查和每日检查。 |
| `tweet_groups` | 用户分组列表，配置关注账号、推送目标、间隔检查、每日检查和暂存开关。 |
| `scheduled_fetch_limit` | 后台检查时每个账号拉取最近多少条用于对比。 |
| `notify_no_updates` | 无新推文或首次记录账号时是否发送检查摘要。 |
| `merge_tweet_threshold` | QQ/OneBot 新推文总数达到多少条时启用合并转发；`0` 关闭。 |
| `send_target_interval` | 多个推送目标之间的发送间隔。 |
| `send_user_interval` | 多个账号之间的发送间隔。 |
| `deferred_publish_times` | 暂存队列发布时间列表，格式 `HH:MM`。 |
| `concurrent_fetch_enabled` | 是否启用后台账号 RSS 并发拉取，默认关闭。 |
| `fetch_concurrency` | 同时拉取账号数，范围 `1-8`，默认 `3`。 |
| `concurrent_fetch_instances` | 后台并发拉取专用 Nitter 镜像池；留空时不启用并发，也不会回退到 `instances`。建议只填写自建镜像。 |
| `concurrent_prepare_enabled` | 是否启用后台媒体、翻译、识图和评论并发准备，默认关闭。 |
| `prepare_concurrency` | 同时准备的推文或账号批次数，范围 `1-8`，默认 `2`。 |
| `send_image_attachments` | 是否发送图片附件，默认开启。 |
| `send_video_attachments` | 是否发送视频/GIF 附件，默认关闭。 |
| `translate_enabled` | 是否翻译非中文推文。 |
| `comment_enabled` | 是否按概率追加 AI 评论。 |
| `vision_enabled` | 是否启用 AI 识图；结果主要作为 AI 评论上下文。 |
| `brief_log_enabled` | 后台日志简略模式；默认开启，只保留结果摘要、失败详情和关键 warning/error。 |

## 行为要点

- 首次启用某个账号时，只记录当前 RSS 中已有推文 ID，不推送历史内容。
- 后台检查以推送记录中最大的数字推文 ID 作为时间基准；之后翻页或过滤才发现的更旧未知推文只补入推送记录，不会回填推送。
- `filter_reposts_enabled` 开启时，会比较 RSS item 主链接作者和订阅账号；作者不同则视为转发并过滤，无法解析作者时保留。
- 推送记录按 `group_id + username` 独立存储；同一账号在不同分组里的记录互不影响。
- 手动 `/推文 用户名 数量` 不写入推送记录；后台检查和暂存发布会写入推送记录。
- QQ 合并转发只对 OneBot/`aiocqhttp` 类目标生效；Telegram、飞书/Lark、微信 OC 和其他平台始终普通发送。
- QQ/OneBot 图片附件会拆成独立图片消息或独立合并转发节点，降低图文同条发送超时概率；其他平台保持图文同消息行为。
- `brief_log_enabled` 只影响 AstrBot 后台日志，不影响聊天消息、命令返回或推送内容。
- 普通媒体发送后会删除；升级后会自动执行一次普通缓存清理，不删除暂存队列媒体。
- `scheduled_fetch_limit` 是每个账号本轮最多保留的有效推文数，默认 `5`、范围 `1-20`；Nitter RSS 会按 `Min-Id` 游标翻页，不是固定只拉一页。
- 后台并发拉取只在 `concurrent_fetch_enabled=true`、`concurrent_fetch_instances` 非空且 `fetch_concurrency > 1` 时启用；手动 `/推文` 和 `/镜像测试` 不使用并发配置。
- 即使拉取、媒体下载或模型处理并发完成，最终发送、暂存入队和推送记录更新仍按 `watch_users` 配置顺序以及推文从旧到新的顺序执行。

## 常见问题

### 为什么第一次启用账号不推送历史推文？

插件会先记录当前 RSS 已有推文 ID，之后只推送新出现的 ID，避免首次启用时刷屏。
如果后续因为纯文本过滤或翻页才看到更旧的媒体推文，后台检查只会把它补进推送记录防重复，不会把它当作新推文发送。

### 为什么 `/推文检查` 只看到检查结果，没有看到新推文？

`/推文检查` 会按当前会话 UMO 匹配已启用用户分组。当前会话不在任何已启用分组的 `push_targets` 中时，不会执行检查；开启暂存发布的分组也会绕过暂存队列，只把本次新推文临时发回当前会话。

### 为什么日志里有 HTTP 403、503 或 SSL EOF？

公共 Nitter 实例不稳定，可能拒绝访问、返回异常内容或临时断开。插件会按配置顺序尝试其他实例，并对临时错误重试；长期使用建议自建实例。

### 为什么媒体没有发出来？

图片和视频附件依赖 `xdown.app` 解析，下载后还会受平台大小、格式、CDN 上传和本地文件权限影响。附件失败不会阻止推文文本和原文链接发送。

### 为什么请求 30 条，实际发送少于 30 条？

`30` 表示最多拉取 30 条。开启转发过滤、Nitter RSS 返回不足、部分内容解析失败或视频/媒体被跳过时，最终发送数量可能更少。

## 更多说明

- [进阶说明](./docs/advanced.md)：平台差异、流程图、完整配置参考、缓存/推送记录/暂存发布细节。
- [_conf_schema.json](./_conf_schema.json)：插件配置默认值和 AstrBot WebUI 文案。
- [CHANGELOG.md](./CHANGELOG.md)：版本变更记录。

## 致谢

- [`astrbot_plugin_parser`](https://github.com/Zhalslar/astrbot_plugin_parser)：参考了 Twitter/X 媒体解析、媒体下载与消息发送分层思路。
- [Nitter](https://github.com/zedeus/nitter)：提供公开推文 RSS 访问方式。
- [xdown.app](https://xdown.app/)：提供 Twitter/X 媒体解析接口。
- [AstrBot](https://github.com/Soulter/AstrBot)、OneBot/aiocqhttp 生态：提供插件运行、消息组件与合并转发能力。

## 许可证

本项目代码采用 MIT License，详见 [LICENSE](./LICENSE)。

## 免责声明

本插件仅用于访问和转发公开可见的 X/Twitter 推文 RSS 内容，不提供绕过平台访问控制、批量抓取非公开内容或规避第三方服务限制的能力。使用本插件时，请自行确认并遵守 X/Twitter、Nitter 实例、xdown.app 以及消息平台的服务条款、速率限制和内容使用规则。
