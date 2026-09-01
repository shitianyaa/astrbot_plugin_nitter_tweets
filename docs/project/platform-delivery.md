# 平台发送指南

开发或修改发送逻辑时先读本文件，再读 `delivery/sender.py`、`delivery/` 和 `rendering/tweets.py`。

## 入口

- `TweetSender.send(event, username, instance, tweets, ...)`: 手动命令当前会话。
- `TweetSender.send_to_umo(context, umo, username, instance, tweets, ...)`: 后台推送单账号。
- `TweetSender.send_merged_to_umo(context, umo, batches, ...)`: 后台推送多账号合并摘要。
- `TweetSender.send_summary_to_umo(context, umo, summary)`: 无更新或结果摘要。

平台选择统一通过：

```python
profile = PlatformResolver().from_umo(context, umo)
adapter = PlatformDeliveryRegistry().adapter_for(sender, profile)
```

不要只按 UMO 第一段判断平台类型。UMO 第一段是 AstrBot 平台实例 ID，不一定等于平台类型。

## UMO

格式：

```text
platform_id:MessageType:session_id
```

示例：

```text
aiocqhttp:GroupMessage:123456
qq_official:GroupMessage:group-openid
telegram:FriendMessage:123456789
lark:GroupMessage:oc_xxxxxxxxx
weixin_oc:FriendMessage:wxid_xxx
```

推送目标必须使用 `/sid` 返回的完整 UMO。

## 平台适配器

| 平台 | 适配器 | 文件 | 行为 |
| --- | --- | --- | --- |
| 私人号 OneBot | `OneBotDeliveryAdapter` | `delivery/onebot.py` | `aiocqhttp`、`onebot`、`onebot_v11`、`napcat` 支持 Node/Nodes 合并转发、raw forward、图片拆分、视频降级 |
| QQ Official | `QQOfficialDeliveryAdapter` | `delivery/qq_official.py` | 正文 Event/UMO 使用安全转义的官方 Markdown；媒体独立发送，Markdown 被拒时 UMO 降级为纯文本，不使用 OneBot 合并转发 |
| Lark/Feishu | `LarkDeliveryAdapter` | `delivery/lark.py` | 优先 native post，同框发送正文和图片，失败降级 |
| Telegram | `TelegramDeliveryAdapter` | `delivery/telegram.py` | 使用专用发送链路关闭文本中的网页预览，保留可点击链接；额外处理 flood control retry |
| 其他平台 | `DefaultDeliveryAdapter` | `delivery/default.py` | 使用 AstrBot `MessageChain` 普通发送 |

平台识别逻辑在 `delivery/platforms.py`：
- `PRIVATE_QQ_PLATFORM_TYPES`: 私人号 OneBot 类型（`aiocqhttp`、`onebot`、`onebot_v11`、`napcat`）。
- `QQ_OFFICIAL_PLATFORM_TYPES`: 官方 Bot 类型及窄义兼容别名（`qq_official`、`qq_official_webhook`、`qqofficial`、`qqofficial_webhook`）。
- `LEGACY_QQ_MEDIA_PLATFORM_TYPES`: 历史通用 `qq` 实例 ID，只保留直发媒体拆分，不作为 QQ Official 判定依据。
- `QQ_DIRECT_MEDIA_SPLIT_TYPES`: 私人号 OneBot、QQ Official 和历史 `qq` 实例都需要直发媒体拆分。
- `NON_ONEBOT_PLATFORM_TYPES`: 明确不是 OneBot 的平台。
- `LARK_PLATFORM_TYPES`: Lark/Feishu。
- `TELEGRAM_PLATFORM_TYPES`: Telegram。
- `PlatformProfile.is_qq_official`: 命中官方 Bot 类型。
- `PlatformProfile.is_onebot`: 命中私人号 OneBot 类型，或存在 `call_action` 且不是已知非 OneBot；官方 Bot 会显式排除。
- 已解析到平台实例时，metadata/config 类型优先于 UMO 第一段的实例 ID；只有无类型信息时才用实例 ID 兜底。

## 私人号 OneBot

触发合并转发：

```python
sender._should_use_merge_for_count(tweet_count)
```

规则：
- `merge_tweet_threshold=0` 关闭合并。
- 达到阈值且目标支持 merged forward 时使用合并。
- 单次合并过大时按 chunk 分批。
- 图片附件从正文中拆出；普通直发先发正文再逐张发图，合并转发中图片成为独立节点。
- 合并中有视频时优先 raw OneBot 节点。
- raw 合并转发因非 payload 拒绝的原因失败时，先换传输编码重建整份节点数组重试，再考虑拆分或去视频。
- 合并失败时尝试去视频重试。
- 不确定送达错误按可能已送达处理，避免重复推送。
- 直发媒体在梯度不止一档时改走 `call_action` 原始消息段，以取得 `file` 字段的控制权；取不到 `call_action` 时回落到原有组件链。
- `media_only_enabled` 有效时每个推文节点只保留作者和附件；附件节点不重复输出正文或链接，失败降级也不能泄漏完整内容。

测试入口：
- `tests/test_scheduler_delivery.py::test_ordinary_targets_send_per_account_but_qq_merges_at_end`
- `tests/test_media_transport.py`

## 媒体传输编码

媒体默认以本地文件路径交给平台（直发用 `Image/Video.fromFileSystem`，OneBot 合并转发节点用
`file:///` URI）。这隐含假设 AstrBot 与协议端共享文件系统；分容器或分机器部署时协议端读不到该路径。

`delivery/media_transport.py` 提供一条**无损**的编码降级梯度，`delivery/sender_transport.py`
负责执行：

