# ytdlp-downloader 分支 — 核心逻辑分析

> 记录于 2026-06-12，分支 `ytdlp-downloader` 相对于 `main` 的核心变更分析。

---

## 1. 转帖过滤 (`deduplicate_retweets`)

### 文件位置

- `media.py` → `NitterClient._parse_rss()` 第 865 行
- `utils.py` → `TweetItem.username` property 第 52-57 行

### 判断逻辑

```
RSS <link> 中提取的 tweet.username != 当前抓取 username → 判定为转帖 → 跳过
```

### 数据流

```
Nitter RSS <item>
  └─ <link> → normalize → TweetItem.link
       └─ urlparse(link).path.split("/") → 取 /status/ 前第一段 → 去 @ 前缀 → tweet.username
            └─ lowercase 比较 → 与请求的 username 不同 → 跳过
```

### 边界处理

| 场景 | 行为 | 机制 |
|------|------|------|
| link 不含 `/status/` | 不过滤 | `tweet.username` 返回空字符串，`and tweet.username` 短路 |
| username 大小写不一致 | 不过滤 | `.lower()` 比较 |
| `skip_retweets=False` | 全部保留 | 布尔短路 |

### 调用入口

| 场景 | skip_retweets 来源 |
|------|-------------------|
| 手动 `/推文` / `/镜像测试` | 全局配置 `deduplicate_retweets` |
| 定時推送 | 分组配置 `group.deduplicate_retweets`（独立于全局） |

---

## 2. 视频分辨率选择 (`preferred_video_resolution`)

### 文件位置

- `media.py` → `MediaService._resolve_media_urls()` 第 501-528 行
- `media.py` → `_extract_video_id()` 第 573-587 行
- `media.py` → `_parse_resolution()` 第 590-593 行
- `media.py` → `_select_resolution()` 第 595-619 行

### 处理流程

```
1. 遍历 xdown 解析结果
   ├─ kind != "video" → 直接加入 result
   └─ kind == "video" → 按 video_id 分组到 video_candidates dict
    
2. video_id 提取
   URL (JWT) → _decode_jwt_payload → 取 inner_url → urlparse → path
   → 定位 *_video/ 后的 tweet_id 段 → 返回 tweet_id 作为 video_id
   
3. 分辨率提取
   xdown 链接文字 text → re.search(r"(\d+)p", text) → 返回 int
   
4. 分辨率选择
   preferred_video_resolution 配置:
   ├─ "highest" / 空 → 取最高分辨率
   ├─ 指定值 (如 "720p") → 精确匹配 → 最近较低 → 最低兜底
   └─ candidates 空 → 返回 ""
```

### 关键数据结构

```
video_candidates: dict[str, list[tuple[int, str]]]
                              ^video_id   ^res   ^url
```

### 边界处理

| 场景 | 行为 |
|------|------|
| 分辨率文字不含 `\d+p` | `_parse_resolution` 返回 0，排序垫底 |
| JWT 解码失败 | `_decode_jwt_payload` 返回 `{}`，`inner_url` 为空 |
| 路径无 `_video` 段 | `_extract_video_id` 返回整个 path（同一条推文内无影响） |
| candidates 为空 | `_select_resolution` 返回 `""`，下载时异常兜底 |

---

## 3. 有视频时跳过所有图片

### 文件位置

- `media.py` → `MediaService._resolve_media_urls()` 第 497-516 行

### 逻辑

```python
has_video_candidate = any(
    kind in {"video", "dynamic"} for kind, _, _ in parser.items
)
if kind == "image" and has_video_candidate:
    continue  # skip
```

### 原理

Twitter/X **不允许单条推文同时包含图片和视频**。如果 xdown 解析出视频/GIF，该推文的所有图片必然是视频缩略图，全部跳过即可。

### 旧逻辑对比

| 旧逻辑 | 新逻辑 |
|--------|--------|
| `_same_media_url(full_url, cover_url)` 逐一比对封面 URL | 一次性全跳过 |
| 部分缩略图 URL 与封面不一致 → 漏过滤 | 彻底不过滤 |

### 死代码提醒

`_same_media_url()` 方法（`media.py` 第 532 行）现无人调用，可清理。

---

## 辅助方法

### `_decode_jwt_payload(url)` — 第 555 行

从 xdown 代理 URL 的 query 参数 `token` 中解码 JWT payload。

```
url?token=xxx.yyy.zzz → 取 yyy 段 → base64 decode → dict
```

### `_parse_resolution(text)` — 第 590 行

```python
re.search(r"(\d+)p", text)  # "下载 MP4 (720p)" → 720
```

---

## 涉及文件清单

| 文件 | 变更类型 |
|------|---------|
| `media.py` | 核心逻辑（转帖过滤、分辨率选择、图片跳过） |
| `main.py` | 手动命令适配（跳过计数显示） |
| `scheduler.py` | 定时推送适配（分组 deduplicate_retweets） |
| `scheduler_config.py` | 分组配置结构 |
| `_conf_schema.json` | 配置 schema（全局 + 分组独立） |
| `config_compat.py` | 配置分组映射 |
| `CHANGELOG.md` | 版本记录 |
| `README.md` | 文档更新 |
| `metadata.yaml` | 版本号 0.9.1 → 0.9.3 |
