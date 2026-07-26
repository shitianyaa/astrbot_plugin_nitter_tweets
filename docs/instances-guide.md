# Nitter 实例配置指南

本文档详细说明插件的 RSS vs HTML 双路架构、默认实例配置、回退机制和最佳实践。

- 返回 [README](../README.md)
- 查看 [进阶说明](./advanced.md)

---

## RSS vs HTML 双路架构

插件采用**功能分离**的设计，针对不同场景使用不同的 Nitter 接口：

### 架构对比

| 场景 | 接口类型 | 路径 | 默认实例 | 配置项 |
|------|---------|------|---------|--------|
| **博主订阅** | RSS | `/username/rss` | `nitter.net` | `instances` |
| **标签搜索** | HTML | `/search?q=%23tag` | `tiekoetter.com`<br>`poast.org`<br>`kareem.one` | `search_instances` |

### 为什么分离？

**RSS 路径（博主订阅）：**
- ✅ `nitter.net` 的 RSS 非常稳定
- ✅ XML 解析简单可靠
- ✅ 适合定时轮询
- ❌ **不支持搜索**（只能获取用户时间线）
- ❌ `nitter.net` 的 HTML 搜索已不可用（返回 200 空 body）

**HTML 路径（标签搜索）：**
- ✅ 支持标签和短语搜索
- ✅ 3 个实例冗余（容错能力强）
- ✅ 自动门禁解算（Anubis PoW、Poast SHA1）
- ❌ 需要解析 HTML（比 RSS 复杂）
- ❌ 部分实例 RSS 路径返回 403

**分离的好处：**
1. **避免资源冲突** - 博主订阅和搜索不会抢同一个实例
2. **降低限流风险** - 定时博主轮询不占用搜索配额
3. **独立冷却机制** - `cooldown_seconds` 和 `search_cooldown_seconds` 分别控制
4. **错误信息清晰** - RSS 失败不会误报搜索问题

---

## 默认实例配置

### 博主 RSS（`instances`）

```json
{
  "instances": ["https://nitter.net"]
}
```

**特点：**
- 单实例，稳定性高
- 仅支持 `/username/rss` 路径
- **不要用于搜索**（搜索返回空）

**推荐自建：**
```json
{
  "instances": [
    "https://your-nitter.example.com",
    "https://nitter.net"  // 保留官方作为回退
  ]
}
```

---

### 标签搜索 HTML（`search_instances`）

```json
{
  "search_instances": [
    "https://nitter.tiekoetter.com",  // Anubis PoW 门禁
    "https://nitter.poast.org",       // Poast SHA1 门禁
    "https://nitter.kareem.one"       // 轻量门禁
  ]
}
```

**特点：**
- 3x 实例冗余
- CF 实验验证通过
- 自动门禁解算
- **不要添加 `nitter.net`**（它的搜索已不可用）

**门禁类型说明：**

| 实例 | 门禁类型 | 解算时间 | 说明 |
|------|---------|---------|------|
| `tiekoetter.com` | Anubis PoW | ~10-100ms | 基于 SHA256 工作量证明 |
| `poast.org` | Poast SHA1 | ~5-50ms | 基于 SHA1 迭代验证 |
| `kareem.one` | 轻量门禁 | <5ms | 简单验证或无门禁 |

插件会自动检测并解算这些门禁，用户无需手动操作。

---

## RSS 博主回退机制

### 配置项

**`user_html_fallback`**（默认 `false`，WebUI 不可见）

### 行为说明

当所有 `instances` 中的 RSS 镜像都失败时：

**默认行为（`user_html_fallback: false`）：**
```
1. 尝试 instances[0] → 失败
2. 尝试 instances[1] → 失败
3. 尝试 instances[2] → 失败
4. 报错：RSS 轮换失败: username=NASA, tried=3, errors=...
5. ✅ 不会自动切换到 search_instances
```

