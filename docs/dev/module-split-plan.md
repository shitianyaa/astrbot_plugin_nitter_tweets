# 模块拆分计划（维护向，不为拆而拆）

> 状态：**计划已定，未开工拆分**  
> 原则：有真实痛点再拆；行为零变化；与功能 PR 分开  
> 分支语境：`feat/tag-query-search`（标签 + 第一刀 + 第二刀之后）

---

## 1. 目标

- 方便后续**增减**：新抓取源、新发送策略、新命令类型、新 seen 语义。
- **不为拆而拆**：行数大但边界清晰、很少改的文件，保持原样。
- 拆完后同一职责放在**同一文件夹（包）**内，对外入口保持稳定。

---

## 2. 原则

1. **先交付功能，再重构**  
   标签 / HTML / 第一刀 / 第二刀先 commit、PR；拆分用**单独重构 PR**，不与功能大包混提。

2. **按变化原因拆，不按「对称好看」拆**  
   - 改怎么拉 → fetch  
   - 改怎么准备媒体 → prepare  
   - 改怎么发 → send  
   - 改配置形状 → config  

3. **包内可多文件；需要时再分子目录**  
   第一次优先**同级文件**；单文件再次膨胀再收成子包。

4. **对外 import 稳定**  
   `from scheduler import NitterTweetScheduler`（或现有公开入口）尽量不变；内部路径可挪。

5. **每笔拆分必须绿测**  
   至少：`tests/test_scheduler_delivery.py`、`tests/test_scheduler_tag_delivery.py`，以及触及模块的专项；必要时全量 pytest。

6. **明确不拆**  
   - `main.py`（已够薄）  
   - `media_support/html_backend/*`（已按 modes/pool/parser 分好）  
   - 仅为测试文件行数大而先拆测试（业务边界稳定后再说）

---

## 3. 唯一强烈建议：调度器

### 3.1 现状

| 文件 | 约行数 | 问题 |
|------|--------|------|
| `scheduler/runner.py` | ~2500 | 拉取 / 准备 / 发送 / seen / 状态混在一类；标签与仅媒体改动都挤这里 |

### 3.2 目标布局（第一阶段：同级文件，不先套深层子包）

```text
scheduler/
  __init__.py              # 对外 export 保持稳定
  runner.py                # 薄：tick、锁、run_check 编排，调用下列模块
  fetch_pipeline.py        # 博主 RSS / HTML 回退 / 标签 search → UserFetchResult
  prepare_pipeline.py      # 媒体准备、media_only、失败分类
  send_pipeline.py         # 即时发送、合并缓冲、平台分流调用
  config.py                # 已有：ScheduleGroup 解析
  models.py                # 已有
  formatting.py            # 已有
```

**不**在第一阶段强制：

```text
scheduler/fetch/
scheduler/delivery_flow/
```

等某一 pipeline 文件自身再明显膨胀（例如持续 >800–1000 行且多人改），再收成子文件夹。

### 3.3 方法归属（示意）

| 新文件 | 从 runner 挪出的职责（示例） |
|--------|------------------------------|
| `fetch_pipeline.py` | `_fetch_group_users` / `_fetch_group_user` / `_fetch_group_query` / HTML fallback |
| `prepare_pipeline.py` | `_prepare_*` / media_only 判定 / prepare 并发 |
| `send_pipeline.py` | `_send_*` / merge buffer / cleanup 与发送绑定部分 |
| `runner.py` 保留 | `run_check`、锁、tick、把三阶段串起来、薄委托 |

seen / watermark / status 可**暂时仍留 runner**，第二阶段再视痛点抽出 `seen_ops.py` / 并入 `formatting`。

### 3.4 拆分顺序（单笔 PR 可只做一步）

1. `send_pipeline`（体量大、与 fetch 耦合相对弱）  
2. `fetch_pipeline`（博主 vs 标签策略清晰，利于以后加源）  
3. `prepare_pipeline`  
4. （可选）seen / status  

每步：**只挪代码 + 测绿**，不改行为。

### 3.5 验收

- [ ] 公开类型/入口未破坏（测试与 main 导入）  
- [ ] 博主调度 + 标签调度回归通过  
- [ ] 无功能变更（diff 以 move 为主）  
- [ ] AGENTS 代码地图更新 `scheduler/` 结构  

---

## 4. 有痛点再拆（非现在必做）

| 模块 | 约行数 | 建议文件夹/文件 | 何时拆 |
|------|--------|-----------------|--------|
| `media_support/client.py` | ~1080 | 同目录：`rss_parse.py` + 薄 `client.py`；已有 `rss_run_skip.py` | 大改 RSS 解析/过滤时 |
| `command_handlers/subscriptions.py` | ~850 | `command_handlers/subscriptions/`：`blogger.py` / `tag.py` / `export.py` + mixin 转发 | 再加一类订阅命令时 |
| `plugin_api/api.py` | ~1370 | `plugin_api/routes_*.py` 或 `plugin_api/routes/` | 路由继续膨胀时 |
| `storage/sqlite.py` | ~1600 | `storage/`：`seen_repo.py` / `history_repo.py` / `migrations.py` | 再改 schema/seen 语义时 |
| `delivery/sender.py` | ~1350 | 已有平台文件；可增 `merge_strategy.py` | 合并/降级逻辑再膨胀时 |
| `pages/dashboard/app.js` | ~2300 | `pages/dashboard/`：`groups.js` / `queries.js` / `api.js` + 入口 | 下次大改 WebUI 时 |

**对应「以后加减」：**

| 要加的能力 | 应落在 |
|------------|--------|
| 新抓取源 / 搜索 | `fetch_pipeline` + `html_backend` / client |
| 新平台发送 | `delivery/*` + `send_pipeline` |
| 新分组类型 | `scheduler/config` + fetch 策略 + Dashboard |
| 新管理命令 | `command_handlers/` 按域文件 |
| 新 seen 语义 | `storage/*` + runner/seen |

---

## 5. 文件夹纪律（长期）

1. **一个目录 ≈ 一种变化原因**，避免「工具垃圾桶」包。  
2. **入口薄**：`__init__.py` / `runner.py` / `main.py` 不堆业务。  
3. **禁止**为对称给每个子系统建空包。  
4. **双导入**模式（`try: from .x` / `except ImportError`）新文件必须遵守。  
5. 拆分 PR **不**夹带功能；**不**顺手改文案/默认值。

---

## 6. 与现有计划的关系

| 文档 | 关系 |
|------|------|
| `html-search-fallback-plan.md` | 产品功能（标签/HTML）— 已实施 |
| `phase1-release-prep.md` | 第一刀/第二刀收口 — 已实施 |
| **本文** | 维护向重构 — **功能交付之后** |

建议节奏：

```text
功能 commit / PR
  → 合并或稳定后
  → 单独「scheduler 拆分」PR（按 §3.4 分步）
  → 其它模块按痛点再开 PR
```

---

## 7. 开工条件

用户明确说例如：

- `按 module-split-plan 拆 send_pipeline`  
- `开始拆 runner（行为不变）`  

之前**不改业务结构**，仅维护本计划与 Progress 引用。

---

## 8. 状态

| 项 | 状态 |
|----|------|
| 计划成文 | 2026-07-23 |
| runner 拆分实施 | 未开始 |
| 其它模块拆分 | 未开始（按需） |
