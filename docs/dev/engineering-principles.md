# 工程原则

## 模块边界

- `main.py` 只做插件入口和注册。
- 命令层只处理参数、权限、用户提示。
- RSS 行为放 `media_support/client.py`。
- 媒体行为放 `media_support/service.py` 和 `cache.py`。
- 调度行为放 `scheduler.py`。
- 平台差异放 `delivery/` 和 `PlatformResolver`。
- 输出格式放 `tweet_rendering.py`。

## 兼容优先

- 老配置必须能读取或迁移。
- 手动命令和后台调度的行为差异不能混淆。
- 默认值变化需要明确用户影响。
- 新功能默认关闭时，不应改变老用户行为。

## 错误处理

- RSS 临时错误可重试。
- 媒体下载失败不能阻止文本发送。
- OneBot 不确定送达错误不能盲目重发。
- AI provider 缺失或失败要可观测。
- 异常路径仍要清理普通缓存。

## 测试优先

- 先用现有测试定位行为边界。
- 修 bug 必须补能复现该 bug 的回归测试。
- 不要只跑被改函数附近的测试；按 `docs/dev/testing.md` 选矩阵。

## 文档优先级

- 用户用法：`README.md`
- 进阶行为：`docs/advanced.md`
- 项目事实：`docs/project/`
- 开发纪律：`docs/dev/`
- Agent 入口：`AGENTS.md`
