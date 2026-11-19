# AGENTS.md

面向后续 AI agent 的项目开发规范。改代码前先读本文件，再读相关模块和测试。

## 文档入口

- 用户：`README.md`、`docs/advanced.md`、`docs/faq.md`、`docs/twitter-lists.md`、`docs/README.md`
- 项目事实：`docs/project/`（架构、配置、平台发送）
- 开发：`docs/dev/`（setup、testing、maintenance）
- 配置真源：`_conf_schema.json`；迁移：`config/compat.py`

业务细节写在 `docs/project/`、`docs/advanced.md`、schema，**不要**继续把完整专题堆进本文件。

## 工作方式（用户约定）

- **先规划，用户同意后再改代码**（文档小补丁除外，若用户已明确「直接改」）。
- 多步实现用 `Progress/YYYY-MM-DD-*.md` 记清单与验证；不擅自 commit Progress。
- 不使用 obra/superpowers 技能套件；以本文件 + `docs/` + Progress 为准。
- 本机环境与生产访问另见未入库的 `AGENTS.local.md`（若存在）。

## 项目定位

AstrBot 插件 `astrbot_plugin_nitter_tweets`：Nitter RSS / HTML 搜索获取公开推文；手动查询与搜索；按 `tweet_groups` 定时推送（`blogger` / `tag` / `list`）；可选被动解析聊天中的 status 链接；图片/视频/翻译；多平台发送；SQLite seen + push history。

## 代码入口（细节见 architecture）

| 区域 | 职责 |
| --- | --- |
| `main.py` | 生命周期、命令/regex 注册、委派。保持轻量。 |
| `command_handlers/` | `manual` / `maintenance` / `subscriptions` / **`link_preview`**（被动链接） |
| `scheduler/` | 高风险：检查、seen、推送编排 |
| `media_support/` | RSS client、`html_backend`、媒体、**`status_link` / `status_resolve`** |
| `delivery/` | 多平台发送；`force_media` 仅链接预览等显式路径 |
| `rendering/`、`ai/`、`storage/`、`plugin_api/`、`shared/` | 渲染、翻译、SQLite、WebUI API、模型；`shared/observability.py` 负责脱敏日志和结构化任务摘要；`shared/arbiter.py` 负责被动链接跨 Bot 表情仲裁 |

完整模块关系：`docs/project/architecture.md`。

## 必守规则

- 复杂逻辑不进 `main.py`；命令 `event.stop_event()` + `event.send(...)` / sender。
- 管理命令：`@filter.permission_type(ADMIN)`，并继续做场景校验。
- 双导入：`try: from .x import ... except ImportError: from x import ...`。
- 不硬编码 provider、token、群号、实例、本机路径；不提交 `data/`、缓存、DB、下载物。
- 含异常详情、用户配置值或需要出现在 WebUI 的日志用 `safe_task_log` / `safe_log` / `safe_block_log`，传字符串级别名。固定文本和无敏感内容的本地调试可直接调用 logger。任何路径都不得记录 token、Cookie、响应正文、完整私有 URL 或会话材料。任务摘要保留分组、类型、来源、生效实例、轮换轨迹、统计、耗时和 warning/error。
- 插件运行时代码的 logger 从 `astrbot.api` 导入，禁止导入标准库 `logging` 或引用其常量和函数。运行时约束由 `scripts/check.py` 验证。
- 不改用户未要求的行为/文案；优先兼容现有测试。
- 提交只用真实变更描述；无 AI 署名、`Co-Authored-By`、`Generated with ...`。
- 禁止丢改动的 git 命令（`reset --hard` 等），除非用户明确要求。

## 配置与迁移

新增配置同步 `_conf_schema.json`、实际读取该配置的模块、用户文档和相关测试。由兼容层分组或迁移的字段同步 `CONFIG_GROUP_BY_KEY` / `MIGRATABLE_*`，仅分组字段同步 `ScheduleGroup`。

分层：`basic` / `media` / `ai_translation` / `schedule` / `push`。日志分级和诊断环见 `docs/advanced.md` 的日志诊断。

### `tweet_groups`

