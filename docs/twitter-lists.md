# Twitter List 订阅指南

本文档介绍如何使用 Twitter List 订阅功能，聚合关注多个账号的推文到一个时间线。

## 什么是 Twitter List

Twitter List 是 Twitter/X 平台提供的列表功能，可以将多个账号添加到一个列表中，查看这些账号的聚合时间线。常见用途：

- **关注列表**：把你关注的人分类（科技圈、新闻媒体、游戏博主等）
- **主题列表**：围绕特定主题创建列表（AI 研究、开源项目、前端开发等）
- **团队列表**：监控团队成员或合作伙伴的动态

## 前置要求

### 1. List 必须是 Public（公开）

Nitter 无法访问需要登录的 Private List，订阅的 List 必须设置为 **Public**。

**如何设置**：
1. 在 Twitter/X 网页或 App 中打开你的 List
2. 点击"编辑列表"
3. 确保"Make private"选项**未勾选**

### 2. 新建 List 需等待 Nitter 收录

插件通过 **Nitter HTML 搜索实例**拉 List 时间线，不是直连 X 官方 API。

**刚创建不久的 List**（创建时间较短）往往要 **过一段时间** 才会被 Nitter 镜像索引到；在此之前可能一直空结果或抓不到。实践中常见要等约 **10–30 分钟**（随镜像与平台波动，非固定 SLA）。空结果时先等再试，不要立刻判定 ID 配错。

成员增删同样可能有数分钟级缓存延迟。

### 3. 获取 List ID

List ID 是一串正整数数字，从 List 的 URL 中获取。新建 List 通常是 18-20 位，早期 List 的 ID 可能更短；插件接受的最大值为 `uint64` 上限 `18446744073709551615`：

```
https://x.com/i/lists/1553232306718257152
                       ^^^^^^^^^^^^^^^^^^^^
                       这就是 List ID
```

**如何获取**：
- 网页版：打开 List 页面，从浏览器地址栏复制数字部分
- App：分享 List → 复制链接 → 提取数字部分

### 4. 把关注批量加入 List（可选工具）

本插件**只订阅**已有 Public List 的 ID，不会在 X 上创建 List 或批量加成员。