- **顺序不变量**：传输降级（换编码，无损）必须跑在内容降级（丢视频、退纯文本，有损）之前。
  路径档失败先换 base64 重试，成功则视频从未被丢弃。
- 编码档：`path` / `base64` / `url` / `skip`。`skip` 只有视频有，复用既有的
  `TweetMessageRenderer.video_not_sent_notice`；图片没有对应文案，失败交给内容降级链。
- `base64` 档受 `media_transport_base64_max_mb` 单文件上限约束，同一个数字同时管住图片和视频。
- `url` 档需要 `media_transport_url_fallback=true` 且主机在 twimg 白名单内；xdown 直链带 token、
  时效短且对 Referer 敏感，永不交给协议端。
- `uncertain`（超时）**不推进梯度**，否则会重复投递。
- `TransportMemo` 记住每个平台最近一次成功的档作为下次起步提示；失败时仍会回落到更早的档。

**作用域只有 OneBot。** 其余适配器的 `media_transport_ladder` 恒为 `(path,)`：它们都在 AstrBot
进程内从本地路径上传，Lark 甚至会把组件反解回 `Path` 再读字节
（`delivery/lark_support.py` 的 `_local_image_path` 明确跳过 `base64://` 和 `http(s)://`），
换编码会直接打断它。

渲染层不 import `delivery/`：`build_onebot_nodes` / `build_merged_onebot_nodes_for_uin` /
`raw_media` 接受一个可选的 `segment_builder` 回调，由发送层注入编码。

## QQ Official

规则：
- 需要 AstrBot `>=4.26.0`。
- `qq_official` 和 `qq_official_webhook` 走 `QQOfficialDeliveryAdapter`；Event 和媒体沿 AstrBot 公共 `MessageChain`，UMO 正文在 client 可用时直驱 botpy 官方接口。AstrBot 的 webhook 事件类继承自 WebSocket 事件类且未覆写发送逻辑，两者共用同一条投递路径。
- 文本 Event 使用 `MessageChain.use_markdown(True)`，UMO 正文通过平台实例的 botpy client 调用官方 `post_group_message` / `post_c2c_message`，使用 `msg_type=2`、`markdown.content` 和主动消息 `msg_seq`；正文中的用户内容会转义 Markdown 特殊字符，原推链接放在作者头部。
- UMO Markdown 被 QQ 拒绝时，适配器用同一官方接口改发 `msg_type=0` + `content` 纯文本；取不到 botpy client 时也走不泄漏 Markdown 标记的纯文本公共路径。
- 带媒体时先发正文，再逐张发送图片和视频；Markdown 与 `media` 不混在同一条消息中。正文成功但媒体失败时保留“部分送达”状态。
- 不使用 `Node/Nodes`、raw forward 或 OneBot action；媒体上传和附件发送仍由 AstrBot 官方适配器负责。
- `merge_tweet_threshold` 只对私人号 OneBot 生效。
- Markdown 正文主动发送直接使用 UMO 中的 `group_openid` / `openid`，不依赖上游 `_session_scene` 或 `_session_last_message_id` 缓存；媒体附件仍遵循 AstrBot 适配器的上传能力和平台限制。

测试入口：
- `tests/test_qq_official_delivery.py`

## Lark/Feishu

规则：
- 优先调用 `send_lark_post()`。
- post 可同框发送正文和本地图片。
- post 失败时降级为文本和普通媒体附件。
- 视频走普通媒体发送或按默认降级。
- 仅媒体模式的 post 标题只保留作者，图片随 post 发送，视频继续走独立媒体路径。
- 客户端解析在 `delivery/lark_support.py`，不要在业务层直接猜 client 字段。

测试入口：
- `tests/test_subscription_import.py::test_lark_title_uses_manual_header_override`

## Telegram

规则：
- 通过 AstrBot Telegram 发送器发送 MessageChain，并为文本中的 X/Twitter 链接关闭网页预览，避免视频推文卡片重复显示作者和播放器文案；链接仍可点击。
- flood control 错误由 `TelegramDeliveryAdapter.retry_after_flood_control()` 处理。
- retry 成功不再走 fallback。
- retry 失败返回失败结果，避免重复发送不可控。

测试入口：
- `tests/test_scheduler_delivery.py::test_telegram_flood_control_waits_and_retries_same_message`
- `tests/test_scheduler_delivery.py::test_telegram_flood_control_retry_failure_skips_fallback`

## weixin_oc 和其他平台

规则：
- 走 `DefaultDeliveryAdapter`。
- 不使用 OneBot 合并转发。
- 媒体是否成功取决于 AstrBot 平台适配器能力。
- 发送失败时回退到纯文本内容。
- 仅媒体模式的纯文本回退只允许作者标记，不允许正文、翻译或原帖链接。

## 渲染边界

`rendering/tweets.py` 负责输出：
- 普通 MessageChain components。
- OneBot raw nodes。
- 合并转发标题。
- 视频省略提示。
- 纯文本 fallback。

新增平台时优先新增/调整 `delivery/` adapter，不要在 `rendering/tweets.py` 写平台发送逻辑。
传输编码同理：渲染层只接受注入的 `segment_builder`，不自己决定编码。

## 修改发送逻辑检查

- 是否通过 `PlatformResolver` 获取平台能力。
- 是否保留 Event 和 UMO 两条发送路径。
- 是否保留不确定送达保护。
- 是否保留私人号 OneBot 图片独立消息或独立节点行为。
- 是否保留视频失败后的去视频重试或文本 fallback。
- **是否保留传输降级排在内容降级之前的顺序**，以及 `uncertain` 不推进梯度。
- 是否保留 Lark post 降级，且 Lark 仍拿到文件系统路径而不是 base64。
- 是否补对应平台测试。
