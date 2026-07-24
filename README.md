# Nitter 推文记录

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.17.0-blue" />
  <img alt="License" src="https://img.shields.io/github/license/shitianyaa/astrbot_plugin_nitter_tweets" />
  <img alt="AstrBot" src="https://img.shields.io/badge/AstrBot-plugin-00A86B" />
  <img alt="Nitter" src="https://img.shields.io/badge/Nitter-RSS-black" />
  <img alt="Media" src="https://img.shields.io/badge/media-xdown.app-orange" />
  <br />
  <img src="./logo.png" alt="Nitter 推文记录图标" width="160" />
  <br />
  <img src="https://count.getloli.com/@astrbot-plugin-nitter-tweets?name=astrbot-plugin-nitter-tweets&theme=booru-jaypee&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="count" />
</p>

通过 Nitter RSS / HTML 搜索获取指定 X/Twitter 公开推文，支持手动查询与搜索、镜像测试、图片附件、翻译、按博主/标签分组定时推送和 SQLite 推送记录存储。

兼容 AstrBot `>=4.16.0`。

## 界面预览

### WebUI 运维面板

<p align="center">
  <img src="./docs/assets/readme/dashboard-overview.png" alt="Nitter 推文控制台总览" />
</p>

<p align="center">
  <img src="./docs/assets/readme/group-management.png" alt="订阅分组与博主管理" />
</p>

### QQ 推送效果

<p align="center">
  <img src="./docs/assets/readme/qq-delivery.png" alt="QQ 推送效果" width="360" />
</p>

## 功能概览

| 场景 | 能力 |
| --- | --- |
| 手动查询 | `/推文` 查询公开博主推文，`/推文搜索`（固定过滤纯转推） 搜索标签/短语，`/镜像测试` 临时验证 Nitter 实例。 |
| 后台推送 | 按 `tweet_groups` 分组：`blogger` 跟用户，`tag` 跟搜索订阅；定时检查并即时推送。 |
| 平台发送 | QQ/OneBot 支持合并转发；Lark、Telegram、微信 OC 和其他平台走普通发送。 |
| 媒体与 AI | 支持图片附件；可选开启视频/GIF、翻译和分组“仅媒体；可按组开启「发送时去除推文链接」（默认开）”推送。 |
| 运维存储 | 提供 WebUI 面板、缓存清理和推送记录清理。 |

## 快速开始

### 手动查询

```text
/推文 nasa
/推文 nasa 5
/推文 https://twitter.com/nasa 5
```

省略数量时使用 `default_limit`；填写数量时按用户输入获取，不额外截断。开启转发过滤、Nitter RSS 返回不足或部分内容解析失败时，最终发送数量可能少于请求数量。RSS 全失败且 `user_html_fallback=true` 时会尝试 HTML 用户页回退。

### 搜索

同会话同查询会缓存搜索结果，按你要的条数依次发放，不够再向镜像翻页（约 10 分钟内有效）。

```text
/推文搜索 #圣娅
/推文搜索 python programming 5
```

标签请带 `#`；普通词/短语直接写，不会自动加 `#`。走 `search_instances` HTML 搜索，与 `/推文` 冷却分离（`search_cooldown_seconds`）。非合并转发时可用 `manual_send_interval` 控制逐条发送间隔（默认 0）。有译文时是否显示原文由全局 `show_original_when_translated` 控制（默认显示）。

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
    group_type: blogger
    watch_users: NASA, BBCWorld
    push_targets: aiocqhttp:GroupMessage:123456
  - name: 标签示例
    group_id: tags1
    group_type: tag
    watch_queries:
      - "#圣娅"
      - "python programming"
    push_targets: aiocqhttp:GroupMessage:123456
```

每个分组有 `group_type`：`blogger` 使用 `watch_users`，`tag` 使用 `watch_queries`（勿混用）。共用 `push_targets` 与检查调度。

`watch_queries` 请填**纯字符串**（`#标签` 或短语）。不要在 AstrBot 配置列表里塞对象，否则会显示成 `[object Object]`。标签定时：每查询约拉一页最多 20 条 → 滤纯转推/可选纯文本 → 与 seen 差集 → 新帖全发。

**风险提示：** Bot 使用**私人 QQ 号**时，不建议启用标签分组定时功能。

- 博主组：`/订阅导入` `/订阅删除`
- 标签组：`/标签导入` `/标签删除`（须指定标签分组名；`#标签,短语 分组名`）

手动 `/推文检查` 会按当前会话 UMO 匹配已启用分组；当前会话必须写在该分组 `push_targets` 中才会执行。

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

AstrBot 插件页面中会显示 `Nitter 推文面板`，用于日常查看和维护：

- `概览`：查看调度器、后台检查、关注账号、推送目标、功能开关和关键配置摘要。
- `分组订阅`：维护分组名称、启停、每日检查、纯文本过滤、“仅媒体”、关注账号和推送目标；“仅媒体”受全局媒体开关和单条媒体数量上限控制。
- `最近推送`：查看成功送达历史，按分组和博主筛选，并使用当前推送目标重新推送。
- `镜像测试` / `缓存清理`：临时测试 Nitter 镜像连通性，或清理普通媒体缓存和推送记录。

