# 开发环境与本地调试

## 基础环境

- Python 3.10+
- AstrBot SDK 或运行环境
- `pytest`
- `ruff`

依赖文件 `requirements.txt` 目前为空白占位。不要随意新增运行时依赖；优先使用标准库和现有模块。

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
```

视频下载：

```powershell
python scripts/test_video_download.py
```

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
