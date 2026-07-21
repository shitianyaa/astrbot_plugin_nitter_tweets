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
telegram:FriendMessage:123456789
lark:GroupMessage:oc_xxxxxxxxx
weixin_oc:FriendMessage:wxid_xxx
```

推送目标必须使用 `/sid` 返回的完整 UMO。

## 平台适配器

| 平台 | 适配器 | 文件 | 行为 |
| --- | --- | --- | --- |
| OneBot/QQ | `OneBotDeliveryAdapter` | `delivery/onebot.py` | 支持 Node/Nodes 合并转发、raw forward、图片拆分、视频降级 |
| Lark/Feishu | `LarkDeliveryAdapter` | `delivery/lark.py` | 优先 native post，同框发送正文和图片，失败降级 |
| Telegram | `TelegramDeliveryAdapter` | `delivery/telegram.py` | 使用默认发送链路，额外处理 flood control retry |
| 其他平台 | `DefaultDeliveryAdapter` | `delivery/default.py` | 使用 AstrBot `MessageChain` 普通发送 |

平台识别逻辑在 `delivery/platforms.py`：
- `ONEBOT_PLATFORM_TYPES`: OneBot-like 类型。
- `NON_ONEBOT_PLATFORM_TYPES`: 明确不是 OneBot 的平台。
- `LARK_PLATFORM_TYPES`: Lark/Feishu。
- `TELEGRAM_PLATFORM_TYPES`: Telegram。
- `PlatformProfile.is_onebot`: 有 OneBot 类型，或存在 `call_action` 且不是已知非 OneBot。

## OneBot/QQ

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
- 合并失败时尝试去视频重试。
- 不确定送达错误按可能已送达处理，避免重复推送。

测试入口：
- `tests/test_scheduler_delivery.py::test_ordinary_targets_send_per_account_but_qq_merges_at_end`

## Lark/Feishu

规则：
- 优先调用 `send_lark_post()`。
- post 可同框发送正文和本地图片。
- post 失败时降级为文本和普通媒体附件。
- 视频走普通媒体发送或按默认降级。
- 客户端解析在 `delivery/lark_support.py`，不要在业务层直接猜 client 字段。

测试入口：
- `tests/test_subscription_import.py::test_lark_title_uses_manual_header_override`

## Telegram

规则：
- 使用默认 MessageChain 发送。
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

## 渲染边界

`rendering/tweets.py` 负责输出：
- 普通 MessageChain components。
- OneBot raw nodes。
- 合并转发标题。
- 视频省略提示。
- 纯文本 fallback。

新增平台时优先新增/调整 `delivery/` adapter，不要在 `rendering/tweets.py` 写平台发送逻辑。

## 修改发送逻辑检查

- 是否通过 `PlatformResolver` 获取平台能力。
- 是否保留 Event 和 UMO 两条发送路径。
- 是否保留不确定送达保护。
- 是否保留 QQ/OneBot 图片独立消息或独立节点行为。
- 是否保留视频失败后的去视频重试或文本 fallback。
- 是否保留 Lark post 降级。
- 是否补对应平台测试。