WebUI 不替代 AstrBot 设置页；Nitter 实例、媒体限制、AI provider、提示词、并发与限流等复杂配置仍在 `_conf_schema.json` 对应的 AstrBot 配置界面维护。完整页面行为见 [进阶说明](./docs/advanced.md#webui-运维面板)。

## 常用命令

| 命令 | 权限 | 说明 |
| --- | --- | --- |
| `/推文 用户名 [数量]` | 普通用户 | 查询指定公开 X/Twitter 用户最近推文。 |
| `/推文搜索 关键词 [数量]` | 普通用户 | 用 HTML 搜索标签/短语；标签请带 `#`，短语不自动加 `#`。 |
| `/镜像测试 [用户名] [数量] 镜像站URL` | 普通用户 | 用临时 Nitter 镜像站测试获取推文。 |
| `/推文状态` | 管理员 | 查看调度器状态、分组、目标、无效项和推送记录索引数。 |
| `/推文检查 [分组名]` | 管理员 | 立即执行一次当前会话有权限的分组检查。 |
| `/推文缓存清理` | 管理员 | 清理普通图片/视频缓存。 |
| `/推文记录清理 确认` | 管理员 | 清理全部分组推送记录；也支持指定分组。 |
| `/订阅列表` | 管理员 | 查看默认分组有效账号、重复项和无效项。 |
| `/订阅导入 账号1,账号2 [分组名]` | 管理员 | 批量追加订阅账号。 |
| `/订阅删除 账号1,账号2 [分组名]` | 管理员 | 批量删除订阅账号。 |
| `/订阅导出 [分组]` | 管理员 | 导出博主/标签订阅；可指定分组名。 |
| `/订阅去重` | 管理员 | 规范化并去重默认分组关注账号。 |

## 常用配置

这里只列日常最常调整的项；完整默认值和 WebUI 文案见 [_conf_schema.json](./_conf_schema.json)。

| 配置 | 说明 |
| --- | --- |
| `instances` | Nitter 实例列表，按顺序尝试，建议把自建实例放在第一位。 |
| `request_timeout` | 单次 RSS 请求等待某个 Nitter 实例响应的最长秒数。 |
| `default_limit` | 手动 `/推文` 和 `/镜像测试` 未填写数量时的默认获取条数。 |
| `filter_reposts_enabled` | 是否过滤博主转发他人的推文，默认开启。 |
| `schedule_enabled` | 后台检查总开关；关闭后不会触发分组间隔检查和每日检查。 |
| `tweet_groups` | 用户分组列表，配置关注账号、推送目标、间隔检查和每日检查。 |
| `notify_no_updates` | 无新推文或首次记录账号时是否发送检查摘要。 |
| `merge_tweet_threshold` | QQ/OneBot 新推文总数达到多少条时启用合并转发；`0` 关闭。 |
| `send_image_attachments` | 是否发送图片附件，默认开启。 |
| `send_video_attachments` | 是否发送视频/GIF 附件，默认关闭。 |
| `max_media_per_tweet` | 单条推文最多准备和发送的媒体数量；设为 `0` 时分组“仅媒体”自动回退完整内容。 |
| `translate_enabled` | 是否翻译非中文推文。 |

## 行为要点

- 首次启用某个账号时，只记录当前 RSS 中已有推文 ID，不推送历史内容。
- `filter_reposts_enabled` 开启时，会比较 RSS item 主链接作者和订阅账号；作者不同则视为转发并过滤，无法解析作者时保留。
- seen 去重 ID 按 `group_id + username` 独立存储；同一账号在不同分组里的记录互不影响。push history 是独立的成功/部分失败发送快照，供 WebUI 历史查看和重推。
- 手动 `/推文 用户名 数量` 不写入 seen、扫描基准或 push history；后台检查会比较当前 RSS 首屏约 20 条与该账号的 seen 记录，首屏未命中上次最多 20 个基准 ID 时按 `Min-Id` 翻页直到命中任意基准，并发送所有差集。
- QQ 合并转发只对 OneBot/`aiocqhttp` 类目标生效；Telegram、飞书/Lark、微信 OC 和其他平台始终普通发送。
- 附件失败不会阻止推文文本和原文链接发送；普通媒体发送后会自动清理。
- 后台新推文按 RSS 返回顺序发送；每条消息只标注 `@作者`，不显示推文序号或账号进度。每个目标本轮第一条消息会显示博主数、推文数和分组概括。
- 分组开启“仅媒体”后，只有 RSS 确认有当前作者媒体且至少一个附件准备成功的推文会发送；媒体临时失败会在下轮重试，明确被全局类型、数量、时长、大小或分辨率策略排除的推文会跳过。全局媒体不可用时只在 WebUI 和日志提示并回退完整内容。

## 更多说明

- [进阶说明](./docs/advanced.md)：平台差异、流程图、完整配置参考、缓存和推送记录细节。
- [_conf_schema.json](./_conf_schema.json)：插件配置默认值和 AstrBot WebUI 文案。
- [CHANGELOG.md](./CHANGELOG.md)：版本变更记录。

## 致谢

- [`astrbot_plugin_parser`](https://github.com/Zhalslar/astrbot_plugin_parser)：参考了 Twitter/X 媒体解析、媒体下载与消息发送分层思路。
- [Nitter](https://github.com/zedeus/nitter)：提供公开推文 RSS 访问方式。
- [xdown.app](https://xdown.app/)：提供 Twitter/X 媒体解析接口。
- [AstrBot](https://github.com/Soulter/AstrBot)、OneBot/aiocqhttp 生态：提供插件运行、消息组件与合并转发能力。
- [PeeGayhub Telegram 表情包系列](https://t.me/addstickers/PeeGayhub)：插件图标借鉴了该系列表情包风格；图标素材由 GPT 生成。

## 许可证

本项目代码采用 MIT License，详见 [LICENSE](./LICENSE)。

## 免责声明

本插件仅用于访问和转发公开可见的 X/Twitter 推文 RSS 内容，不提供绕过平台访问控制、批量抓取非公开内容或规避第三方服务限制的能力。使用本插件时，请自行确认并遵守 X/Twitter、Nitter 实例、xdown.app 以及消息平台的服务条款、速率限制和内容使用规则。
