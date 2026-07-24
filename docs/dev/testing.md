# 测试与回归检查

## 基础命令

```powershell
python -m pytest -q
ruff check .
python -m py_compile main.py scheduler/__init__.py scheduler/runner.py scheduler/config.py scheduler/models.py media_support/client.py media_support/service.py delivery/sender.py
```

## 分层验证矩阵

| 改动类型 | 最小检查 | 关注点 |
| --- | --- | --- |
| RSS、分页、转发过滤、纯文本过滤 | `python -m pytest -q tests/test_nitter_pagination.py` | 首屏完整扫描、`Min-Id` 水位分页、empty feed、引用媒体、card_img |
| 调度、seen、QQ 合并、Telegram flood | `python -m pytest -q tests/test_scheduler_delivery.py` | 独立扫描基准、全部差集发送、失败不推进基准、合并顺序、限流重试 |
| 配置 schema、迁移、命令解析、订阅维护、AI | `python -m pytest -q tests/test_subscription_import.py` | 旧配置、默认分组、命令参数、provider fallback |
| 媒体解析、视频限制、下载重试 | `python -m pytest -q tests/test_media_resolution.py` | xdown、分辨率、时长、大小、重试 |
| 缓存清理 | `python -m pytest -q tests/test_media_cleanup.py` | 递归清理、类型统计、空目录 |
| 存储适配和旧 KV 迁移 | `python -m pytest -q tests/test_storage_adapter.py` | KV 到 SQLite |
| SQLite 线程安全 | `python -m pytest -q tests/test_sqlite_threading.py` | `asyncio.to_thread` 调用 |

## 高风险改动

| 改动 | 风险 | 要求 |
| --- | --- | --- |
| seen / 扫描水位写入时机 | 失败后漏推或跨过积压 | 补调度测试 |
| OneBot 合并转发 | 重复推送、视频节点失败 | 补 OneBot 平台测试 |
| Lark post | 图片或文本降级异常 | 补 Lark 行为测试 |
| 纯文本过滤 | 引用媒体误判 | 补 RSS HTML 片段测试 |
| xdown 解析 | 下载错误或封面误发 | 补 media resolution 测试 |
| 配置迁移 | 老用户配置丢失 | 补 `config/compat.py` 相关测试 |

改公共模型、`scheduler/`、`delivery/sender.py`、`storage/` 或 `config/compat.py` 后，优先跑全量测试。
