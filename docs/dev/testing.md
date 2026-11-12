# 测试与回归检查

## 共享完整门禁

`python scripts/check.py` 与 CI 使用相同检查入口，默认在系统临时目录生成隔离产物；需要固定位置时用 `--temp-root <目录>` 指定。

门禁确认真实 AstrBot SDK、Node 和固定 Ruff 可用，检查版本/schema/运行时语法及标准库 logging 禁用，再运行全量 pytest、Ruff/format、全部 Dashboard JS、Git diff 检查和真实 ZIP 包内隔离导入。缺环境立即失败；不靠 SDK 桩或 Node 缺失 skip 视为完整通过。只导入插件，不实例化、不联网、不发送消息。

包只含白名单内的 Git 跟踪文件，排除工具、测试、文档、缓存与数据库；输出在独立临时子目录，不修改源码。分步提交另从 index 导出隔离副本后运行，不能用后续工作树改动替早期提交验收。

## 基础命令

`pytest.ini` 将默认收集范围限制为 `tests/`，因此 `testignore/` 中的临时探测脚本不会被全量测试误执行。

```powershell
python -m pytest -q
ruff check .
ruff format --check .
git diff --check
python -m py_compile main.py scheduler/__init__.py scheduler/runner.py scheduler/config.py scheduler/models.py media_support/client.py media_support/service.py delivery/sender.py
```

## 测试维护

- 测试直接使用 `requirements-dev.txt` 中的真实 AstrBot SDK，不注入备用 SDK 桩。抓取、发送、存储等外部边界仍按用例模拟。
- 同一行为优先保留在对应专题文件；按功能归并小文件，不按 PR 编号或单次修复另开文件。跨层测试只验证接线和组合行为，不重复完整输入矩阵。相同准备代码用参数化或 `subTest` 合并，保留必要边界。
- 翻译显隐由 `test_tweet_layout.py` 覆盖，搜索去重由 `test_search_session_buffer.py` 覆盖，作者解析由 `test_search_display_username.py` 覆盖。
- 历史分页在 Quart 请求上下文中直接调用 `handle_history()`，再经 StorageAdapter 和 SQLite 验证四档条数及 150 条下的状态筛选分支；不覆盖路由注册或请求分发。各状态与重推最新结果语义由同文件的存储/序列化测试覆盖。
- Dashboard 日志增量去重、切档和重启由 Node 行为测试覆盖；静态断言保留行为测试尚未覆盖的安全、接线和布局约束，不锁定纯展示文案或无行为意义的函数名。
- 重试测试模拟等待并断言次数与延迟参数；并发、取消和仲裁测试需要真实任务交错时不全局替换 sleep。

## 分层验证矩阵

