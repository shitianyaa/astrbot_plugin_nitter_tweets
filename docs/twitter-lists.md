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

### 2. 获取 List ID

List ID 是一串纯数字（15-20 位），从 List 的 URL 中获取：

```
https://x.com/i/lists/1553232306718257152
                       ^^^^^^^^^^^^^^^^^^^^
                       这就是 List ID
```

**如何获取**：
- 网页版：打开 List 页面，从浏览器地址栏复制数字部分
- App：分享 List → 复制链接 → 提取数字部分

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
    max_tweets_per_check: 10  # 强烈建议设置
    scheduled_fetch_limit: 20  # 每次抓取最多解析 20 条
```

## 重要配置项说明

### `max_tweets_per_check`（必设）

List 聚合多人推文，可能在短时间内产生大量更新。**强烈建议设置此项**（如 10-20），避免一次推送过多消息刷屏。

```yaml
max_tweets_per_check: 10  # 每个 List 单次检查最多推送 10 条
```

### `scheduled_fetch_limit`

每次从 Nitter 抓取页面最多解析多少条，默认 20。

```yaml
scheduled_fetch_limit: 20  # 适中即可，不建议设太大
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
过滤转发（跟随全局 filter_reposts_enabled）
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

新创建的 List 可能需要 10-30 分钟才能被 Nitter 镜像索引到，建议等待一段时间后再配置订阅。

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

首次启用 List 订阅时，插件只会记录当前最新推文作为基线，**不会推送历史内容**。下次检查时才会推送新增推文。

## 转发过滤行为

List 订阅的转发过滤行为**跟随全局配置** `filter_reposts_enabled`：

- `filter_reposts_enabled: true`：List 推送会过滤转发
- `filter_reposts_enabled: false`（默认）：List 推送包含转发

这与博主订阅行为一致，便于统一管理。

## 故障排查

### List 抓取失败

**现象**：后台日志显示 `list {id} failed on all hosts`

**排查步骤**：
1. 确认 List ID 是否正确（纯数字，15-20 位）
2. 确认 List 是否设置为 **Public**
3. 检查 `search_instances`（List 走 HTML 搜索实例）是否可用
4. 使用 `/镜像测试` 验证实例可达性
5. 查看是否触发 Nitter 限流（429 错误）

### List 无新推文推送

**现象**：后台检查正常，但没有推送

**排查步骤**：
1. 确认 List 成员是否有新推文（在 Twitter/X 上查看）
2. 检查 `filter_plain_text_enabled` 是否过滤了纯文本推文
3. 检查 `filter_reposts_enabled` 是否过滤了转发
4. 查看后台日志中的 `raw_item_count` / `retweet_filtered` 统计
5. 使用 `/推文状态` 查看分组检查状态

### List ID 无效

**现象**：配置保存后分组显示 `invalid_entries`

**原因**：List ID 格式错误（包含非数字字符）

**解决**：
- 只填写纯数字部分，不要包含 URL 前缀
- 正确：`1553232306718257152`
- 错误：`https://x.com/i/lists/1553232306718257152`

## 与标签分组的对比

| 特性 | 标签分组 (`tag`) | 列表分组 (`list`) |
|------|------------------|-------------------|
| 订阅对象 | 标签/关键词 | Twitter List（账号聚合） |
| 配置字段 | `watch_queries` | `watch_lists` |
| 内容来源 | 全平台公开推文 | List 成员的推文 |
| 首次订阅 | 记录基线，不推历史 | 记录基线，不推历史 |
| 转发过滤 | 跟随全局配置 | 跟随全局配置 |
| 抓取实例 | `search_instances` | `search_instances` |
| 风险提示 | 私人 QQ 号不建议 | 私人 QQ 号不建议 |

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

如果订阅大量 List，建议自建 Nitter 镜像，避免公共实例限流：

```yaml
search_instances:
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
    filter_plain_text_enabled: false
    media_only_enabled: false
    
    # 推送控制
    max_tweets_per_check: 10
    scheduled_fetch_limit: 20
    
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
