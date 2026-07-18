# 开发环境与本地调试

## 基础环境

- Python 3.10+
- AstrBot SDK 或运行环境
- `pytest`
- `ruff`

运行时依赖由 `requirements.txt` 声明。代理请求使用 `requests`，SOCKS5/SOCKS5h 通过 Requests 官方支持的 `PySocks` 后端实现；更新依赖后需要执行 `python -m pip check`。

## 常用目录

```text
command_handlers/    # 命令实现
delivery/            # 平台发送适配器
media_support/       # RSS、媒体、缓存
tests/               # 回归测试
scripts/             # 本地诊断脚本
docs/                # 项目和开发文档
```

## 本地诊断

RSS 抓取：

```powershell
python scripts/probe_nitter_fetch.py nasa 5
python scripts/probe_nitter_fetch.py nasa 5 --include-reposts
python scripts/probe_nitter_fetch.py nasa 5 --skip-plain-text
python scripts/probe_proxy_fetch.py socks5h://127.0.0.1:1080
```

视频下载：

```powershell
python scripts/test_video_download.py
```

`probe_proxy_fetch.py` 默认抓取 `nasa` 1 条带作者媒体的推文，并用同一个显式代理完成 RSS、xdown 和媒体下载。下载使用隔离临时目录，除非传入 `--keep-dir`，否则结束后不会保留媒体文件。

## 运行数据

不要依赖源码目录下的 `data/` 作为正式运行目录。AstrBot 运行期数据应通过插件数据目录获取。

不要提交：
- `data/`
- `cache/`
- `*.db`
- `*.db-wal`
- `*.db-shm`
- `tests/downloads/`
- `.pytest_cache/`
- `.ruff_cache/`
