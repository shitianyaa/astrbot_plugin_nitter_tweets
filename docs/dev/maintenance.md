# 维护规则

本文面向维护者和协作 agent。业务细节优先放到 `docs/project/` 或 `docs/advanced.md`，不要继续堆进 `AGENTS.md`。

## 文档同步

下列变化必须同步文档：

- 命令行为、参数或权限变化。
- 配置字段、默认值、范围、hint 或迁移规则变化。
- RSS 抓取、过滤、分页、重试变化。
- 调度、seen、暂存发布、缓存清理变化。
- 平台发送、合并转发、降级策略变化。
- 媒体解析、视频/GIF、xdown 行为变化。
- AI provider、prompt、触发条件变化。
- 测试、lint、本地诊断流程变化。

修改 repo-wide 维护规则或 agent 入口约定时，同步 `AGENTS.md`。

## 配置维护

- 配置字段语义见 `docs/project/configuration.md`。
- `_conf_schema.json` 是 WebUI 真源。
- `config_compat.py` 是兼容和迁移真源。
- `scheduler_config.py` 是分组行为真源。

## 测试维护

常用命令见 `docs/dev/testing.md`。

涉及下列行为时，优先补回归测试：
- RSS HTML 解析。
- seen 写入。
- pending queue 发布和失败。
- OneBot 合并转发。
- Lark/Telegram 特殊发送。
- 媒体缓存清理。
- 配置迁移。

## 已知非职责

本插件不维护独立 Web 服务、不抓取非公开推文、不规避第三方速率限制、不持久化完整历史推文。
