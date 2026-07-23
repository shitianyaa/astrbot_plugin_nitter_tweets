# 第一刀：发布前收口计划

> 分支：`feat/tag-query-search`  
> 状态：**进行中**  
> 范围：主功能（标签分组 + HTML 搜索/回退）已落地后的发布前缺口  
> 不做：Playwright、RSS host 冷却大改、并发重试参数化（第二刀）

---

## 目标

让当前分支达到「可 review / 可试运行」质量：命令语义完整、测试覆盖高风险调度、文档与导出不误导。

---

## 任务清单

### 1. `/订阅导出 [分组名称]`（本任务优先）

**用法（与既有风格一致）：**

```text
/订阅导出
/订阅导出 分组名
/订阅导出 group_id
```

| 行为 | 说明 |
| ------ | ------ |
| 无参数 | 导出全部启用解析后的分组 |
| 有参数 | 按 `schedule_group(名称/id/别名)` 解析，只导出该组 |
| 找不到 | 提示可用分组列表，不导出空壳 |
| 博主组 | 导出 `watch_users` 逗号列表（规范化用户名） |
| 标签组 | 导出 `watch_queries` 的 `query` 逗号列表（保留 `#`/短语） |
| 空组 | 明确写 `（空）`，不省略行 |

**输出格式（统一带类型，避免标签组看起来像没订阅）：**

```text
Nitter 订阅导出
分组数: N 个
博主订阅: X 个
搜索订阅: Y 个
订阅列表:
默认分组 (default, 博主, 1 个): NASA
科技 (tech, 博主, 2 个): OpenAI,SpaceX
标签示例 (tags1, 标签, 2 个): #圣娅,python programming
```

可选末尾提示（单行即可）：

```text
提示: 博主组 /订阅导入 用户列表 分组名 ；标签组 /标签导入 查询列表 分组名
```

**代码落点：**

- `main.py`：`cmd_tweets_export_subscriptions` 增加 `args=GreedyStr`
- `command_handlers/subscriptions.py`：`_cmd_tweets_export_subscriptions_impl`、`_export_subscription_lines`
- 测试：`tests/test_subscription_import.py` 更新旧期望 + 标签组 + 按名过滤

**验收：**

- 纯博主配置导出仍可读、可对照导入
- 含标签组时显示查询而非假「0 账号」
- `/订阅导出 科技` 只出该组
- `pytest` 相关用例绿

---

### 2. 标签调度 E2E 测试（已完成）

文件建议：`tests/test_scheduler_tag_delivery.py`

| 用例 | 期望 |
| ------ | ------ |
| 首次有结果 | 只 init seen，不推送 |
| 第二次新 ID | 推送且写 seen |
| 首次空结果 | 不 init watermark/seen |
| 发送失败 | 不写 seen |
| 标签组强制串行 | mock 可观察调用顺序（可选） |

mock `html_backend.search`，复用 `test_scheduler_delivery` 的 storage/sender 夹具风格。

---

### 3. 文档同步（已完成）

| 文件 | 内容 |
| ------ | ------ |
| `AGENTS.md` | 代码地图加 `html_backend`、`group_type`、`/推文搜索`、`/标签导入`、`/订阅导出` |
| `docs/project/configuration.md` | 三列表、`group_type`、`watch_queries` |
| `README.md` | 导出用法一行（若缺） |
| `CHANGELOG.md` | 导出支持标签 + 可选分组名 |

---

### 4. Dashboard diff 收敛（已完成）

- `pages/dashboard/app.js` 去掉纯缩进重写，只保留功能 diff  
- `node --check` 仍通过  

（可与导出分两次提交，避免混杂。）

---

### 5. 第二刀（后置；决策见 Progress）

用户倾向：S1=30s–5min；S3=全局配置；S6=同分支先堆。S2/S4/S5 见 Progress 白话与建议默认。

### 5b. 原「明确后置」清单

- RSS host 429 冷却 / 失败降权  
- `retry_attempts` schema 化  
- HTML RateLimiter 加锁（可插在 2 之后若有空）  
- query `changed` 自愈回写  

---

## 执行顺序

```text
1 导出（本轮） → 2 标签调度 E2E → 3 文档 → 4 app.js 收敛
每步：改代码 → 相关 pytest → 需要时更新 README/CHANGELOG
```

## 验证命令

```powershell
python -m pytest -q tests/test_subscription_import.py -k export
python -m pytest -q
ruff check command_handlers/subscriptions.py main.py
```
