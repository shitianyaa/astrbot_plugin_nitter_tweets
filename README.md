# Nitter 推文记录

<p align="center">
  <a href="https://github.com/shitianyaa/astrbot_plugin_nitter_tweets/releases"><img alt="Version" src="https://img.shields.io/badge/version-0.18.2-blue?style=for-the-badge" /></a>
  <a href="https://github.com/shitianyaa/astrbot_plugin_nitter_tweets/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/shitianyaa/astrbot_plugin_nitter_tweets?style=for-the-badge&color=blue" /></a>
  <a href="https://github.com/Soulter/AstrBot"><img alt="AstrBot" src="https://img.shields.io/badge/AstrBot-plugin-00A86B?style=for-the-badge" /></a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <br />
  <a href="https://github.com/shitianyaa/astrbot_plugin_nitter_tweets/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/shitianyaa/astrbot_plugin_nitter_tweets?style=for-the-badge&color=gold" /></a>
  <a href="https://github.com/shitianyaa/astrbot_plugin_nitter_tweets"><img alt="Last Commit" src="https://img.shields.io/github/last-commit/shitianyaa/astrbot_plugin_nitter_tweets?style=for-the-badge" /></a>
  <a href="https://qm.qq.com/q/cPQnFNtdN6"><img alt="QQ Group" src="https://img.shields.io/badge/QQ%E7%BE%A4-Bot%E6%B5%8B%E8%AF%95%E7%BE%A4-12B7F5?style=for-the-badge&logo=tencentqq&logoColor=white" /></a>
  <br />
  <img src="./logo.png" alt="Nitter 推文记录图标" width="160" />
</p>

通过 Nitter 获取公开 X/Twitter 推文：手动查询与搜索、可选链接解析、按分组定时推送、图片/视频与翻译。兼容 AstrBot `>=4.16.0`。

> 首页只保留**上手与定位**。边界行为、平台差异、完整配置见 [进阶说明](./docs/advanced.md)。

## 目录