- `group_id` 稳定；默认新建 `default`。
- `group_type`：`blogger` | `tag` | **`list`**。创建后勿改；字段分别用 `watch_users` / `watch_queries` / **`watch_lists`**，勿混用。
- seen：`group_id + account_key`；博主=用户名；标签=`q:<casefold>`；List=`list:<id>`（用 `normalize_seen_account_key`）。
- 转发过滤：`全局 filter_reposts_enabled && 分组 filter_reposts_enabled`；手动命令不读分组子开关。
- List 必须 Public；ID 为纯数字；走统一 `instances`（RSS 优先，失败回退 HTML）。

### 自建实例

- `instances`：唯一 Nitter 列表，同时用于博主 RSS、List RSS、搜索/HTML 后备和后台抓取。
- Blogger 固定 RSS 优先、HTML 自动后备；无 `user_html_fallback` 开关。
- `search_instances` / `blogger_html_instances` / `concurrent_fetch_instances` 已删除，只做启动诊断，不读取、不迁移、不写回。
- 无公共默认实例；已退役公共地址只在运行时过滤并记录 warning。
- 网络层允许合法 HTTP(S) 的 loopback、Docker 服务名、私网 IP 和重定向；文档必须提醒只使用可信自建实例并隔离内部管理面。

### 被动链接解析

- 配置：`auto_parse_tweet_links_enabled`（**默认 false**）。
- 入口：`@filter.regex` → `LinkPreviewMixin`；**无新命令**。
- 忽略 Bot 自身消息；合法 status 链才 `stop_event`。
- 解析：FxTwitter → VxTwitter → Syndication（`status_resolve`）；URL 白名单在 `status_link`。
- 仲裁：`link_preview_arbiter_enabled`（**默认 true**），仅 OneBot 群聊：表情 289 占坑、124 胜出确认，`msg_time` 60s 时间片确定性轮转；表情 API 不可用退化为无仲裁，不阻塞解析。
- 翻译跟全局 `translate_*`；原文显隐只跟全局 `show_original_when_translated`（无分组 hide）。
- 媒体：`force_all_media` / send `force_media`（无视全局图视频开关与 `max_media_per_tweet`，仍受大小/时长/超时）。
- 单消息最多 3 链；防抖同 UMO+status_id（实现上应在**成功后**再记；见 Progress/审查）。
- 注意：共享 `TweetSender` 上临时改 media flags 有并发串扰风险；优先局部 force。

## RSS / HTML / 过滤（摘要）

- 手动 `fetch_tweets` 默认不跳纯文本、保留转发；后台可用 `skip_plain_text` 与双层转发过滤。
- 博主分组后台检查按 URL 250 字符安全分批走合并 RSS（`/{u1,u2,...}/rss`），每批最多扫 3 页，分别确认账号水位。未确认水位的账号单独补查，合并请求失败则整批逐个补查。保留转推时直接逐个请求。
- `filter_plain_text_enabled` 云端优化：Tag 搜索追加 `filter:media`；博主仅在转发过滤也开启时切 `/{user}/media/rss` 相册专线，否则保持主页 RSS 由本地过滤以保留转推；List 保持本地过滤。
- 纯文本过滤只影响后台：作者上传媒体才算；`card_img`、Article 封面、**引用推媒体**不算。
- 整页被滤但仍有 cursor 须翻页；真·空 feed 才 empty。
- 诊断：`python scripts/probe_nitter_fetch.py nasa 5 --instance http://nitter:8080`（可加 `--skip-plain-text` / `--include-reposts`）。
- HTML 只分类正常时间线、空页、登录/维护/错误页和异常页面；不再实现或检测公共实例挑战。

## 调度与 seen

- 首次账号/查询只 init seen，不推历史；Tag/List 真空首轮可不 init。
- **seen 在发送成功或发送调用失败被显式处理后更新**；媒体准备失败/取消不写 seen，并须清本轮普通媒体缓存。
- 改 `ScheduleGroup` / `ScheduledCheckResult` 时同步 status/log/message 格式与测试。

## 媒体 / 平台 / AI

