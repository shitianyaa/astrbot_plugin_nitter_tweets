# Nitter 推文记录文档索引

`astrbot_plugin_nitter_tweets` 的用户使用说明以根目录 `README.md` 为准。本目录只收口项目事实、开发规范和维护检查。

## 文档职责

- `docs/README.md`: 总索引和阅读路径。
- `docs/advanced.md`: 用户侧进阶说明、平台差异、完整配置参考。
- `docs/project/overview.md`: 插件定位、能力边界、入口。
- `docs/project/architecture.md`: 模块关系、数据流、发送链路、存储边界。
- `docs/project/configuration.md`: 配置字段来源、迁移规则、同步要求。
- `docs/project/platform-delivery.md`: 多平台发送、UMO、适配器和回归测试入口。
- `docs/dev/setup.md`: 本地开发、诊断脚本、目录注意事项。
- `docs/dev/testing.md`: 测试矩阵和高风险回归。
- `docs/dev/contributing.md`: 改动流程、提交边界。
- `docs/dev/engineering-principles.md`: 工程约束。
- `docs/dev/maintenance.md`: 维护规则、文档同步、agent 入口。

同一概念不要在多个文档里维护完整细节。最具体的专题文档负责细节，其他位置只链接。

## 阅读路径

### 快速理解插件

1. `docs/project/overview.md`
2. `docs/project/architecture.md`
3. `docs/project/platform-delivery.md`
4. `README.md`
5. `docs/advanced.md`

### 参与开发

1. `AGENTS.md`
2. `docs/dev/setup.md`
3. `docs/dev/testing.md`
4. `docs/dev/contributing.md`
5. `docs/dev/maintenance.md`

### 修改配置

1. `docs/project/configuration.md`
2. `_conf_schema.json`
3. `config_compat.py`
4. `scheduler_config.py`
5. `tests/test_subscription_import.py`