| 改动类型 | 最小检查 | 关注点 |
| --- | --- | --- |
| 调度、seen、私人号 OneBot 合并、QQ Official、Telegram flood | `python -m pytest -q tests/test_delivery_platforms.py tests/test_scheduler_delivery.py tests/test_qq_official_delivery.py` | 独立扫描基准、发送调用失败跳过、准备失败不推进基准、合并顺序、官方 Markdown/纯文本切换、媒体部分成功、限流重试 |
| 发布版本与工具 | `python -m pytest -q tests/test_release_version.py tests/test_release_tools.py tests/test_workflow_contract.py` | 四处版本一致、首标题/日期/有效说明、tag/SHA、公开版本不可覆盖、草稿续跑与API失败、ZIP内容与包内导入、CI依赖和权限 |
| 结构化日志、双环与 HTML 页面分类 | `python -m pytest -q tests/test_observability.py tests/test_log_buffer.py tests/test_web_logs_api.py tests/test_html_quiet_log.py tests/test_html_gate_detection.py` | 脱敏字段、摘要统计、主环/DEBUG 独立容量与读取、HTML 过程分流、时间线/空页/登录维护/异常页分类 |
| WebUI 历史分页与状态筛选 | `python -m pytest -q tests/test_web_history_api.py` | 在 Quart 请求上下文中直接调用 `handle_history()` → StorageAdapter → SQLite，验证五组分页场景；不覆盖路由注册或请求分发。保留四档条数、带状态筛选的分页、双目标合并、总页数、下一页探测与末页完整性，以及独立的各状态筛选和最新投递语义测试 |
| Dashboard 历史表格与主题 | `python -m pytest -q tests/test_dashboard_history.py` | 需要 Node；来源中文、状态标签、表头、跨页序号、空列表、宿主主题同步与首帧主题。浏览器另检查浅暗配色、表内吸顶、分页/选择/详情和响应式列对齐 |
| Dashboard 日志档位与轮询 | `python -m pytest -q tests/test_dashboard_log_polling.py tests/test_list_support.py` | 需要 Node；快速切档、迟到响应/错误/收尾、重启重拉、去重与暂停恢复 |
| 推文版式与订阅显示 | `python -m pytest -q tests/test_tweet_layout.py tests/test_search_display_username.py tests/test_subscription_display.py` | 来源链接清理、正文布局与翻译显隐、搜索作者、分组/实例显示 |
| 媒体传输编码 | `python -m pytest -q tests/test_media_transport.py` | 梯度组成、base64 上限、URL 主机白名单、传输降级先于内容降级、`uncertain` 不推进、编码记忆、非 OneBot 恒 `path` |
| OneBot 普通直发图文 | `python -m pytest -q tests/test_onebot_direct_images.py` | Event/UMO 图文同消息、多图编码、视频独立发送、传输重试与拆分降级、可能已送达保护、拒收兜底及仅媒体行为 |
| 发送失败分类与提示 | `python -m pytest -q tests/test_image_send_rejected_notice.py` | 拒收签名识别、ENOENT 不误判、`rejected` 保持 retryable 以免跳过有损降级链、拒收判定排在 uncertain 之前、提示链接遵循 `omit_status_url`、仅媒体不补提示 |
| 媒体画质与视频大小预检 | `python -m pytest -q tests/test_media_quality.py` | 图片三档、视频分辨率中位选择、大小预检降档、未知大小及 FxTwitter bitrate/时长估算 |
| 媒体缓存文件名 | `python -m pytest -q tests/test_media_utilities.py` | 百分号编码尾巴、query `format` 脏值、无扩展名回落 |
| 合并 RSS 管道、多博主批量、最低水位与回退 | `python -m pytest -q tests/test_merged_rss.py tests/test_scheduler_delivery.py` | 批次字符分批、最旧水位边界不漏推、转推过滤关闭时跳过合并走逐个请求、单博主空结果回退 |
| Twitter List RSS 优先与增量游标 | `python -m pytest -q tests/test_list_rss.py tests/test_list_support.py` | List RSS 优先拉取、Min-Id 增量游标、Redis 缓存、失败自动回退 HTML 翻页 |
| 搜索排序与热门流 | `python -m pytest -q tests/test_html_search_rotate.py tests/test_html_backend_query.py tests/test_backend_mode_switch.py tests/test_search_session_buffer.py` | latest 时间序、top 热门度排序、Tag 后台强制时间序、手动 session 缓存隔离 |
| 配置契约、类型解析与订阅导入 | `python -m pytest -q tests/test_config_contracts.py` | schema、迁移、空分组与旧混合订阅保留、标签查询可逆存储 |
| WebUI 分组回写契约 | `python -m pytest -q tests/test_webui_group_push_targets.py` | `update_group` 对 `push_targets` / `watch_users` 原样落盘：含无效条目 = 显式保留，缺失 = 显式删除；批量导入/移除保留隔离条目 |

## 高风险改动

| 改动 | 风险 | 要求 |
| --- | --- | --- |
| seen / 扫描水位写入时机 | 准备失败漏推或发送失败重复 | 补调度测试 |
| OneBot 合并转发 | 重复推送、视频节点失败 | 补 OneBot 平台测试 |
| 媒体传输编码梯度 | 有损降级抢在无损重试之前导致丢图丢视频；`uncertain` 推进梯度导致重复投递；base64 撑爆 payload | 补 `tests/test_media_transport.py` |
| QQ Official 官方 Bot | Markdown 原样泄漏、官方 UMO 字段错误、Markdown 拒绝降级、媒体失败导致重复推送 | 补 `tests/test_qq_official_delivery.py` |
| Lark post | 图片或文本降级异常；被误喂 base64 而不是文件路径 | 补 Lark 行为测试 |
| 纯文本过滤 | 引用媒体误判 | 补 RSS HTML 片段测试 |
| xdown 解析 | 下载错误或封面误发 | 补 media resolution 测试 |
| 配置迁移 | 老用户配置丢失 | 补 `config/compat.py` 相关测试 |
| 合并 RSS 水位边界与转推意图 | 多博主水位碰撞导致提前截断漏推；保留转推时误入合并流导致跨博主转推被静默丢弃 | 补 `tests/test_merged_rss.py`、`tests/test_scheduler_delivery.py` |

改公共模型、`scheduler/`、`delivery/sender.py`、`storage/` 或 `config/compat.py` 后，优先跑全量测试。

网络探测属于显式集成测试，不纳入默认 pytest；临时脚本统一放在 `testignore/`，并通过 `http_proxy`/`https_proxy` 或脚本参数记录代理配置。代理、Cookie 和响应正文不得进入提交或日志。
