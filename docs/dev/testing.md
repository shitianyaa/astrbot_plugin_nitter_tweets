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
| RSS、分页、转发过滤、纯文本过滤 | `python -m pytest -q tests/test_nitter_pagination.py` | 首屏完整扫描、`Min-Id` 水位分页、empty feed、引用媒体、card_img |
| 调度、seen、私人号 OneBot 合并、QQ Official、Telegram flood | `python -m pytest -q tests/test_delivery_platforms.py tests/test_scheduler_delivery.py tests/test_qq_official_delivery.py` | 独立扫描基准、发送调用失败跳过、准备失败不推进基准、合并顺序、官方 Markdown/纯文本切换、媒体部分成功、限流重试 |
| 配置 schema、迁移、命令解析、订阅维护、AI | `python -m pytest -q tests/test_subscription_import.py` | 旧配置、默认分组、命令参数、provider fallback |
| 发布版本元数据 | `python -m pytest -q tests/test_release_version.py` | README 徽章、`metadata.yaml`、`main.py`、CHANGELOG 版本一致，QQ Official 最低 AstrBot 版本 |
| 媒体解析、视频限制、下载重试 | `python -m pytest -q tests/test_media_resolution.py` | xdown、分辨率、时长、大小、重试 |
| 缓存清理 | `python -m pytest -q tests/test_media_cleanup.py` | 递归清理、类型统计、空目录 |
| 存储适配和旧 KV 迁移 | `python -m pytest -q tests/test_storage_adapter.py` | KV 到 SQLite |
| SQLite 线程安全 | `python -m pytest -q tests/test_sqlite_threading.py` | `asyncio.to_thread` 调用 |
| 结构化日志与 HTML 门禁 | `python -m pytest -q tests/test_observability.py tests/test_html_gate_detection.py` | 脱敏字段、摘要统计、显式 Anubis/Poast 优先，真实时间线优先于通用门禁文案 |
| 推文版式与订阅显示 | `python -m pytest -q tests/test_tweet_layout.py tests/test_subscription_display.py` | 来源链接清理、正文布局、分组/实例显示 |

## 高风险改动

| 改动 | 风险 | 要求 |
| --- | --- | --- |
| seen / 扫描水位写入时机 | 准备失败漏推或发送失败重复 | 补调度测试 |
| OneBot 合并转发 | 重复推送、视频节点失败 | 补 OneBot 平台测试 |
| QQ Official 官方 Bot | Markdown 原样泄漏、官方 UMO 字段错误、Markdown 拒绝降级、媒体失败导致重复推送 | 补 `tests/test_qq_official_delivery.py` |
| Lark post | 图片或文本降级异常 | 补 Lark 行为测试 |
| 纯文本过滤 | 引用媒体误判 | 补 RSS HTML 片段测试 |
| xdown 解析 | 下载错误或封面误发 | 补 media resolution 测试 |
| 配置迁移 | 老用户配置丢失 | 补 `config/compat.py` 相关测试 |

改公共模型、`scheduler/`、`delivery/sender.py`、`storage/` 或 `config/compat.py` 后，优先跑全量测试。

网络探测属于显式集成测试，不纳入默认 pytest；临时脚本统一放在 `testignore/`，并通过 `http_proxy`/`https_proxy` 或脚本参数记录代理配置。代理、Cookie 和响应正文不得进入提交或日志。
