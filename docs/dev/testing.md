# 测试与回归检查

## 基础命令

`pytest.ini` 将默认收集范围限制为 `tests/`，因此 `testignore/` 中的临时探测脚本不会被全量测试误执行。

```powershell
python -m pytest -q
ruff check .
ruff format --check .
git diff --check
python -m py_compile main.py scheduler/__init__.py scheduler/runner.py scheduler/config.py scheduler/models.py media_support/client.py media_support/service.py delivery/sender.py
```

## 分层验证矩阵

| 改动类型 | 最小检查 | 关注点 |
| --- | --- | --- |
| 调度、seen、私人号 OneBot 合并、QQ Official、Telegram flood | `python -m pytest -q tests/test_delivery_platforms.py tests/test_scheduler_delivery.py tests/test_qq_official_delivery.py` | 独立扫描基准、发送调用失败跳过、准备失败不推进基准、合并顺序、官方 Markdown/纯文本切换、媒体部分成功、限流重试 |
| 发布版本元数据 | `python -m pytest -q tests/test_release_version.py` | README 徽章、`metadata.yaml`、`main.py`、CHANGELOG 版本一致，QQ Official 最低 AstrBot 版本 |
| 结构化日志与 HTML 页面分类 | `python -m pytest -q tests/test_observability.py tests/test_html_gate_detection.py` | 脱敏字段、摘要统计、时间线/空页/登录维护/异常页分类 |
| 推文版式与订阅显示 | `python -m pytest -q tests/test_tweet_layout.py tests/test_subscription_display.py` | 来源链接清理、正文布局、分组/实例显示 |
| 媒体传输编码 | `python -m pytest -q tests/test_media_transport.py` | 梯度组成、base64 上限、URL 主机白名单、传输降级先于内容降级、`uncertain` 不推进、编码记忆、非 OneBot 恒 `path` |
| 发送失败分类与提示 | `python -m pytest -q tests/test_image_send_rejected_notice.py` | 拒收签名识别、ENOENT 不误判、`rejected` 保持 retryable 以免跳过有损降级链、拒收判定排在 uncertain 之前、提示链接遵循 `omit_status_url`、仅媒体不补提示 |
| 媒体缓存文件名 | `python -m pytest -q tests/test_media_file_name.py` | 百分号编码尾巴、query `format` 脏值、无扩展名回落 |
| 合并 RSS 管道、多博主批量、最低水位与回退 | `python -m pytest -q tests/test_merged_rss.py tests/test_scheduler_delivery.py` | 批次字符分批、最旧水位边界不漏推、转推过滤关闭时跳过合并走逐个请求、单博主空结果回退 |
| Twitter List RSS 优先与增量游标 | `python -m pytest -q tests/test_list_rss.py tests/test_list_support.py` | List RSS 优先拉取、Min-Id 增量游标、Redis 缓存、失败自动回退 HTML 翻页 |
| 搜索排序与热门流 | `python -m pytest -q tests/test_search_sort.py tests/test_html_backend_query.py` | latest 时间序、top 热门度排序、Tag 后台强制时间序、手动 session 缓存隔离 |
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
