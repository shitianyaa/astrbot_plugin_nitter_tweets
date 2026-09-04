# Nitter 推文面板重做计划

## 背景

AstrBot 插件 `astrbot_plugin_nitter_tweets` 的 WebUI 运维面板。当前界面过度装饰（渐变/发光/模糊滤镜/动画），要推倒重做一个简约风。

## 技术约束

- AstrBot Plugin Pages 系统，注入 `window.AstrBotPluginPage`（简称 `bridge`）
- `await bridge.ready()` 等 bridge 就绪
- `bridge.apiGet(endpoint, params)` → GET，`bridge.apiPost(endpoint, body)` → POST
- endpoint 传裸路由后缀（如 `"web/overview"`），host 自动拼前缀
- 响应统一信封：`{success: bool, error: str, ...payload}`，`success=false` 时前端抛错
- **Vanilla JS，不用框架**。`<script type="module">` 已可用，ES module import/export 没问题
- 暗色/亮色主题切换（`localStorage` 持久化，`prefers-color-scheme` 兜底）

## 设计方向

- **简约第一**：无渐变、无发光、无模糊滤镜、无装饰动画。边框和背景色区分层级，不靠阴影堆叠
- **信息密度**：运维面板不是落地页，一屏多放信息，少留白
- **语义色**：成功=绿、警告=橙、危险=红、其余中性灰。不要 6 种 accent 色系
- **系统字体栈**：`system-ui, -apple-system, sans-serif`，不引外部字体
- **CSS 变量**：只留 `--bg --panel --text --text-muted --line --primary --success --warn --danger --radius`，约 10 个
- **交互**：危险操作走 confirm 弹窗，操作完成走 toast，表单用 inline validation

## 4 个 Tab + 功能清单

### 1. 控制台总览

数据源：`GET web/overview`

展示：
- 调度器状态（运行中/未运行）、后台检查开关
- 分组/博主订阅/搜索订阅/List/推送目标 计数（含无效数）
- 功能开关（图片/视频/翻译）
- 配置摘要（实例数、检查间隔、合并阈值等）
- 已配置实例列表（chip 形式）
- attention_items（异常项，按 level 分色）
- **danger zone**（从原 cleanup tab 合并）：
  - 清理媒体缓存 → `POST web/cache/clear`（无参数）
  - 清理推送记录 → `POST web/seen/clear`（参数 `group_id?` + `confirm="CLEAR_ALL"` 清全部），范围选择器从 `GET web/groups` 的分组列表填充

### 2. 分组订阅管理

数据源：`GET web/groups`（返回分组数组，每个含完整序列化字段）

分组列表：
- 显示名称、类型（博主/搜索/List）、启用状态、脏标记（有未保存编辑时）
- 点击切换选中分组
- 新建分组 → `POST web/groups/create`（参数 `name?` `group_type?`）
- 删除分组 → `POST web/groups/delete`（参数 `group_id` `force=true` `confirm="DELETE"`，default 分组不可删）

分组编辑器（选中分组后展示）：
- 基本字段：分组名称（可编辑）、ID（只读）、类型（只读）、启用开关
- 调度字段：间隔检查开关、每日检查时间（多行文本，逗号或换行分隔）
- 过滤字段：转发过滤、纯文本过滤、仅媒体、省略状态URL、有译文时显示原文
- push_targets：可增删的目标 UMO 列表
- 目标探测 → `POST web/targets/probe`（参数 `group_id`），返回每个目标的平台/有效性/是否支持合并转发
- 目标黑名单：按目标 UMO 管理 blocked_users → `GET web/target-blacklists` + `POST web/target-blacklists/update`（参数 `target_umo` `blocked_users[]`）
- watch_users / watch_queries / watch_lists：根据分组类型显示对应列表，支持增删
  - 导入订阅 → `POST web/subscriptions/import`（参数 `group_id` `entries`）
  - 删除订阅 → `POST web/subscriptions/delete`（参数 `group_id` `entries`）
- 保存 → `POST web/groups/update`（提交 draft 全字段）
- 立即检查 → `POST web/check`（参数 `group_id`，分组须启用且无未保存改动）

草稿系统：编辑不立即保存，本地 draft + dirty 检测，切换分组/刷新时提示丢弃。

### 3. 推送历史

数据源：`GET web/history`（参数 `group_id?` `username?` `limit` `offset`）

- 筛选：分组下拉、用户名输入、数量（1-50）
- 分页
- 每条记录显示：分组名、订阅源、状态ID、目标、推送时间、送达状态（成功/失败/部分失败）、原文摘要、译文摘要
- 复制原链接（`dataset.copy-link` 委托）
- 重推 → `POST web/history/replay`（参数 `record_id` `target_umos?`），重推前弹 confirm 让选目标
- 失效分组检测 → `GET web/history/orphans`，返回不属于当前配置的分组历史记录
- 删除失效记录 → `POST web/history/orphans/delete`（参数 `group_id` `confirm="DELETE"`）

### 4. 实例能力诊断

数据源：`POST web/mirror/probe`（参数 `username?` `query?` `list_id?` `limit?` `instance?`）

- 表单：用户名（默认 nasa）、搜索内容、List ID（可选）、数量、实例 URL（留空测全部）
- 已配置实例列表（点击填入 URL）
- 结果按实例分组，每实例显示 RSS/HTML/搜索/List 四项检查的成功状态、推文数、耗时、错误
- 成功的检查展示推文摘要（status_id、链接、文本预览、媒体数）

## 交互模式

- **confirm 弹窗**：危险操作（删除分组/清缓存/清 seen/重推/删失效记录）弹模态确认，focus trap，ESC/点遮罩取消
- **toast**：操作成功/失败提示，3 秒自动消失
- **loading 状态**：两个层级——`state.loading`（页面加载）、`state.actionBusy`（操作中），都禁用相关按钮
- **事件委托**：动态渲染的内容用 `dataset.*` 属性 + 容器级 `click`/`input`/`change` 监听
- **alert banner**：操作结果内联提示（成功绿/错误红），非 toast 的补充

## 文件结构

```
pages/dashboard/
  index.html    — HTML 骨架（sidebar + main，4 个 view section，confirm dialog，toast container）
  style.css     — 简约 CSS（目标 < 800 行）
  app.js        — 入口：import 模块、boot、bindEvents、renderAll、switchView
  core.js       — 共享：state/els、dom 工具、api 封装、feedback、theme、confirm、withAction
  groups.js     — 分组：列表、编辑器、草稿、CRUD action
  views.js      — 其余：overview、history、mirror
  _page.json    — 不动（AstrBot 元数据）
```

## 不要做的

- 不要 glow/blur/gradients/阴影堆叠
- 不要装饰动画（pulse/spin/fade-in）
- 不要 6 种 accent 色
- 不要外部字体
- 不要改后端 API
- 不要加新功能（只重做界面）
