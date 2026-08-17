# CLAUDE.md

本仓库的 agent 规范真源是 [AGENTS.md](./AGENTS.md)，本文件只保留入口和高频约束。

- 用户文档：[`README.md`](./README.md)、[`docs/`](./docs/)，实例专题见 [`docs/instances-guide.md`](./docs/instances-guide.md)。
- 多步任务：使用 `Progress/YYYY-MM-DD*.md` 记录要求、变更和验证；`Progress/` 不提交。
- 临时网络探测和一次性测试：只能放在 `testignore/`，不得把代理、Cookie、token 写入脚本或日志。
- 代码改动前先读 `AGENTS.md`、相关模块和测试；复杂逻辑保持在 `main.py` 之外。
- 验证：`python -m pytest -q`、`ruff check .`、`ruff format --check .`、`git diff --check`。
- 结构化日志必须使用现有安全辅助函数，避免输出敏感 URL、响应正文和会话材料。