若需要把 Following 里的账号快速装进某个 List，可使用第三方浏览器扩展 [X Follow to List](https://github.com/DrErwin/X-Follow-to-List)（Chrome / Edge 等 Chromium；本地运行，无需 X API Key）：

1. 从 [GitHub Release](https://github.com/DrErwin/X-Follow-to-List/releases/latest) 下载 ZIP，解压后在浏览器扩展页开启开发者模式并「加载已解压的扩展程序」。
2. 登录 X，打开 `https://x.com/你的用户名/following`，滚动加载需要的账号。
3. 在扩展中筛选、勾选账号，填入目标 List 分享链接后开始任务（建议先小批量、拉长间隔）。
4. 确认 List 为 Public，再把 List ID 填入本插件的 `watch_lists` 或 Dashboard 列表分组。

**速率限制：** X 对「将用户加入 List」有官方限制。实践中 **约 24 小时内大约只能成功约 100 次量级**（随账号与平台策略变化，非固定承诺）。请分批、分多天导入；触发限制后暂停，不要高频重试。该扩展与本插件相互独立，使用风险自负。

## 配置 List 分组

### 方式一：WebUI 配置（推荐）

1. 打开 AstrBot 插件页面 → **Nitter 推文面板**
2. 进入 **分组订阅管理**
3. 点击 **添加分组** → 选择 **"列表分组"** 模板
4. 填写配置：
   - **分组名称**：例如"我关注的人"、"科技圈"
   - **Twitter List 订阅**：每行一个 List ID
   - **分组推送目标**：填写 UMO（在目标会话中发送 `/sid` 获取）
   - **单次检查最多推送推文数**：**强烈建议设置**（如 10-20），防止刷屏
5. 保存配置

Dashboard 会在保存前检查 List ID 是否为 1-20 位纯数字，并检查当前草稿和已有配置中的重复值；服务端还会校验 ID 为正 `uint64`，拒绝 `0` 和超过 `18446744073709551615` 的值。概览会单独统计 List 数量和无效 List ID，历史记录的订阅源显示为 `List {id}`，不会显示内部存储前缀。

### 方式二：配置文件

编辑插件配置文件，在 `tweet_groups` 中添加：

```yaml
tweet_groups:
  - name: 我关注的人
    group_id: my_follows  # 自动生成，首次可留空
    group_type: list
    enabled: true
    watch_lists:
      - "1553232306718257152"
      - "2081623084780671084"
    push_targets:
      - "aiocqhttp:GroupMessage:123456"
    filter_reposts_enabled: true  # 分组子开关，默认开启
    max_tweets_per_check: 10  # 强烈建议设置
```

## 重要配置项说明

### `max_tweets_per_check`（必设）

List 聚合多人推文，可能在短时间内产生大量更新。**强烈建议设置此项**（如 10-20），避免一次推送过多消息刷屏。

超过上限的较旧推文会标记 seen，不会在下一轮重新补发；该选项用于控制消息量，不是积压队列。

```yaml
max_tweets_per_check: 10  # 每个 List 单次检查最多推送 10 条
```

### `html_max_pages`

这是全局 HTML 配置，控制一次 Tag/List 抓取最多请求多少页。每翻一页通常会增加一次页面 GET。首次订阅只取最多 20 条建立基准；已有水位后本轮扫描可以超过 20 条，并继续翻页到命中旧水位或游标结束，但持久化水位仍最多保存最新 20 个 ID。达到 `html_max_pages` 后仍未命中旧基准时，`max_tweets_per_check=0` 会跳过推送并自动用当前第一页最多 20 个状态 ID 重建基准；正数会按上限推送，所有目标处理完后再重建。第一页没有有效状态 ID、发送准备失败或基准写入失败时保留旧水位；发送调用失败会跳过当前批次并推进 seen，不在下轮自动重试。默认 `1`，可按自建实例性能和更新量设置为 `1-3`。

```yaml
basic:
  html_max_pages: 1
```

### `filter_reposts_enabled`

List 分组内的同名配置是子开关，默认开启。只有全局 `basic.filter_reposts_enabled` 总开关与当前 List 分组子开关都开启时才过滤转发；任一关闭都会保留转发。

```yaml
filter_reposts_enabled: true
```

### `filter_plain_text_enabled`

开启后只推送包含媒体（图片/视频/GIF）的推文，跳过纯文本推文。

```yaml
filter_plain_text_enabled: true  # 适合关注摄影、设计等媒体内容创作者
```

### `media_only_enabled`

开启后只发送媒体，不附带推文文字、链接、翻译。

```yaml
media_only_enabled: true  # 打造纯图片/视频推送频道
```

## 检查调度

List 分组与博主/标签分组共享相同的检查调度机制：

- `check_on_startup=true` 时，调度存储初始化完成后会按分组顺序首检所有启用且配置了 List 和有效推送目标的分组，即使该分组只有每日检查或没有定时槽位；首检后会锚定当前槽位，避免重复检查。
- 首检、手动 `/推文检查` 和 WebUI 检查都会等待存储初始化完成；初始化失败时不会抓取或发送，并记录 `storage_not_ready`。

### 间隔检查

```yaml
interval_check_enabled: true  # 启用间隔检查
# 检查间隔由全局配置 schedule.check_interval_minutes 控制
```

### 每日定点检查

```yaml
daily_check_times:
  - "09:00"
  - "18:00"
# 每天 9:00 和 18:00 检查一次
```

## 工作流程

```
定时触发
  ↓
抓取 List 时间线（通过 Nitter HTML 搜索实例）
  ↓
解析推文（复用 parse_timeline_html）
  ↓
首次订阅取最多 20 条建立基线；已有水位则翻页到旧水位或游标结束
  ↓
Tag/List 达到 html_max_pages 仍未命中旧基准时按 max_tweets_per_check 处理：0 不推送并自动重建，正数按上限推送后自动重建；无有效 ID、发送准备失败或写入失败时保留旧水位，发送调用失败则跳过当前批次并推进 seen
  ↓
按全局与分组双层开关过滤转发
  ↓
过滤纯文本（如果分组启用）
  ↓
与 seen 数据库去重
  ↓
准备媒体（图片/视频）+ AI 翻译
  ↓
推送到目标会话
  ↓
记录 seen（键格式：group_id + "list:{list_id}"）
```

## 已知限制

### 1. Private List 不可访问

Nitter 无法读取需要登录的 Private List，订阅的 List 必须设置为 **Public**。

### 2. 新建 List 延迟生效

见上文「前置要求 · 新建 List 需等待 Nitter 收录」。创建时间较短的 List 需要过段时间才会被 Nitter 搜索到；配置里 `watch_lists` 也有同样提示。

### 3. List 成员上限

- 单个 List 最多可添加 **5000 个账号**
- 每个 Twitter 账号最多可创建 **1000 个 List**

### 4. 推送频率控制

List 聚合多人推文，可能产生大量更新。建议：
- 设置 `max_tweets_per_check`（如 10-20）
- 适当拉长检查间隔（如 30-60 分钟）
- 或拆分为多个小 List，分别订阅

### 5. 成员变更非实时

List 成员的增删改会有缓存延迟，Nitter 通常需要 5-10 分钟才能看到变更。

### 6. 首次启用不推历史

首次启用 List 订阅时，插件会记录当前扫描到的最多 20 个有效推文 ID 作为基线，**不会推送历史内容**。下次检查时才会推送新增推文。

## 转发过滤行为

List 订阅使用全局与分组双层开关：

- 全局 `basic.filter_reposts_enabled: true` 且分组 `filter_reposts_enabled: true`：过滤转发
- 任一开关为 `false`：保留转发

两个开关默认都开启；旧 List 分组缺少子开关时按开启处理。全局关闭时，分组不能单独强制开启过滤。

这与博主订阅行为一致，便于统一管理。

## 故障排查

### List 抓取失败

**现象**：后台日志显示 `list {id} failed on all hosts`

**排查步骤**：
1. 确认 List ID 是否正确（正整数纯数字，不要填写完整 URL）
2. 确认 List 是否设置为 **Public**
3. 检查 `instances`（List 走自建实例的 HTML 页面）是否可用
4. 使用 `/镜像测试` 验证实例可达性
优先查看结构化任务摘要中的 `生效实例`、`轮换轨迹`、`抓取状态`、`水位状态`、`推文统计`、`推送结果` 与 `失败详情`。它们分别表示最终生效实例、轮换尝试与状态码、抓取与基准状态、水位更新情况、新推文/过滤统计、目标推送结果以及失败/告警原因。

### List 无新推文推送

**现象**：后台检查正常，但没有推送

**排查步骤**：
1. 确认 List 成员是否有新推文（在 Twitter/X 上查看）
2. 检查 `filter_plain_text_enabled` 是否过滤了纯文本推文
3. 检查 `filter_reposts_enabled` 是否过滤了转发
4. 查看后台日志中“推文统计”的扫描与过滤条数
5. 检查是否出现“扫描未完整，自动重建基准”或“自动重建基准未完成”；如频繁重建，可适当提高 `html_max_pages` 或缩短检查间隔
6. 使用 `/推文状态` 查看分组检查状态

Dashboard 的“镜像测试”会一次测试用户 RSS、用户 HTML、搜索和可选 List，可直接验证 List 使用的 `instances`；填写 List ID 后会单独返回 List 检查结果。镜像 URL 留空会按配置顺序串行测试全部自建实例，返回每站推文数、耗时和错误。填写 URL 时只测试指定站点。HTTP 403、429、异常页或超时属于实例可用性问题，不要仅凭一次空结果判定 List ID 错误。

### List ID 无效

**现象**：配置保存后分组显示 `invalid_entries`

**原因**：List ID 包含非数字字符、为 `0`，或超过正 `uint64` 上限

**解决**：
- 只填写纯数字部分，不要包含 URL 前缀
- 数值范围为 `1` 至 `18446744073709551615`
- 正确：`1553232306718257152`
- 错误：`https://x.com/i/lists/1553232306718257152`

## 与标签分组的对比

| 特性 | 标签分组 (`tag`) | 列表分组 (`list`) |
|------|------------------|-------------------|
| 订阅对象 | 标签/关键词 | Twitter List（账号聚合） |
| 配置字段 | `watch_queries` | `watch_lists` |
| 内容来源 | 全平台公开推文 | List 成员的推文 |
| 首次订阅 | 记录基线，不推历史 | 记录基线，不推历史 |
| 转发过滤 | 全局总开关 + 分组子开关 | 全局总开关 + 分组子开关 |
| 抓取实例 | `instances` | `instances` |

## 最佳实践

### 1. 按主题分类

为不同主题创建多个 List 和分组：

```yaml
tweet_groups:
  - name: 科技资讯
    group_type: list
    watch_lists: ["1553232306718257152"]
    max_tweets_per_check: 15

  - name: 开源项目
    group_type: list
    watch_lists: ["2081623084780671084"]
    max_tweets_per_check: 10
```

### 2. 控制推送频率

List 聚合多人，建议：
- 拉长检查间隔（30-60 分钟）
- 限制单次推送数（10-20 条）
- 开启纯文本过滤（只推媒体内容）

```yaml
max_tweets_per_check: 10
filter_plain_text_enabled: true
interval_check_enabled: true  # 全局间隔 30 分钟
daily_check_times: []  # 不使用定点检查
```

### 3. 媒体专用频道

打造纯图片/视频推送频道：

```yaml
media_only_enabled: true
filter_plain_text_enabled: true
max_tweets_per_check: 20
```

### 4. 自建 Nitter 实例

订阅 List 前必须先配置自建 Nitter：

```yaml
instances:
  - "https://your-nitter.example.com"
```

## 示例配置

### 完整 List 分组配置

```yaml
tweet_groups:
  - name: 我关注的开发者
    group_id: dev_follows
    group_type: list
    enabled: true

    # List 订阅
    watch_lists:
      - "1553232306718257152"
      - "2081623084780671084"

    # 推送目标
    push_targets:
      - "aiocqhttp:GroupMessage:123456"

    # 检查调度
    interval_check_enabled: true
    daily_check_times: []

    # 内容过滤
    filter_reposts_enabled: true
    filter_plain_text_enabled: false
    media_only_enabled: false

    # 推送控制
    max_tweets_per_check: 10

    # 链接与翻译
    omit_status_url: true
    hide_original_when_translated: false
```

## 相关命令

目前 List 订阅**不支持手动命令导入**，只能通过配置文件或 WebUI 管理。

手动检查（如果当前会话在分组的 `push_targets` 中）：

```
/推文检查 我关注的开发者
```

查看分组状态：

```
/推文状态
```

## 参考链接

- [Twitter List 帮助文档](https://help.twitter.com/en/using-twitter/twitter-lists)
- [Nitter 项目](https://github.com/zedeus/nitter)
- [插件仓库](https://github.com/shitianyaa/astrbot_plugin_nitter_tweets)