- 有视频/GIF 时跳过同条封面图；下载失败不挡文本。
- 普通媒体发送后清理；统计 removed/failed 等。
- UMO 用 `/sid` 完整值；平台类型用 `PlatformResolver`，勿只看 UMO 第一段。
- QQ 合并转发有降级与「可能已送达」处理；TG flood retry；Lark 优先原生 post。
- 媒体传输编码梯度只作用于 OneBot（`delivery/media_transport.py`）：**无损的换编码重试必须排在有损的去视频/纯文本降级之前**；`uncertain` 不推进梯度；Lark 必须拿到文件系统路径而非 base64。详见 `docs/project/platform-delivery.md`。
- 处理顺序：翻译 → 媒体；provider 不硬编码。

## 文档同步

用户可见变更同步 `CHANGELOG.md` 和受影响的使用说明。配置变化更新 schema，发布版本及插件能力变化同步相关版本和能力声明。

### CHANGELOG 与版本

- 开发期间把用户可见变更写入下一候选版本的数字标题（如 `## [1.7.4]`）。版本按语义化版本确定（修 bug → patch，新增功能 → minor，破坏性变更 → major），同步 `metadata.yaml`、`main.py` 和 README 徽章。候选版本在发版 PR 最终检查前补上实际发布日期。
- 发布契约以 `scripts/release.py` 为准。版本校验会拒绝 `Unreleased` 和 `未发布` 标题。涉及自动发布的合并在确认时说明发布影响，见 [CI 与发布门禁](docs/dev/maintenance.md#ci-与发布门禁)。
- 条目只写相对 `main` 的用户可见变化（修复 / 新增 / 变更），内部重构、分支内自我迭代不单独成条；用用户能看懂的行为描述，不堆 CSS 选择器、ARIA 属性名等实现细节。

## 临时产物

本地临时脚本、测试、探测和门禁输出统一放在 `Temp/<任务短名>/`，用 Git 的本地排除规则忽略 `/Temp/`。门禁默认写入 `Temp/quality-gate/`，可用 `--temp-root Temp/<任务短名>` 指定任务目录。探测记录目标和代理方式，省略凭据和私有地址。
正式 pytest 只收集 `tests/`（见 `pytest.ini`）。持续回归测试放在 `tests/`。

## 测试与工具

```powershell
python -m pytest -q
ruff check .
ruff format --check .
```

- Ruff：**0.15.22**；与 `requirements-dev.txt` 和 `scripts/check.py` 保持一致。
- 链接解析：`tests/test_status_link_preview.py`
- 合并 RSS 管道：`tests/test_merged_rss.py`
- List：`tests/test_list_rss.py`、`tests/test_list_support.py`、`tests/test_scheduler_list_delivery.py`
- 标签调度与搜索排序：`tests/test_scheduler_tag_delivery.py`、`tests/test_html_search_rotate.py`
- HTML/搜索：`tests/test_html_backend_query.py`；配置、类型解析与订阅导入：`tests/test_config_contracts.py`
- 日志与 HTML 页面分类：`tests/test_observability.py`、`tests/test_html_gate_detection.py`
- 版式与订阅显示：`tests/test_tweet_layout.py`、`tests/test_subscription_display.py`
- 媒体传输编码：`tests/test_media_transport.py`
- 媒体画质三档：`tests/test_media_quality.py`；链接处理器向解析器传递画质：`tests/test_status_link_preview.py`
- 发送拒收分类与图片失败提示：`tests/test_image_send_rejected_notice.py`
- 媒体缓存文件名后缀：`tests/test_media_utilities.py`
- 配置迁移标记 schema 声明：`tests/test_config_contracts.py`
- xdown token 直链与重试兜底：`tests/test_xdown_token_direct_url.py`
- 视频大小预检降级：`tests/test_media_quality.py`
- 改 `delivery/sender.py`、`scheduler/`、`config/compat.py` 或公共模型 → **全量 pytest**。

完整矩阵：`docs/dev/testing.md`。

## Review 清单

- 只改任务相关文件；手动 vs 后台行为差异保留。
- 无提前写 seen；发送调用失败有失败 history 可重推；媒体准备失败缓存已清理；非 OneBot 平台未误用合并转发。
- 引用媒体未当作者媒体；schema/compat/docs/测试已同步；对应测试已跑。
