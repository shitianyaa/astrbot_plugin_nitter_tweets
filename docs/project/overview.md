# 项目概览

`astrbot_plugin_nitter_tweets` 是 AstrBot 插件，通过 Nitter RSS 获取公开 X/Twitter 推文，并发送到 AstrBot 会话。

## 能力

- 手动查询：`/推文 用户名 [数量]`
- 搜索：`/推文搜索 查询 [数量]`（`#` 为标签，否则短语）
- 镜像测试：`/镜像测试 [用户名] [数量] 镜像站URL`；Dashboard 按模式使用 `instances` 或 `search_instances`，留空 URL 时串行测试全部配置实例。
- 后台检查：按 `tweet_groups` 分组扫描 Blogger RSS 或 Tag/List HTML，以独立扫描基准和 seen 识别并推送全部新推文。
- 分组类型：Blogger（`watch_users`）、Tag（`watch_queries`）和 List（`watch_lists`）；摘要分别使用“n 位博主”“n 个搜索订阅”“n 个 List”。
- 目标作者黑名单：按完整 UMO 保存，同一目标跨分组共享，只过滤后台分组推送。
- 订阅维护：导入、删除、导出、去重。
- 媒体处理：图片、视频/GIF、xdown 解析、缓存。
- AI 处理：翻译。
- 多平台发送：OneBot/QQ、Telegram、Lark/Feishu、weixin_oc、默认 MessageChain。
- 运维恢复：Dashboard 显示成功、部分送达和发送失败历史，可向原分组当前目标手动重推。

## 边界

- 处理 Blogger 公开 RSS 和配置开启时的 Tag/List HTML 搜索结果；Blogger 不使用 HTML 用户页回退池。
- 不绕过 X/Twitter、Nitter、xdown 或消息平台限制。
- SQLite 会保存运行所需的分组、订阅源和目标配置、seen、独立扫描基准组，以及最近推送所需的 push history 快照；push history 用于 WebUI 历史查看和重推，不会主动抓取或归档订阅源的全部历史推文。
- 手动查询不写入 seen、扫描基准或 push history。
- 历史重推属于原分组，是不受目标作者黑名单和 `media_only_enabled` 限制的显式恢复操作。
- 后台检查首次启用订阅源只初始化 seen 和最近最多 20 个扫描基准 ID，不推送历史；Tag/List 真正空首轮保持未初始化，有原始结果但全被过滤时记录空扫描水位。
- `check_on_startup=true` 时，存储初始化完成后按分组顺序立即首检所有启用且配置完整的分组（包括仅每日、仅间隔和无定时槽位分组）；首检后锚定槽位，不重复触发。缺少订阅源或推送目标的分组只记录跳过日志。
- Dashboard 支持创建、编辑和校验 List 分组，概览分别统计三类订阅，历史统一显示“订阅源”；镜像测试留空 URL 时返回逐实例结果和汇总。
- 纯文本过滤只影响开启该分组开关的后台检查，手动命令不受影响。
- 分组 `media_only_enabled` 只影响定时推送；有效时只发送作者和成功准备的媒体，全局媒体不可用时回退完整内容。

## 入口

- 插件入口：`main.py`
- 用户命令：`command_handlers/`
- 后台调度：`scheduler/`
- Nitter RSS：`media_support/client.py`；HTML 搜索与旧兼容实现：`media_support/html_backend/`
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
