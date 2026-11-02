# 开发环境与本地调试

## 基础环境

- Python 3.12+；CI 使用 Python 3.13。
- Node 24，用于 Dashboard 语法与行为检查。
- `requirements-dev.txt` 固定真实 AstrBot SDK、pytest、pytest-asyncio、Ruff 和 pre-commit。

```powershell
python -m pip install -r requirements-dev.txt
python -m pip check
python scripts/check.py
```

默认使用系统临时目录；需要固定产物位置时加 `--temp-root <目录>`。不要全局安装或升级依赖，建议在独立虚拟环境运行。插件的 `requirements.txt` 仍为空白占位，开发依赖不进入插件运行安装或发布包。

`requirements-dev.txt` 里的 AstrBot SDK 是经过验证的基线，升级它应当作为独立改动并重跑门禁，而不是随手跟随最新版。`pytest.ini` 已设置 `pythonpath = .`，因此从仓库根目录直接跑 `pytest` 或 `python -m pytest` 都可导入插件模块；不需要修改 `PYTHONPATH`。

可选启用本仓库提交 hook：`pre-commit install`。仅检查暂存 Python 的 Ruff 和格式，不自动修改文件，也不在每次 commit 跑全量 pytest。安装 hook 会改变本仓库 Git hooks，须由维护者明确执行。

## 常用目录

```text
command_handlers/    # 命令实现
delivery/            # 平台发送适配器
media_support/       # RSS、媒体、缓存
tests/               # 回归测试
scripts/             # 本地诊断脚本
testignore/          # 被 .gitignore 忽略的一次性测试和网络探测
docs/                # 项目和开发文档
```

## 本地诊断

RSS 抓取：

```powershell
python scripts/probe_nitter_fetch.py nasa 5 --instance http://nitter:8080
python scripts/probe_nitter_fetch.py nasa 5 --instance http://nitter:8080 --include-reposts
python scripts/probe_nitter_fetch.py nasa 5 --instance http://nitter:8080 --skip-plain-text
```

List/HTML 探测脚本、代理测试和临时输出放在 `testignore/`。需要本地代理时，在脚本或命令中显式使用 `http://127.0.0.1:3067` 等代理地址；不要把 Cookie、token 或完整会话响应写入文件。测试脚本应记录目标 URL、实例、代理和结果摘要，便于复现。只使用可信的自建 Nitter 实例进行探测；Nitter 的管理面应隔离在不可信网络之外，不要暴露到公网。

视频下载：

```powershell
python scripts/test_video_download.py https://x.com/user/status/123
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
- 仓库根目录的一次性测试脚本（请移入 `testignore/`）