- [预览](#预览)
- [能做什么](#能做什么)
- [5 分钟上手](#5-分钟上手)
- [常用命令](#常用命令)
- [常用配置](#常用配置)
- [文档导航](#文档导航)
- [致谢](#致谢)
- [许可证](#许可证)
- [免责声明](#免责声明)

## 预览

<p align="center">
  <img src="./docs/assets/readme/dashboard-overview.png" alt="Nitter 推文控制台总览" />
</p>

<p align="center">
  <img src="./docs/assets/readme/qq-delivery.png" alt="QQ 推送效果" width="360" />
</p>

更多界面说明见 [进阶说明 · WebUI](./docs/advanced.md#webui-运维面板)。

## 能做什么

| 场景 | 能力 |
| --- | --- |
| 手动 | `/推文`、`/推文搜索`、`/镜像测试` |
| 链接 | 可选被动解析聊天中的 status 链接（默认关） |
| 定时 | `tweet_groups`：`blogger` / `tag` / `list` 分组推送 |
| 发送 | QQ 合并转发；Telegram / Lark / 微信 OC 等普通发送；Telegram 推文链接保留但不展开网页预览 |
| 媒体与 AI | 图片；可选视频/GIF、翻译 |
| 运维 | WebUI 面板、缓存与推送记录清理 |

## 5 分钟上手

### 1. 先试命令

```text
/推文 nasa
/推文搜索 #标签
/镜像测试 https://nitter.net
```

数量可省略（用 `default_limit`）。`/镜像测试` 仅管理员。说明与边界见 [进阶说明](./docs/advanced.md)。

### 2. 最小后台推送

```text
schedule_enabled = true
tweet_groups:
  - name: 默认分组
    group_id: default
    group_type: blogger
    watch_users: NASA, BBCWorld
    push_targets: aiocqhttp:GroupMessage:123456
```

必知（3 条）：

1. 在目标会话发 `/sid`，把**完整 UMO** 填进 `push_targets`
2. `group_type` 与字段对应：`blogger`→`watch_users`，`tag`→`watch_queries`，`list`→`watch_lists`（勿混用）
3. **首次只记 seen，不推历史**

标签 / List 示例、风险与调度细节：[进阶说明](./docs/advanced.md) · [List 指南](./docs/twitter-lists.md)。**新建不久的 List 要过段时间才会被 Nitter 收录**，空结果先等再查。

### 3. 可选

| 需求 | 做法 |
| --- | --- |
| 聊天里自动解析推文链接 | 打开 `auto_parse_tweet_links_enabled` |
| 批量把关注加入 Public List | 见 [List 指南](./docs/twitter-lists.md)（第三方扩展；X 约 24h ~100 次量级限额） |
| WebUI 管分组 / 历史 / 镜像 | AstrBot 插件页「Nitter 推文面板」 |

### 推送目标示例

```text
aiocqhttp:GroupMessage:123456
telegram:GroupMessage:-1001234567890
lark:GroupMessage:oc_xxxxxxxxxxxxx
```

以 `/sid` 返回为准，不要手猜平台 ID。

## 常用命令

| 命令 | 权限 | 说明 |
| --- | --- | --- |
| `/推文 用户名 [数量]` | 普通 | 查公开用户最近推文 |
| `/推文搜索 关键词 [数量]` | 普通 | HTML 搜索；标签请带 `#` |
| `/镜像测试 … 镜像站URL` | 管理员 | 临时测 Nitter 镜像 |
| `/推文状态` | 管理员 | 调度与分组状态 |
| `/推文检查 [分组名]` | 管理员 | 立即检查（当前会话须在该组 `push_targets`） |
| `/推文缓存清理` | 管理员 | 清媒体缓存 |
| `/推文记录清理 确认` | 管理员 | 清推送记录 |
| `/订阅导入` `/订阅删除` `/订阅列表` `/订阅导出` `/订阅去重` | 管理员 | 博主订阅 |
| `/标签导入` `/标签删除` | 管理员 | 标签订阅（须带分组名） |

List 通过配置文件或 WebUI 添加 ID，暂无导入命令。

## 常用配置

完整默认值与 WebUI 文案见 [`_conf_schema.json`](./_conf_schema.json)。只列最常改的：

| 配置 | 说明 |
| --- | --- |
| `instances` | 博主 RSS 镜像列表 |
| `search_instances` | 搜索 / List 用 HTML 镜像（**不要**默认塞 nitter.net） |
| `default_limit` | 手动命令默认条数 |
| `schedule_enabled` | 后台检查总开关 |
| `tweet_groups` | 订阅与推送分组 |
| `filter_reposts_enabled` | 后台转发过滤（全局；分组还有子开关） |
| `auto_parse_tweet_links_enabled` | 被动解析推文链接，默认关 |
| `send_image_attachments` / `send_video_attachments` | 图 / 视频是否发送 |
| `translate_enabled` | 是否翻译 |
| `merge_tweet_threshold` | QQ 合并转发条数阈值；`0` 关 |

实例架构与容错：[实例配置指南](./docs/instances-guide.md)。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [进阶说明](./docs/advanced.md) | 平台、流程、全配置、行为边界、诊断 |
| [List 订阅](./docs/twitter-lists.md) | Public List、导入关注、故障排查 |
| [实例指南](./docs/instances-guide.md) | RSS vs HTML、重试与回退 |
| [文档索引](./docs/README.md) | 全部 docs 入口 |
| [CHANGELOG](./CHANGELOG.md) | 版本记录 |
| [`_conf_schema.json`](./_conf_schema.json) | 配置真源 |

## 致谢

- [astrbot_plugin_parser](https://github.com/Zhalslar/astrbot_plugin_parser)、[Nitter](https://github.com/zedeus/nitter)、[xdown.app](https://xdown.app/)、[AstrBot](https://github.com/Soulter/AstrBot)
- 感谢 [tutianyu101](https://github.com/tutianyu101) 参与新版本测试
- 图标风格参考 [PeeGayhub 表情包](https://t.me/addstickers/PeeGayhub)；素材由 GPT 生成

## 许可证

MIT，见 [LICENSE](./LICENSE)。

## 免责声明

仅用于公开可见推文的获取与转发。请遵守 X/Twitter、Nitter 实例、xdown 与各消息平台的服务条款与速率限制。不提供绕过访问控制或抓取非公开内容的能力。
