# 项目概览

`astrbot_plugin_nitter_tweets` 是 AstrBot 插件，通过 Nitter RSS 获取公开 X/Twitter 推文，并发送到 AstrBot 会话。

## 能力

- 手动查询：`/推文 用户名 [数量]`
- 搜索：`/推文搜索 查询 [数量]`（`#` 为标签，否则短语）
- 镜像测试：`/镜像测试 [用户名] [数量] 镜像站URL`
- 后台检查：按 `tweet_groups` 分组扫描 RSS，以独立扫描基准和 seen 识别并推送全部新推文。
- 订阅维护：导入、删除、导出、去重。
- 媒体处理：图片、视频/GIF、xdown 解析、缓存。
- AI 处理：翻译。
- 多平台发送：OneBot/QQ、Telegram、Lark/Feishu、weixin_oc、默认 MessageChain。

## 边界

- 处理公开 RSS，以及配置开启时的 HTML 用户页回退 / HTML 搜索结果。
- 不绕过 X/Twitter、Nitter、xdown 或消息平台限制。
- SQLite 会保存运行所需的分组、账号和目标索引、seen、独立扫描基准组，以及最近推送所需的 push history 快照；push history 用于 WebUI 历史查看和重推，不会主动抓取或归档账号的全部历史推文。
- 手动查询不写入 seen、扫描基准或 push history。
- 后台检查首次启用账号只初始化 seen 和最近最多 20 个扫描基准 ID，不推送历史；空 feed 或全过滤结果也会保留初始化状态。
- 纯文本过滤只影响开启该分组开关的后台检查，手动命令不受影响。
- 分组 `media_only_enabled` 只影响定时推送；有效时只发送作者和成功准备的媒体，全局媒体不可用时回退完整内容。

## 入口

- 插件入口：`main.py`
- 用户命令：`command_handlers/`
- 后台调度：`scheduler/`
- Nitter RSS：`media_support/client.py`；HTML 搜索/回退：`media_support/html_backend/`
- 媒体：`media_support/service.py`
- 发送：`delivery/`
- 配置：`_conf_schema.json`、`config/`、`scheduler/config.py`
- 存储：`storage/`

## 真源

- 配置字段真源：`_conf_schema.json`
- 配置读取和迁移真源：`config/compat.py`
- 分组行为真源：`scheduler/config.py`
- 用户说明真源：`README.md` 和 `docs/advanced.md`
- Agent 维护入口：`AGENTS.md`
