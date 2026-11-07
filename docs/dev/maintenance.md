# 维护规则

本文面向维护者和协作 agent。业务细节优先放到 `docs/project/` 或 `docs/advanced.md`，不要继续堆进 `AGENTS.md`。

## 文档同步

下列变化必须同步文档：

- 命令行为、参数或权限变化。
- 配置字段、默认值、范围、hint 或迁移规则变化。
- RSS 抓取、过滤、分页、重试变化。
- 调度、seen、缓存清理变化。
- 平台发送、合并转发、降级策略变化。
- 媒体解析、视频/GIF、xdown 行为变化。
- AI provider、prompt、触发条件变化。
- 测试、lint、本地诊断流程变化。
- 结构化日志字段、日志脱敏规则、HTML 页面分类或链接清理行为变化。

修改 repo-wide 维护规则或 agent 入口约定时，同步 `AGENTS.md`。

## 配置维护

- 配置字段语义见 `docs/project/configuration.md`。
- `_conf_schema.json` 是 WebUI 真源。
- `config/compat.py` 是兼容和迁移真源。
- `scheduler/config.py` 是分组行为真源。

## 测试维护

常用命令见 `docs/dev/testing.md`。

涉及下列行为时，优先补回归测试：
- RSS HTML 解析。
- HTML 真实时间线、空页、登录维护页和异常页面的分类边界。
- 结构化任务摘要、实例轮换轨迹和敏感字段脱敏。
- 推文正文中来源 Nitter 镜像链接的清理与普通外部链接保留。
- seen 写入、发送调用失败跳过并推进 seen、媒体准备失败不写 seen。
- OneBot 合并转发。
- Lark/Telegram 特殊发送。
- 媒体缓存清理。
- 配置迁移。

一次性网络探测、代理验证和临时脚本只放 `testignore/`；维护文档或进度记录中可以写目标、实例、代理和结果摘要，但不要记录 Cookie、token、响应正文或完整会话 URL。

版本发布前检查 `metadata.yaml`、README 徽章、`main.py`、`CHANGELOG.md` 和发布工作流的版本契约。没有明确发布版本时，不要为了文档更新擅自改版本号或触发 release 自动化。

## CI 与发布门禁

- `Quality Gate` 在 PR 和 main push 上执行 `scripts/check.py`。仓库管理员需另将该状态设为 main 必需检查；存在 workflow 不代表不能绕过合并。不得使用 `pull_request_target` 执行贡献者代码或向检查 job 提供写 token。
- 发布 job 依赖检查成功，仅 main 的 CHANGELOG 变更或 main 手工勾选 `publish` 可发布。普通 main 文档/门禁更新与默认手工触发只检查，不发布。
- `scripts/release.py` 是版本解析、白名单打包和发布状态真源。开发允许首版本段无日期；实际发布必须是 `## [X.Y.Z] - YYYY-MM-DD`，有效日期不可在未来且必须有变更条目。禁止跳过 Unreleased/未发布或非法首标题。不会自动补日期、改版本。
- tag 解引用后必须等于本次 checkout/event SHA；API 403/429/网络错误不得当成不存在。首次发布创建并核对 tag，然后草稿、上传、摘要/附件 SHA256 核验、最后公开。创建草稿后最多查询 3 次，仅返回未找到时隔 2 秒重试；查询异常、歧义或非草稿立即停止，超过次数保留 tag/草稿供原提交续跑，不重复创建。
- 已公开同 SHA 且说明/附件一致的 Release 重跑跳过；不一致或缺损报错，绝不覆盖附件/说明。现有同 SHA 草稿可续跑，已有附件先核验，不能使用 `--clobber`。失败留下 tag/草稿，不自动删除；需要修复公开版本时走新版本或维护者单独批准的操作。
- 合入 main 的提交必须已补上发布日期，否则发布 job 会以“Publication requires a changelog date”失败，且不会自动补日期。修正已公开版本说明的错字也会触发失败（公开说明不改），需 bump 版本或另走维护者操作。
- ZIP 固定结构和文件时间，仅包内白名单跟踪文件，检查资源/语法/32MiB上限并做无网络隔离导入；不包含开发依赖和检查脚本。

本地验收包括模拟发布API与故障路径，不创建远端 Release；不能替代 GitHub token 权限、事件触发和必需状态设置的云端核验。提交、推送、合并、发布授权仍分开。

## 已知非职责

本插件不维护独立 Web 服务、不抓取非公开推文、不规避第三方速率限制，也不会主动归档账号的全部历史推文；运行期会持久化分组、账号和目标运行索引，以及 seen 和已推送内容的历史快照。