**回退行为（`user_html_fallback: true`，不推荐）：**
```
1. 尝试所有 instances → 全部失败
2. ⚠️ 回退到 search_instances
3. 尝试 HTML /username 路径
4. 成功则返回结果
```

### 为什么不推荐开启回退？

| 问题 | 影响 |
|------|------|
| **占用搜索资源** | 博主订阅会消耗搜索实例配额 |
| **增加 429 风险** | 定时轮询 + 搜索查询 = 更容易触发限流 |
| **降低搜索成功率** | 博主回退占用可能导致真正的搜索失败 |
| **错误信息混淆** | 难以区分是 RSS 问题还是搜索问题 |

### 何时可以临时开启？

**仅在以下情况下考虑：**
1. ✅ 你的 `instances` 完全不可用（所有 RSS 镜像都挂了）
2. ✅ 你需要紧急获取博主推文
3. ✅ 你的 `search_instances` 有足够的配额（自建或低频使用）
4. ✅ 你理解这只是临时应急方案

**开启后尽快：**
1. 修复或更换 `instances` 中的 RSS 镜像
2. 关闭 `user_html_fallback`
3. 监控 `search_instances` 的 429 限流情况

---

## 容错机制

### 实例轮换

**单个实例失败 → 自动尝试下一个：**
```
instances: ["A", "B", "C"]

尝试顺序:
1. A → 失败（429 限流）
2. B → 失败（超时）
3. C → 成功 ✅
```

**冷却机制：**
```
实例 A 返回 429:
1. 记录冷却时间（默认 60 秒）
2. 60 秒内跳过实例 A
3. 优先使用 B、C
4. 60 秒后 A 恢复可用
```

**健康度评分：**
```
每个实例有内存评分:
- 成功返回结果 → +100 分
- 返回空结果 → +50 分（软成功）
- 失败 → -20 分

选择实例时优先使用高分实例
```

---

### 全局重试机制

**当所有实例都失败时：**

```
第 1 轮尝试:
  A → 失败
  B → 失败
  C → 失败

延迟 5 秒

第 2 轮尝试:
  A → 失败
  B → 成功 ✅ → 返回结果
  
(如果第 2 轮也失败，延迟 10 秒继续第 3 轮)
```

**配置项：**

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `max_global_retries` | `2` | 最多重试轮数 |
| `retry_delay_base` | `5.0` | 基础延迟（秒） |
| `retry_delay_on_cooldown` | `10.0` | 全部冷却时的延迟（秒） |

**渐进式延迟：**
```
重试 1: 延迟 5s  (1 × retry_delay_base)
重试 2: 延迟 10s (2 × retry_delay_base)
重试 3: 延迟 15s (3 × retry_delay_base)
```

**智能跳过：**
- ✅ 验证错误（ValueError）不触发重试
- ✅ Probe 模式（`/镜像测试`）不触发重试
- ✅ 运行时故障才重试

---

## 错误提示对照表

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| `未配置 Nitter 实例` | `instances` 或 `search_instances` 为空 | 检查配置，添加至少一个实例 |
| `本轮所有 Nitter 实例均不可用（已跳过 3 个实例）` | 所有实例都在冷却或全部失败 | 等待冷却结束，或检查实例可用性 |
| `RSS 轮换失败: username=NASA, tried=3, errors=...` | 所有 RSS 实例都失败 | 检查 `instances` 可用性，考虑添加更多镜像 |
| `HTML search failed after 2 retries` | 搜索实例全部失败且重试耗尽 | 检查 `search_instances` 可用性，稍后重试 |
| `all instances in cooldown` | 所有实例都被限流 | 等待冷却结束（默认 60 秒） |

---

## 最佳实践

### 1. 生产环境配置

**博主订阅（RSS）：**
```json
{
  "instances": [
    "https://your-primary-nitter.example.com",
    "https://your-backup-nitter.example.com",
    "https://nitter.net"
  ],
  "user_html_fallback": false
}
```

**标签搜索（HTML）：**
```json
{
  "search_instances": [
    "https://your-search-nitter.example.com",
    "https://nitter.tiekoetter.com",
    "https://nitter.poast.org",
    "https://nitter.kareem.one"
  ]
}
```

---

### 2. 自建实例优先

**为什么要自建？**
- ✅ 无限流风险
- ✅ 稳定性可控
- ✅ 可自定义配置
- ✅ 不受公共实例状态影响

**自建后配置：**
```json
{
  "instances": [
    "https://your-nitter.example.com"  // 自建优先
  ],
  "search_instances": [
    "https://your-nitter.example.com",  // 自建优先
    "https://nitter.tiekoetter.com"    // 公共镜像作为回退
  ]
}
```

---

### 3. 监控与诊断

**使用 `/镜像测试` 验证实例：**
```bash
# 测试 RSS 路径
/镜像测试 nasa 5 https://nitter.net

# 测试自建实例
/镜像测试 nasa 5 https://your-nitter.example.com
```

**日志关键字：**
```
# 成功
[NitterTweets] RSS fetch ok: instance=nitter.net, username=NASA, tweets=5

# 冷却
[NitterTweets] defer cooling nitter.net remain=45s

# 失败
[NitterTweets] RSS 轮换失败: username=NASA, tried=3, errors=[...]

# HTML 搜索成功
[NitterTweets][html] search ok host=poast.org query=#NASA

# HTML 门禁解算
[NitterTweets][html] anubis: solved challenge=abc123 in 45ms
```

---

### 4. 不要混用路径

**❌ 错误配置：**
```json
{
  "instances": ["https://nitter.tiekoetter.com"],  // 这个实例的 RSS 返回 403
  "search_instances": ["https://nitter.net"]       // 这个实例的搜索返回空
}
```

**✅ 正确配置：**
```json
{
  "instances": ["https://nitter.net"],             // RSS 专用
  "search_instances": [                            // 搜索专用
    "https://nitter.tiekoetter.com",
    "https://nitter.poast.org"
  ]
}
```

---

## 常见问题

### Q: 为什么不用同一个实例列表？

**A:** 因为不同实例对 RSS 和搜索的支持情况不同：
- `nitter.net`: RSS ✅ / 搜索 ❌
- `tiekoetter/poast/kareem`: RSS ❌ / 搜索 ✅

分离配置确保每个功能都用对应的可用实例。

---

### Q: 我的 RSS 实例全挂了怎么办？

**A:** 三种方案（按推荐顺序）：
1. **最佳方案：** 添加自建 Nitter 实例到 `instances`
2. **临时方案：** 添加其他公共 RSS 镜像（需验证可用性）
3. **应急方案：** 临时开启 `user_html_fallback`，但尽快修复 RSS

---

### Q: 搜索总是返回 429 怎么办？

**A:** 
1. 检查是否频繁搜索（触发限流）
2. 增加 `search_cooldown_seconds`（默认 120 秒）
3. 添加更多 `search_instances`（分散负载）
4. 考虑自建实例（无限流）
5. 确认没有开启 `user_html_fallback`（避免博主占用搜索配额）

---

### Q: 全局重试会让请求变慢吗？

**A:** 
- **正常情况：** 不会。第一轮就成功，无延迟。
- **全部失败时：** 会增加 5-15 秒延迟，但提升了成功率。
- **权衡：** 可靠性 > 响应时间（偶尔慢一点，但成功率高 3 倍）

---

### Q: 我可以只用一个实例吗？

**A:** 可以，但不推荐：
- ✅ 适合：自建实例（稳定性自己控制）
- ❌ 不适合：公共实例（随时可能失效或限流）

建议至少配置 2-3 个实例作为回退。

---

## 相关文档

- [README](../README.md) - 快速开始
- [进阶说明](./advanced.md) - 完整配置参考
- [_conf_schema.json](../_conf_schema.json) - 配置默认值

---

## 更新日志

- **2026-07-27** - 添加全局重试机制和 3 镜像默认配置
- **2026-07-23** - 初始版本，分离 RSS 和 HTML 架构
