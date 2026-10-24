from __future__ import annotations

import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def _ensure_astrbot_module(name: str) -> tuple[types.ModuleType, bool]:
    """Import the real astrbot module when importable, otherwise install a stub.

    Returns ``(module, is_stub)``. Fake classes are only assigned to stubs:
    patching a real AstrBot installation leaks into every later test module
    (e.g. ``command_handlers.manual`` binding the fake ``MessageChain``
    depending on collection order).
    """
    try:
        return importlib.import_module(name), False
    except Exception:
        stub = types.ModuleType(name)
        sys.modules[name] = stub
        return stub, True


astrbot_module, astrbot_is_stub = _ensure_astrbot_module("astrbot")
astrbot_api_module, astrbot_api_is_stub = _ensure_astrbot_module("astrbot.api")
astrbot_api_all_module, astrbot_api_all_is_stub = _ensure_astrbot_module(
    "astrbot.api.all"
)
astrbot_api_event_module, astrbot_api_event_is_stub = _ensure_astrbot_module(
    "astrbot.api.event"
)
astrbot_api_message_components_module, astrbot_api_message_components_is_stub = (
    _ensure_astrbot_module("astrbot.api.message_components")
)


class _Logger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _MessageChain:
    def __init__(self, components=None):
        self.components = components or []


class _Plain:
    def __init__(self, text=""):
        self.text = text


class _Image:
    @classmethod
    def fromFileSystem(cls, path):
        return cls()


class _Video:
    @classmethod
    def fromFileSystem(cls, path):
        return cls()


class _Node:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.uin = kwargs.get("uin")
        self.name = kwargs.get("name")
        self.content = kwargs.get("content", [])


class _Nodes:
    def __init__(self, *args, **kwargs):
        self.nodes = []


class _At:
    pass


class _Star:
    def __init__(self, context=None):
        self.context = context


class _Filter:
    class PermissionType:
        ADMIN = "admin"

    @staticmethod
    def command(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def command_group(*args, **kwargs):
        def decorator(func):
            func.command = _Filter.command
            return func

        return decorator

    @staticmethod
    def permission_type(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def on_astrbot_loaded():
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def regex(*args, **kwargs):
        def decorator(func):
            return func

        return decorator


def _register(*args, **kwargs):
    def decorator(cls):
        return cls

    return decorator


astrbot_api_star_module, astrbot_api_star_is_stub = _ensure_astrbot_module(
    "astrbot.api.star"
)
astrbot_core_command_module, astrbot_core_command_is_stub = _ensure_astrbot_module(
    "astrbot.core.star.filter.command"
)
astrbot_core_module, astrbot_core_is_stub = _ensure_astrbot_module("astrbot.core")
astrbot_core_message_module, astrbot_core_message_is_stub = _ensure_astrbot_module(
    "astrbot.core.message"
)
astrbot_core_message_components_module, astrbot_core_message_components_is_stub = (
    _ensure_astrbot_module("astrbot.core.message.components")
)


if astrbot_api_is_stub:
    astrbot_api_module.logger = _Logger()
if astrbot_api_all_is_stub:
    astrbot_api_all_module.At = _At
    astrbot_api_all_module.AstrBotConfig = dict
    astrbot_api_all_module.Context = object
    astrbot_api_all_module.MessageChain = _MessageChain
    astrbot_api_all_module.Plain = _Plain
    astrbot_api_all_module.Star = _Star
    astrbot_api_all_module.logger = getattr(astrbot_api_module, "logger", _Logger())
if astrbot_api_event_is_stub:
    astrbot_api_event_module.MessageChain = _MessageChain
    astrbot_api_event_module.AstrMessageEvent = object
    astrbot_api_event_module.filter = _Filter
if astrbot_api_message_components_is_stub:
    astrbot_api_message_components_module.Plain = _Plain
    astrbot_api_message_components_module.Image = _Image
    astrbot_api_message_components_module.Video = _Video
    astrbot_api_message_components_module.Node = _Node
    astrbot_api_message_components_module.Nodes = _Nodes
if astrbot_api_star_is_stub:
    astrbot_api_star_module.register = _register
if astrbot_core_command_is_stub:
    astrbot_core_command_module.GreedyStr = str
if astrbot_core_message_components_is_stub:
    astrbot_core_message_components_module.Image = _Image
    astrbot_core_message_components_module.Video = _Video
    astrbot_core_message_components_module.Node = _Node
    astrbot_core_message_components_module.Nodes = _Nodes
    astrbot_core_message_components_module.Plain = _Plain

if astrbot_api_message_components_is_stub and "rendering.tweets" in sys.modules:
    tweet_rendering_module = sys.modules["rendering.tweets"]
    tweet_rendering_module.Plain = _Plain
    tweet_rendering_module.Image = _Image
    tweet_rendering_module.Video = _Video
    tweet_rendering_module.Node = _Node
    tweet_rendering_module.Nodes = _Nodes


import delivery.telegram as telegram_delivery_module  # noqa: E402
import scheduler as scheduler_module  # noqa: E402
from delivery import DefaultDeliveryAdapter, TweetSender  # noqa: E402
from delivery.outcomes import SendAttempt, SendOutcome  # noqa: E402
from rendering import TweetMessageRenderer  # noqa: E402
from scheduler import NitterTweetScheduler  # noqa: E402
from shared import TweetItem, TweetMedia  # noqa: E402
from storage import (  # noqa: E402
    SQLiteStorage,
    StorageAdapter,
)


class _Owner:
    async def get_kv_data(self, key, default):
        return default


class _Nitter:
    def __init__(self):
        self.filter_reposts_calls = []
        self.tweets = [
            TweetItem(
                text="old",
                link="https://x.com/NASA/status/100",
                published="",
            ),
            TweetItem(
                text="new",
                link="https://x.com/NASA/status/101",
                published="",
            ),
        ]

    async def fetch_tweets(
        self,
        username,
        limit,
        skip_plain_text=False,
        filter_reposts=None,
    ):
        self.filter_reposts_calls.append(filter_reposts)
        return "https://nitter.test", self.tweets[:limit]

    async def fetch_tweets_with_stats(
        self,
        username,
        limit,
        skip_plain_text=False,
        filter_reposts=None,
    ):
        self.filter_reposts_calls.append(filter_reposts)
        return "https://nitter.test", self.tweets[:limit], 0


class _MultiUserNitter:
    def __init__(self, tweets_by_user, events=None):
        self.tweets_by_user = tweets_by_user
        self.events = events if events is not None else []
        self.concurrent_calls = []
        self.filter_reposts_calls = []

    async def fetch_tweets(
        self,
        username,
        limit,
        skip_plain_text=False,
        filter_reposts=None,
    ):
        self.filter_reposts_calls.append(filter_reposts)
        self.events.append(f"fetch:{username}")
        return "https://nitter.test", self.tweets_by_user.get(username, [])[:limit]

    async def fetch_tweets_with_stats(
        self,
        username,
        limit,
        skip_plain_text=False,
        filter_reposts=None,
    ):
        self.filter_reposts_calls.append(filter_reposts)
        self.events.append(f"fetch:{username}")
        return "https://nitter.test", self.tweets_by_user.get(username, [])[:limit], 0

    async def fetch_tweets_with_stats_from_instances(
        self,
        username,
        limit,
        instances,
        start_index=0,
        skip_plain_text=False,
        retry_attempts=3,
        filter_reposts=None,
    ):
        self.filter_reposts_calls.append(filter_reposts)
        self.concurrent_calls.append(
            (username, tuple(instances), start_index, skip_plain_text, retry_attempts)
        )
        self.events.append(f"concurrent_fetch:{username}")
        return (
            "https://concurrent.test",
            self.tweets_by_user.get(username, [])[:limit],
            0,
        )


class _SchedulerNitter:
    """Fake the dedicated scheduler scan API while preserving RSS ordering."""

    def __init__(self, scans_by_user):
        self.scans_by_user = {
            username: list(scans) for username, scans in scans_by_user.items()
        }
        self.calls = []
        self.filter_reposts_calls = []
        self.path_overrides = []

    async def fetch_tweets_for_scheduler(
        self,
        username,
        watermark,
        skip_plain_text=False,
        filter_reposts=None,
        **kwargs,
    ):
        del skip_plain_text
        self.filter_reposts_calls.append(filter_reposts)
        self.path_overrides.append(kwargs.get("path_override", ""))
        self.calls.append((username, watermark))
        scans = self.scans_by_user[username]
        scan = scans.pop(0) if len(scans) > 1 else scans[0]
        return (
            "https://scheduler.test",
            types.SimpleNamespace(
                tweets=list(scan.get("tweets", [])),
                scanned_status_ids=list(scan.get("scanned_status_ids", [])),
                anchor_status_ids=list(
                    scan.get(
                        "anchor_status_ids",
                        scan.get("scanned_status_ids", [])[:20],
                    )
                ),
                latest_status_id=str(scan.get("latest_status_id", "")),
                plain_text_filtered=0,
                complete=scan.get("complete", True),
            ),
        )


class _PartiallyFailingNitter(_MultiUserNitter):
    def __init__(self, tweets_by_user, failures_by_user, events=None):
        super().__init__(tweets_by_user, events=events)
        self.failures_by_user = failures_by_user

    async def fetch_tweets(
        self,
        username,
        limit,
        skip_plain_text=False,
        filter_reposts=None,
    ):
        self.filter_reposts_calls.append(filter_reposts)
        self.events.append(f"fetch:{username}")
        if username in self.failures_by_user:
            raise RuntimeError(self.failures_by_user[username])
        return "https://nitter.test", self.tweets_by_user.get(username, [])[:limit]

    async def fetch_tweets_with_stats(
        self,
        username,
        limit,
        skip_plain_text=False,
        filter_reposts=None,
    ):
        self.filter_reposts_calls.append(filter_reposts)
        self.events.append(f"fetch:{username}")
        if username in self.failures_by_user:
            raise RuntimeError(self.failures_by_user[username])
        return "https://nitter.test", self.tweets_by_user.get(username, [])[:limit], 0


class _ConcurrentNitter(_MultiUserNitter):
    def __init__(
        self, tweets_by_user, events=None, failures_by_user=None, filtered=None
    ):
        super().__init__(tweets_by_user, events=events)
        self.failures_by_user = failures_by_user or {}
        self.filtered = filtered or {}
        self.release_first = scheduler_module.asyncio.Event()

    async def fetch_tweets_with_stats_from_instances(
        self,
        username,
        limit,
        instances,
        start_index=0,
        skip_plain_text=False,
        retry_attempts=3,
        filter_reposts=None,
    ):
        self.filter_reposts_calls.append(filter_reposts)
        self.concurrent_calls.append(
            (username, tuple(instances), start_index, skip_plain_text, retry_attempts)
        )
        self.events.append(f"concurrent_fetch_start:{username}")
        if username == "NASA":
            await self.release_first.wait()
        else:
            self.release_first.set()
        self.events.append(f"concurrent_fetch_done:{username}")
        if username in self.failures_by_user:
            raise RuntimeError(self.failures_by_user[username])
        return (
            "https://concurrent.test",
            self.tweets_by_user.get(username, [])[:limit],
            self.filtered.get(username, 0),
        )


class _NoConcurrentNitter(_MultiUserNitter):
    async def fetch_tweets_with_stats_from_instances(self, *args, **kwargs):
        raise AssertionError("concurrent fetch should not be used")


class _Media:
    def __init__(self):
        self.attached = 0
        self.cleaned = 0

    async def attach_media(self, tweets):
        self.attached += len(tweets)

    def cleanup_after_send(self, tweets):
        self.cleaned += len(tweets)


class _RecordingMedia(_Media):
    def __init__(self, events):
        super().__init__()
        self.events = events

    async def attach_media(self, tweets):
        self.events.append("media:" + ",".join(tweet.status_id for tweet in tweets))
        for tweet in tweets:
            for media in tweet.media:
                if media.path is None:
                    media.path = Path(f"{tweet.status_id}.jpg")
        await super().attach_media(tweets)

    def cleanup_after_send(self, tweets):
        self.events.append("cleanup:" + ",".join(tweet.status_id for tweet in tweets))
        super().cleanup_after_send(tweets)


class _StatusMedia(_Media):
    def __init__(self, statuses, events=None):
        super().__init__()
        self.statuses = {str(key): value for key, value in statuses.items()}
        self.events = events if events is not None else []

    async def attach_media_with_results(self, tweets):
        reports = []
        for tweet in tweets:
            status, path = self.statuses.get(str(tweet.status_id), ("ready", None))
            self.events.append(f"media:{tweet.status_id}:{status}")
            if path is not None:
                tweet.media = [
                    TweetMedia(
                        "image",
                        f"https://example.test/{tweet.status_id}.jpg",
                        path=path,
                    )
                ]
            reports.append(types.SimpleNamespace(status=status, error=""))
        self.attached += len(tweets)
        return reports

    def cleanup_after_send(self, tweets):
        self.events.append("cleanup:" + ",".join(tweet.status_id for tweet in tweets))
        super().cleanup_after_send(tweets)


class _BlockingMedia(_Media):
    def __init__(self, block_status_id, expected_attached=2):
        super().__init__()
        self.block_status_id = str(block_status_id)
        self.expected_attached = expected_attached
        self.attached_ids = []
        self.cleaned_ids = []
        self.all_attached = asyncio.Event()
        self.release = asyncio.Event()

    async def attach_media(self, tweets):
        status_ids = [str(tweet.status_id) for tweet in tweets]
        self.attached_ids.extend(status_ids)
        await super().attach_media(tweets)
        if len(self.attached_ids) >= self.expected_attached:
            self.all_attached.set()
        if self.block_status_id in status_ids:
            await self.release.wait()

    def cleanup_after_send(self, tweets):
        self.cleaned_ids.extend(str(tweet.status_id) for tweet in tweets)
        super().cleanup_after_send(tweets)


class _Translator:
    async def attach_translations(self, tweets, target):
        for tweet in tweets:
            tweet.translation = "translated"


class _RecordingTranslator(_Translator):
    def __init__(self, events):
        self.events = events

    async def attach_translations(self, tweets, target):
        self.events.append("translate:" + ",".join(tweet.status_id for tweet in tweets))
        await super().attach_translations(tweets, target)


class _OutOfOrderTranslator(_Translator):
    def __init__(self, events):
        self.events = events
        self.release_first = scheduler_module.asyncio.Event()

    async def attach_translations(self, tweets, target):
        status_id = tweets[0].status_id
        self.events.append(f"translate_start:{status_id}")
        if status_id == "101":
            await self.release_first.wait()
        else:
            self.release_first.set()
        self.events.append(f"translate_done:{status_id}")
        await super().attach_translations(tweets, target)


class _Sender:
    def __init__(
        self,
        success=True,
        failed_targets=None,
        merge_targets=None,
        events=None,
    ):
        self.sent = []
        self.merged_sent = []
        self.group_labels = []
        self.merged_group_labels = []
        self.headers = []
        self.summary_sends = []
        self.batch_summaries = []
        self.merged_batch_summaries = []
        self.media_only_flags = []
        self.merged_media_only_flags = []
        self.tweet_start_indexes = []
        self.success = success
        self.failed_targets = set(failed_targets or [])
        self.merge_targets = set(merge_targets or [])
        self.events = events if events is not None else []

    def supports_merged_forward_for_umo(self, context, umo):
        return umo in self.merge_targets

    async def send_summary_to_umo(self, context, umo, summary):
        del context
        self.summary_sends.append((umo, summary))
        success = self.success and umo not in self.failed_targets
        return types.SimpleNamespace(
            success=success,
            warning="",
            error="" if success else "send failed",
        )

    async def send_to_umo_with_outcome(
        self,
        context,
        umo,
        username,
        instance,
        tweets,
        group_label="",
        header_text="",
        batch_summary="",
        tweet_start_index=1,
        media_only=False,
        omit_status_url=True,
        hide_original_when_translated=False,
        link_style="plain",
        **kwargs,
    ):
        del omit_status_url, hide_original_when_translated, link_style, kwargs
        self.events.append(f"send:{umo}:{username}")
        self.sent.append(
            (umo, username, instance, [tweet.status_id for tweet in tweets])
        )
        self.group_labels.append((umo, username, group_label))
        self.headers.append((umo, username, header_text))
        self.batch_summaries.append((umo, username, batch_summary))
        self.media_only_flags.append(media_only)
        self.tweet_start_indexes.append((umo, username, tweet_start_index))
        success = self.success and umo not in self.failed_targets
        return types.SimpleNamespace(
            success=success,
            warning="",
            error="" if success else "direct send failed",
        )

    async def send_merged_to_umo(
        self,
        context,
        umo,
        batches,
        group_label="",
        batch_summary="",
        media_only=False,
        **kwargs,
    ):
        del kwargs
        self.events.append(f"merged:{umo}")
        self.merged_sent.append(
            (
                umo,
                [
                    (username, instance, [tweet.status_id for tweet in tweets])
                    for username, instance, tweets in batches
                ],
            )
        )
        self.merged_group_labels.append((umo, group_label))
        self.merged_batch_summaries.append((umo, batch_summary))
        self.merged_media_only_flags.append(media_only)
        success = self.success and umo not in self.failed_targets
        return types.SimpleNamespace(
            success=success,
            warning="",
            error="" if success else "send failed",
            mode="full_forward",
        )


class _FailOnceStatusSender(_Sender):
    def __init__(self, failed_status_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.failed_status_id = str(failed_status_id)
        self.failed = False

    async def send_to_umo_with_outcome(self, *args, **kwargs):
        tweets = args[4]
        status_id = str(tweets[0].status_id) if tweets else ""
        outcome = await super().send_to_umo_with_outcome(*args, **kwargs)
        if status_id == self.failed_status_id and not self.failed:
            self.failed = True
            outcome.success = False
            outcome.warning = ""
            outcome.error = "send failed once"
        return outcome


class _RaisingSender(_Sender):
    async def send_to_umo_with_outcome(self, *args, **kwargs):
        del args, kwargs
        raise RuntimeError("send crashed")


class _RaisingMergedSender(_Sender):
    async def send_merged_to_umo(self, *args, **kwargs):
        del args, kwargs
        raise RuntimeError("merge crashed")


class _RaisingSummarySender(_Sender):
    async def send_summary_to_umo(self, *args, **kwargs):
        del args, kwargs
        raise RuntimeError("summary crashed")


class _RaisingPostSendOutcome:
    success = True
    error = ""
    delivery_status = "success"
    delivery_error = ""
    mode = "full_forward"

    @property
    def warning(self):
        raise RuntimeError("post-send bookkeeping crashed")


class _RaisingPostSendSender(_Sender):
    async def send_to_umo_with_outcome(self, *args, **kwargs):
        await super().send_to_umo_with_outcome(*args, **kwargs)
        return _RaisingPostSendOutcome()

    async def send_merged_to_umo(self, *args, **kwargs):
        await super().send_merged_to_umo(*args, **kwargs)
        return _RaisingPostSendOutcome()


class _PartialDeliverySender(_Sender):
    def __init__(self, *args, report_delivered_ids=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.report_delivered_ids = report_delivered_ids

    async def send_to_umo_with_outcome(self, *args, **kwargs):
        outcome = await super().send_to_umo_with_outcome(*args, **kwargs)
        outcome.success = False
        outcome.error = "media failed"
        outcome.warning = "media failed"
        outcome.delivery_status = "partial_failed"
        outcome.delivery_error = "media failed"
        tweets = args[4]
        outcome.delivered_status_ids = (
            tuple(tweet.status_id for tweet in tweets if tweet.status_id)
            if self.report_delivered_ids
            else ()
        )
        return outcome


class _SuccessfulPartialDeliverySender(_PartialDeliverySender):
    async def send_to_umo_with_outcome(self, *args, **kwargs):
        outcome = await super().send_to_umo_with_outcome(*args, **kwargs)
        outcome.success = True
        return outcome


class _PartialMergedDeliverySender(_Sender):
    def __init__(self, delivered_status_ids, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.delivered_status_ids = tuple(delivered_status_ids)

    async def send_merged_to_umo(self, *args, **kwargs):
        outcome = await super().send_merged_to_umo(*args, **kwargs)
        outcome.success = False
        outcome.error = "right split failed"
        outcome.warning = ""
        outcome.delivery_status = "partial_failed"
        outcome.delivery_error = "right split failed"
        outcome.delivered_status_ids = self.delivered_status_ids
        return outcome


class SchedulerDeliveryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = TemporaryDirectory()
        self.schedulers = []
        db_path = Path(self.temp_dir.name) / "nitter_tweets.db"

        self.storage_patch = patch.object(
            StorageAdapter,
            "_init_sqlite",
            return_value=SQLiteStorage(db_path),
        )
        self.storage_patch.start()

    async def test_stop_consumes_exception_from_completed_task(self):
        scheduler = self._create_scheduler({})

        async def fail_task():
            raise RuntimeError("completed task failed")

        task = asyncio.create_task(fail_task())
        await asyncio.sleep(0)
        self.assertTrue(task.done())
        scheduler._task = task

        with (
            patch.object(scheduler.storage, "close") as close_mock,
            patch.object(scheduler_module.logger, "warning") as warning_mock,
        ):
            await scheduler.stop()

        self.assertIsNone(scheduler._task)
        close_mock.assert_called_once_with()
        self.assertTrue(
            any(
                "completed task failed" in str(call.args[0])
                for call in warning_mock.call_args_list
            )
        )

    async def asyncTearDown(self):
        for scheduler in self.schedulers:
            scheduler.storage.close()
        self.storage_patch.stop()
        self.temp_dir.cleanup()

    def test_sender_parses_string_media_switches_as_booleans(self):
        sender = TweetSender(
            {
                "send_image_attachments": "false",
                "send_video_attachments": "false",
            }
        )

        self.assertFalse(sender.send_image_attachments)
        self.assertFalse(sender.send_video_attachments)

    async def test_forward_chunks_include_batch_summary_only_once(self):
        sender = TweetSender({})
        tweets = [self._make_tweet("NASA", str(status_id)) for status_id in range(9)]
        calls = []

        async def fake_send_chunk(
            context,
            umo,
            username,
            instance,
            chunk,
            group_label="",
            header_text="",
            batch_summary="",
            tweet_start_index=1,
            media_only=False,
            **kwargs,
        ):
            del context, umo, username, instance, media_only, kwargs
            calls.append(
                (
                    len(chunk),
                    group_label,
                    header_text,
                    batch_summary,
                    tweet_start_index,
                )
            )
            return SendOutcome(success=True)

        sender._send_forward_chunk_to_umo = fake_send_chunk

        outcome = await sender._send_forward_chunks_to_umo(
            object(),
            "telegram:GroupMessage:1",
            "NASA",
            "https://nitter.test",
            tweets,
            group_label="默认分组",
            header_text="检查摘要",
            batch_summary="批次概括",
        )

        self.assertTrue(outcome.success)
        self.assertEqual(
            calls,
            [
                (8, "默认分组", "检查摘要", "批次概括", 1),
                (1, "", "", "", 9),
            ],
        )

    async def test_forward_split_failure_reports_delivered_status_ids(self):
        sender = TweetSender.__new__(TweetSender)
        sender.FORWARD_SPLIT_MIN_TWEETS = 1
        sender.renderer = types.SimpleNamespace(
            build_nodes_for_uin=lambda *args, **kwargs: "nodes",
            format_plain=lambda *args, **kwargs: "plain",
        )
        tweets = [self._make_tweet("NASA", str(status_id)) for status_id in range(4)]
        reject_error = "retcode=1200 res_id failed"
        attempts = iter(
            [
                SendAttempt(
                    success=False,
                    retryable=True,
                    error=reject_error,
                )
            ]
        )

        async def send_context_message(*args, **kwargs):
            del args, kwargs
            return next(attempts)

        nested_calls = []

        async def send_nested_part(
            context,
            umo,
            username,
            instance,
            part,
            **kwargs,
        ):
            del context, umo, username, instance, kwargs
            nested_calls.append([tweet.status_id for tweet in part])
            if len(nested_calls) == 1:
                return SendOutcome(success=True)
            return SendOutcome(
                success=False,
                error="right split failed",
                delivery_status="partial_failed",
                delivery_error="right split failed",
                delivered_status_ids=("2",),
            )

        direct_calls = []

        async def fail_direct(*args, **kwargs):
            del kwargs
            direct_calls.append([tweet.status_id for tweet in args[4]])
            return SendOutcome(
                success=False,
                error="direct fallback failed",
                delivery_status="partial_failed",
                delivery_error="direct fallback failed",
                delivered_status_ids=("3",),
            )

        sender._send_context_message = send_context_message
        sender._send_forward_chunk_to_umo = send_nested_part
        sender._send_direct_to_umo = fail_direct

        outcome = await TweetSender._send_forward_chunk_to_umo(
            sender,
            object(),
            "aiocqhttp:GroupMessage:1",
            "NASA",
            "https://nitter.test",
            tweets,
        )

        self.assertFalse(outcome.success)
        self.assertEqual(outcome.delivery_status, "partial_failed")
        self.assertEqual(outcome.delivered_status_ids, ("0", "1", "2", "3"))
        self.assertEqual(nested_calls, [["0", "1"], ["2", "3"]])
        self.assertEqual(direct_calls, [["3"]])

    async def test_forward_chunks_preserve_partial_delivery_ids_on_failure(self):
        sender = TweetSender.__new__(TweetSender)
        sender.FORWARD_TWEET_CHUNK_SIZE = 2
        tweets = [self._make_tweet("NASA", str(status_id)) for status_id in range(4)]
        calls = []

        async def send_chunk(
            context,
            umo,
            username,
            instance,
            chunk,
            **kwargs,
        ):
            del context, umo, username, instance, kwargs
            calls.append([tweet.status_id for tweet in chunk])
            if len(calls) == 1:
                return SendOutcome(success=True)
            return SendOutcome(
                success=False,
                error="second chunk failed",
                delivery_status="partial_failed",
                delivery_error="second chunk failed",
                delivered_status_ids=("2",),
            )

        sender._send_forward_chunk_to_umo = send_chunk

        outcome = await sender._send_forward_chunks_to_umo(
            object(),
            "aiocqhttp:GroupMessage:1",
            "NASA",
            "https://nitter.test",
            tweets,
        )

        self.assertFalse(outcome.success)
        self.assertEqual(outcome.delivery_status, "partial_failed")
        self.assertEqual(outcome.delivery_error, "second chunk failed")
        self.assertEqual(outcome.delivered_status_ids, ("0", "1", "2"))
        self.assertEqual(calls, [["0", "1"], ["2", "3"]])

    def _create_scheduler(
        self,
        config,
        *,
        nitter=None,
        media=None,
        sender=None,
        translator=None,
    ):
        scheduler = NitterTweetScheduler(
            _Owner(),
            context=None,
            config=config,
            nitter=nitter or _Nitter(),
            media=media or _Media(),
            sender=sender or _Sender(),
            translator=translator or _Translator(),
        )
        self.schedulers.append(scheduler)
        return scheduler

    def _make_tweet(self, username, status_id):
        return TweetItem(
            text=f"tweet {status_id}",
            link=f"https://x.com/{username}/status/{status_id}",
            published="",
        )

    async def test_blogger_repost_filter_override_reaches_serial_and_concurrent_fetch(
        self,
    ):
        class HtmlBackend:
            def __init__(self):
                self.filter_reposts_calls = []

            def fetch_user(
                self,
                username,
                limit,
                *,
                filter_reposts=None,
            ):
                self.filter_reposts_calls.append(filter_reposts)
                return (
                    "https://html.test",
                    [
                        TweetItem(
                            text="tweet 100",
                            link=f"https://x.com/{username}/status/100",
                            published="",
                        )
                    ][:limit],
                )

        config = {
            "filter_reposts_enabled": True,
            "tweet_groups": [
                {
                    "name": "博主",
                    "group_id": "bloggers1",
                    "group_type": "blogger",
                    "watch_users": ["NASA"],
                    "push_targets": [],
                    "filter_reposts_enabled": False,
                }
            ],
        }
        serial_nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": [],
                        "scanned_status_ids": [],
                    }
                ]
            }
        )
        html_backend = HtmlBackend()
        serial_nitter.fetch_user_html = html_backend.fetch_user
        serial_scheduler = self._create_scheduler(
            config,
            nitter=serial_nitter,
        )
        group = serial_scheduler._schedule_groups(log_invalid_targets=False)[0]

        await serial_scheduler._fetch_group_user(
            group,
            0,
            "NASA",
            20,
            False,
            None,
            concurrent=False,
        )

        concurrent_nitter = _MultiUserNitter(
            {"NASA": [self._make_tweet("NASA", "100")]}
        )
        concurrent_scheduler = self._create_scheduler(
            config,
            nitter=concurrent_nitter,
        )
        concurrent_group = concurrent_scheduler._schedule_groups(
            log_invalid_targets=False
        )[0]
        concurrent_nitter.instances = ["https://nitter.test"]

        await concurrent_scheduler._fetch_group_user(
            concurrent_group,
            0,
            "NASA",
            20,
            False,
            None,
            concurrent=True,
        )

        self.assertEqual(serial_nitter.filter_reposts_calls, [False])
        self.assertEqual(html_backend.filter_reposts_calls, [False])
        self.assertEqual(concurrent_nitter.filter_reposts_calls, [False])

    async def test_blogger_media_path_only_when_both_plain_text_and_repost_filter_on(
        self,
    ):
        """/<user>/media/rss excludes ALL retweets.  Only switch to it when
        both skip_plain_text and filter_reposts are active; when the user
        wants to keep retweets (filter_reposts=False), stay on the regular
        RSS feed so retweets are not silently dropped.
        """
        tweet = self._make_tweet("NASA", "100")
        scan = [{"tweets": [tweet], "scanned_status_ids": ["100"]}]

        # Case 1: both plain_text and repost filtering on → media path
        config_both = {
            "filter_reposts_enabled": True,
            "tweet_groups": [
                {
                    "name": "博主",
                    "group_id": "b1",
                    "group_type": "blogger",
                    "watch_users": ["NASA"],
                    "push_targets": [],
                    "filter_reposts_enabled": True,
                    "filter_plain_text_enabled": True,
                }
            ],
        }
        nitter_both = _SchedulerNitter({"NASA": scan})
        sched_both = self._create_scheduler(config_both, nitter=nitter_both)
        group_both = sched_both._schedule_groups(log_invalid_targets=False)[0]
        await sched_both._fetch_group_user(
            group_both, 0, "NASA", 20, True, None, concurrent=False
        )
        self.assertEqual(nitter_both.path_overrides, ["NASA/media"])

        # Case 2: plain_text on, repost filter off → regular RSS
        config_no_repost = {
            "filter_reposts_enabled": False,
            "tweet_groups": [
                {
                    "name": "博主",
                    "group_id": "b2",
                    "group_type": "blogger",
                    "watch_users": ["NASA"],
                    "push_targets": [],
                    "filter_reposts_enabled": False,
                    "filter_plain_text_enabled": True,
                }
            ],
        }
        nitter_no_repost = _SchedulerNitter({"NASA": list(scan)})
        sched_nr = self._create_scheduler(config_no_repost, nitter=nitter_no_repost)
        group_nr = sched_nr._schedule_groups(log_invalid_targets=False)[0]
        await sched_nr._fetch_group_user(
            group_nr, 0, "NASA", 20, True, None, concurrent=False
        )
        self.assertEqual(nitter_no_repost.path_overrides, [""])

    async def test_blogger_merged_skipped_when_repost_filter_off(self):
        """When filter_reposts is off, the merged RSS path must be skipped
        because author-based splitting drops retweets of outside accounts.
        Per-user requests are used instead so retweets are preserved.
        """
        tweet_a = self._make_tweet("alice", "100")
        tweet_b = self._make_tweet("bob", "200")

        class _MergedAwareNitter(_SchedulerNitter):
            def __init__(self, scans):
                super().__init__(scans)
                self.merged_called = False

            async def fetch_merged_for_scheduler(self, *a, **kw):
                self.merged_called = True
                raise AssertionError("merged path should be skipped")

        config = {
            "filter_reposts_enabled": False,
            "tweet_groups": [
                {
                    "name": "博主",
                    "group_id": "b1",
                    "group_type": "blogger",
                    "watch_users": ["alice", "bob"],
                    "push_targets": [],
                    "filter_reposts_enabled": False,
                }
            ],
        }
        nitter = _MergedAwareNitter(
            {
                "alice": [{"tweets": [tweet_a], "scanned_status_ids": ["100"]}],
                "bob": [{"tweets": [tweet_b], "scanned_status_ids": ["200"]}],
            }
        )
        scheduler = self._create_scheduler(config, nitter=nitter)
        group = scheduler._schedule_groups(log_invalid_targets=False)[0]
        results = await scheduler._fetch_group_users(group, 20, False, {})

        self.assertFalse(nitter.merged_called)
        self.assertEqual(len(results), 2)
        self.assertEqual(nitter.calls, [("alice", None), ("bob", None)])

    def test_all_targets_delivered_rejects_empty_target_list(self):
        batch = scheduler_module.PendingTweetBatch(
            username="NASA",
            instance="https://nitter.test",
            tweets=[self._make_tweet("NASA", "101")],
            fetched_ids=["101"],
            seen_ids=[],
            delivered_targets={"telegram:FriendMessage:1"},
        )

        self.assertFalse(
            scheduler_module.NitterTweetScheduler._all_targets_delivered([], batch)
        )
        self.assertTrue(
            scheduler_module.NitterTweetScheduler._all_targets_delivered(
                ["telegram:FriendMessage:1"], batch
            )
        )

    async def test_scheduler_fetch_preserves_explicit_empty_anchor_ids(self):
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "scanned_status_ids": ["102", "101"],
                        "anchor_status_ids": [],
                        "latest_status_id": "102",
                    }
                ]
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
            },
            nitter=nitter,
        )
        group = scheduler._schedule_groups(log_invalid_targets=False)[0]

        result = await scheduler._fetch_group_user(
            group,
            0,
            "NASA",
            20,
            False,
            None,
            concurrent=False,
        )

        self.assertEqual(result.scanned_status_ids, ["102", "101"])
        self.assertEqual(result.anchor_status_ids, [])

    async def test_replay_push_history_uses_real_scheduler_and_records_delivery(self):
        events = []
        sender = _Sender(events=events)
        media = _RecordingMedia(events)
        target = "telegram:FriendMessage:1"
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "tweet_groups": [
                    {
                        "group_id": "global",
                        "name": "默认分组",
                        "enabled": True,
                        "watch_users": ["NASA"],
                        "push_targets": [target, "weixin:FriendMessage:2"],
                        "media_only_enabled": True,
                    }
                ],
                "send_target_interval": 0,
            },
            sender=sender,
            media=media,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        record_id = await scheduler.storage.record_push_history(
            "global",
            "NASA",
            self._make_tweet("NASA", "901"),
            target,
            "scheduled",
            "https://nitter.test",
        )

        result = await scheduler.replay_push_history(record_id, [target])

        self.assertTrue(result["success"])
        self.assertEqual(result["success_targets"], 1)
        self.assertEqual(
            sender.sent[-1],
            (target, "NASA", "https://nitter.test", ["901"]),
        )
        self.assertEqual(sender.media_only_flags, [False])
        self.assertEqual(events, ["media:901", f"send:{target}:NASA", "cleanup:901"])
        replay_rows = await scheduler.storage.get_push_history("global", "NASA")
        self.assertTrue(
            any(
                row.source == "replay" and row.target_umo == target
                for row in replay_rows
            )
        )

    async def test_replay_push_history_rejects_stale_target_before_media_prepare(self):
        events = []
        sender = _Sender(events=events)
        media = _RecordingMedia(events)
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "send_target_interval": 0,
            },
            sender=sender,
            media=media,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        record_id = await scheduler.storage.record_push_history(
            "global",
            "NASA",
            self._make_tweet("NASA", "902"),
            "telegram:FriendMessage:1",
            "scheduled",
            "https://nitter.test",
        )

        result = await scheduler.replay_push_history(
            record_id,
            ["telegram:FriendMessage:missing"],
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["invalid_targets"], ["telegram:FriendMessage:missing"])
        self.assertEqual(events, [])

    async def test_replay_partial_delivery_is_recorded_but_not_counted_success(self):
        target = "lark:GroupMessage:chat-1"
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "send_target_interval": 0,
            },
            sender=_PartialDeliverySender(),
            media=_RecordingMedia([]),
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        record_id = await scheduler.storage.record_push_history(
            "global",
            "NASA",
            self._make_tweet("NASA", "903"),
            target,
            "scheduled",
            "https://nitter.test",
        )

        result = await scheduler.replay_push_history(record_id, [target])

        self.assertFalse(result["success"])
        self.assertEqual(result["success_targets"], 0)
        self.assertIn(target, result["failed_targets"])
        replay_rows = await scheduler.storage.get_push_history("global", "NASA")
        self.assertTrue(
            any(
                row.source == "replay"
                and row.target_umo == target
                and row.delivery_status == "partial_failed"
                for row in replay_rows
            )
        )

    async def test_replay_batch_aggregates_groups_and_records_history(self):
        events = []
        sender = _Sender(events=events)
        media = _RecordingMedia(events)
        tg1 = "telegram:FriendMessage:1"
        tg2 = "telegram:FriendMessage:2"
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "tweet_groups": [
                    {
                        "group_id": "g1",
                        "name": "博主组",
                        "group_type": "blogger",
                        "watch_users": ["NASA", "spacex"],
                        "push_targets": [tg1],
                    },
                    {
                        "group_id": "g2",
                        "name": "标签组",
                        "group_type": "tag",
                        "watch_queries": ["#photo"],
                        "push_targets": [tg2],
                    },
                ],
                "send_target_interval": 0,
            },
            sender=sender,
            media=media,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        # StorageAdapter does not forward pushed_at; write via the underlying
        # sqlite handle so the merged-forward order (oldest first) is testable.
        sqlite_storage = await scheduler.storage._ensure_sqlite_connected()
        rid_902 = await asyncio.to_thread(
            sqlite_storage.record_push_history,
            "g1",
            "NASA",
            self._make_tweet("NASA", "902"),
            tg1,
            "scheduled",
            "https://nitter.test",
            200,
        )
        rid_901 = await asyncio.to_thread(
            sqlite_storage.record_push_history,
            "g1",
            "NASA",
            self._make_tweet("NASA", "901"),
            tg1,
            "scheduled",
            "https://nitter.test",
            100,
        )
        rid_903 = await asyncio.to_thread(
            sqlite_storage.record_push_history,
            "g1",
            "spacex",
            self._make_tweet("spacex", "903"),
            tg1,
            "scheduled",
            "https://nitter.test",
            300,
        )
        rid_904 = await asyncio.to_thread(
            sqlite_storage.record_push_history,
            "g2",
            "q:photo",
            self._make_tweet("q:photo", "904"),
            tg2,
            "scheduled",
            "https://nitter.test",
            400,
        )

        result = await scheduler.replay_push_history_batch(
            [rid_901, rid_902, rid_903, rid_904],
            {"g1": [tg1]},
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["triggered"], 4)
        self.assertEqual(
            [(g["group_id"], g["record_count"]) for g in result["groups"]],
            [("g1", 3), ("g2", 1)],
        )
        await scheduler._replay_batch_task

        # Group g1 aggregates per source, oldest first; g2 falls back to its
        # full current target list when omitted from targets_by_group.
        self.assertEqual(
            sender.merged_sent,
            [
                (
                    tg1,
                    [
                        ("NASA", "https://nitter.test", ["901", "902"]),
                        ("spacex", "https://nitter.test", ["903"]),
                    ],
                ),
                (tg2, [("q:photo", "https://nitter.test", ["904"])]),
            ],
        )
        self.assertEqual(
            events,
            [
                "media:901,902,903",
                f"merged:{tg1}",
                "cleanup:901,902",
                "cleanup:903",
                "media:904",
                f"merged:{tg2}",
                "cleanup:904",
            ],
        )
        replay_rows = []
        for group_id, user in (("g1", "NASA"), ("g1", "spacex"), ("g2", "q:photo")):
            replay_rows.extend(await scheduler.storage.get_push_history(group_id, user))
        replay_rows = [row for row in replay_rows if row.source == "replay"]
        self.assertEqual(
            sorted((row.username, row.status_id) for row in replay_rows),
            [("NASA", "901"), ("NASA", "902"), ("q:photo", "904"), ("spacex", "903")],
        )
        self.assertTrue(all(row.delivery_status == "success" for row in replay_rows))

    async def test_replay_batch_skips_group_with_stale_target_and_replays_rest(self):
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "tweet_groups": [
                    {
                        "group_id": "g1",
                        "name": "组1",
                        "watch_users": ["NASA"],
                        "push_targets": ["telegram:FriendMessage:1"],
                    },
                    {
                        "group_id": "g2",
                        "name": "组2",
                        "watch_users": ["ESA"],
                        "push_targets": ["telegram:FriendMessage:2"],
                    },
                ],
                "send_target_interval": 0,
            },
            sender=sender,
            media=_RecordingMedia([]),
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        rid_911 = await scheduler.storage.record_push_history(
            "g1",
            "NASA",
            self._make_tweet("NASA", "911"),
            "telegram:FriendMessage:1",
            "scheduled",
            "https://nitter.test",
        )
        rid_912 = await scheduler.storage.record_push_history(
            "g2",
            "ESA",
            self._make_tweet("ESA", "912"),
            "telegram:FriendMessage:2",
            "scheduled",
            "https://nitter.test",
        )

        result = await scheduler.replay_push_history_batch(
            [rid_911, rid_912],
            {"g1": ["telegram:FriendMessage:gone"]},
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["triggered"], 1)
        self.assertEqual([item["group_id"] for item in result["skipped"]], ["g1"])
        await scheduler._replay_batch_task

        self.assertEqual(
            [umo for umo, _batches in sender.merged_sent], ["telegram:FriendMessage:2"]
        )

    async def test_replay_batch_rejects_second_trigger_while_running(self):
        media = _BlockingMedia("921", expected_attached=1)
        target = "telegram:FriendMessage:1"
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "send_target_interval": 0,
            },
            sender=_Sender(),
            media=media,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        rid_921 = await scheduler.storage.record_push_history(
            "global",
            "NASA",
            self._make_tweet("NASA", "921"),
            target,
            "scheduled",
            "https://nitter.test",
        )

        first = await scheduler.replay_push_history_batch([rid_921])
        self.assertTrue(first["success"])
        second = await scheduler.replay_push_history_batch([rid_921])
        self.assertFalse(second["success"])
        self.assertIn("已有批量重推正在进行", str(second["error"]))

        media.release.set()
        await scheduler._replay_batch_task

    async def test_replay_batch_reports_invalid_records_and_over_limit(self):
        scheduler = self._create_scheduler({"schedule_enabled": True})
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        missing = await scheduler.replay_push_history_batch([999_999])
        self.assertFalse(missing["success"])
        self.assertEqual(
            missing["skipped"], [{"record_id": "999999", "reason": "未找到推送记录"}]
        )

        over_limit = await scheduler.replay_push_history_batch(list(range(1, 52)))
        self.assertFalse(over_limit["success"])
        self.assertIn("最多", str(over_limit["error"]))

    async def test_replay_batch_partial_delivery_records_only_delivered(self):
        class _PartialMergedSender(_Sender):
            async def send_merged_to_umo(self, context, umo, batches, **kwargs):
                await super().send_merged_to_umo(context, umo, batches, **kwargs)
                return types.SimpleNamespace(
                    success=False,
                    warning="",
                    error="partial failure",
                    mode="forward",
                    delivery_status="partial_failed",
                    delivery_error="partial failure",
                    delivered_status_ids=("931",),
                )

        target = "telegram:FriendMessage:1"
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "send_target_interval": 0,
            },
            sender=_PartialMergedSender(),
            media=_RecordingMedia([]),
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.record_push_history(
            "global",
            "NASA",
            self._make_tweet("NASA", "931"),
            target,
            "scheduled",
            "https://nitter.test",
        )
        await scheduler.storage.record_push_history(
            "global",
            "NASA",
            self._make_tweet("NASA", "932"),
            target,
            "scheduled",
            "https://nitter.test",
        )
        record_ids = [
            row.id for row in await scheduler.storage.get_push_history("global", "NASA")
        ]

        result = await scheduler.replay_push_history_batch(record_ids)

        self.assertTrue(result["success"])
        await scheduler._replay_batch_task
        replay_rows = [
            row
            for row in await scheduler.storage.get_push_history("global", "NASA")
            if row.source == "replay"
        ]
        self.assertEqual([row.status_id for row in replay_rows], ["931"])
        self.assertEqual(replay_rows[0].delivery_status, "partial_failed")

    async def test_replay_batch_send_crash_writes_failed_history_without_seen(self):
        target = "telegram:FriendMessage:1"
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "send_target_interval": 0,
            },
            sender=_RaisingMergedSender(),
            media=_RecordingMedia([]),
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.record_push_history(
            "global",
            "NASA",
            self._make_tweet("NASA", "941"),
            target,
            "scheduled",
            "https://nitter.test",
        )
        await scheduler.storage.record_push_history(
            "global",
            "NASA",
            self._make_tweet("NASA", "942"),
            target,
            "scheduled",
            "https://nitter.test",
        )
        record_ids = [
            row.id for row in await scheduler.storage.get_push_history("global", "NASA")
        ]
        seen_before = await scheduler.storage.get_seen_ids("global", "NASA")

        result = await scheduler.replay_push_history_batch(record_ids)

        self.assertTrue(result["success"])
        await scheduler._replay_batch_task
        failed_rows = [
            row
            for row in await scheduler.storage.get_push_history("global", "NASA")
            if row.source == "replay"
        ]
        self.assertEqual(sorted(row.status_id for row in failed_rows), ["941", "942"])
        self.assertTrue(
            all(
                row.delivery_status == "failed" and row.delivery_error
                for row in failed_rows
            )
        )
        self.assertEqual(
            await scheduler.storage.get_seen_ids("global", "NASA"), seen_before
        )

    async def test_scheduler_ignores_unseen_tweets_older_than_seen_watermark(self):
        sender = _Sender()
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "200"),
                    self._make_tweet("NASA", "150"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 2,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["200"])

        result = await scheduler.run_check(reason="test_seen_watermark_older")
        seen_ids = await scheduler.storage.get_seen_ids("global", "NASA")

        self.assertEqual(result.new_tweet_count, 0)
        self.assertEqual(sender.sent, [])
        self.assertIn("NASA", result.no_new_users)
        self.assertNotIn("150", seen_ids)
        self.assertIn("200", seen_ids)

    async def test_scheduler_sends_all_unseen_tweets_before_scan_baseline(self):
        sender = _Sender()
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "201"),
                    self._make_tweet("NASA", "150"),
                    self._make_tweet("NASA", "200"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 3,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["200"])

        result = await scheduler.run_check(reason="test_seen_watermark_mixed")
        seen_ids = await scheduler.storage.get_seen_ids("global", "NASA")

        self.assertEqual(result.new_tweet_count, 2)
        self.assertEqual(
            [item[3] for item in sender.sent],
            [["201"], ["150"]],
        )
        self.assertIn("150", seen_ids)
        self.assertIn("201", seen_ids)

    async def test_scheduler_uses_surviving_anchor_when_newest_anchor_is_deleted(self):
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "scanned_status_ids": [
                            str(status_id) for status_id in range(120, 100, -1)
                        ],
                        "latest_status_id": "120",
                    },
                    {
                        "tweets": [
                            self._make_tweet("NASA", str(status_id))
                            for status_id in range(125, 120, -1)
                        ],
                        "scanned_status_ids": [
                            "125",
                            "124",
                            "123",
                            "122",
                            "121",
                            "119",
                        ],
                        "anchor_status_ids": [
                            str(status_id) for status_id in range(125, 105, -1)
                        ],
                        "latest_status_id": "125",
                    },
                ]
            }
        )
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        first = await scheduler.run_check(reason="test_deleted_newest_anchor_seed")
        second = await scheduler.run_check(reason="test_deleted_newest_anchor_update")

        self.assertEqual(first.new_tweet_count, 0)
        self.assertEqual(second.new_tweet_count, 5)
        self.assertEqual(
            [status_id for item in sender.sent for status_id in item[3]],
            ["125", "124", "123", "122", "121"],
        )
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("global"),
            {"NASA": [str(status_id) for status_id in range(125, 105, -1)]},
        )

    async def test_failed_scheduled_push_marks_seen_and_does_not_retry(self):
        sender = _Sender(success=False)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "201"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 1,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        await scheduler.run_check(reason="test_failed_seen")
        seen_ids = await scheduler.storage.get_seen_ids("global", "NASA")

        self.assertIn("201", seen_ids)
        history = await scheduler.storage.get_push_history("global", "NASA")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].delivery_status, "failed")
        self.assertEqual(history[0].delivery_error, "direct send failed")
        second = await scheduler.run_check(reason="test_failed_seen_again")
        self.assertEqual(second.new_tweet_count, 0)
        self.assertEqual(len(sender.sent), 1)

    async def test_send_exception_marks_seen_and_does_not_retry(self):
        sender = _RaisingSender()
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "202"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 1,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        await scheduler.run_check(reason="test_send_exception_seen")
        self.assertIn("202", await scheduler.storage.get_seen_ids("global", "NASA"))
        history = await scheduler.storage.get_push_history("global", "NASA")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].delivery_status, "failed")
        self.assertEqual(history[0].delivery_error, "send crashed")
        second = await scheduler.run_check(reason="test_send_exception_seen_again")
        self.assertEqual(second.new_tweet_count, 0)

    async def test_summary_send_exception_keeps_batch_unhandled(self):
        target = "telegram:FriendMessage:1"
        sender = _RaisingSummarySender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
            },
            nitter=_MultiUserNitter({"NASA": []}),
            sender=sender,
        )
        batch = scheduler_module.PendingTweetBatch(
            username="NASA",
            instance="https://nitter.test",
            tweets=[self._make_tweet("NASA", "203")],
            fetched_ids=["203"],
            seen_ids=["100"],
        )
        result = scheduler_module.ScheduledCheckResult(
            reason="summary_exception",
            group_id="global",
            group_type="blogger",
            targets=[target],
        )

        await scheduler._send_per_user_updates(
            [batch],
            result,
            [target],
            target_interval=0,
            user_interval=0,
            batch_summary="summary",
            history_group_id="global",
            history_source="scheduled",
        )

        self.assertNotIn(target, batch.delivered_targets)
        self.assertEqual(sender.sent, [])

    async def test_send_ordinary_batches_summary_enabled_calls_send_summary_to_umo(
        self,
    ):
        target = "telegram:FriendMessage:1"
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "push": {"send_batch_summary_enabled": True},
            },
            sender=sender,
        )
        self.assertTrue(scheduler.send_batch_summary_enabled)
        batch = scheduler_module.PendingTweetBatch(
            username="NASA",
            instance="https://nitter.test",
            tweets=[self._make_tweet("NASA", "203")],
            fetched_ids=["203"],
            seen_ids=["100"],
        )
        result = scheduler_module.ScheduledCheckResult(
            reason="summary_enabled",
            group_id="global",
            group_type="blogger",
            targets=[target],
        )

        await scheduler._send_per_user_updates(
            [batch],
            result,
            [target],
            target_interval=0,
            user_interval=0,
            batch_summary="📬 默认分组 · 1 位博主 · 1 条新推文",
            history_group_id="global",
            history_source="scheduled",
        )

        self.assertEqual(len(sender.summary_sends), 1)
        self.assertEqual(
            sender.summary_sends[0],
            (target, "📬 默认分组 · 1 位博主 · 1 条新推文"),
        )
        self.assertEqual(len(sender.sent), 1)

    async def test_send_ordinary_batches_summary_disabled_suppresses_send_summary_to_umo(
        self,
    ):
        target = "telegram:FriendMessage:1"
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "push": {"send_batch_summary_enabled": False},
            },
            sender=sender,
        )
        self.assertFalse(scheduler.send_batch_summary_enabled)
        batch = scheduler_module.PendingTweetBatch(
            username="NASA",
            instance="https://nitter.test",
            tweets=[self._make_tweet("NASA", "203")],
            fetched_ids=["203"],
            seen_ids=["100"],
        )
        result = scheduler_module.ScheduledCheckResult(
            reason="summary_disabled",
            group_id="global",
            group_type="blogger",
            targets=[target],
        )

        await scheduler._send_per_user_updates(
            [batch],
            result,
            [target],
            target_interval=0,
            user_interval=0,
            batch_summary="📬 默认分组 · 1 位博主 · 1 条新推文",
            history_group_id="global",
            history_source="scheduled",
        )

        self.assertEqual(sender.summary_sends, [])
        self.assertEqual(len(sender.sent), 1)

    async def test_send_ordinary_batches_alias_summary_suppressed_when_disabled(self):
        target = "telegram:FriendMessage:1"
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "push": {"send_batch_summary_enabled": False},
            },
            sender=sender,
        )
        batch = scheduler_module.PendingTweetBatch(
            username="NASA",
            instance="https://nitter.test",
            tweets=[self._make_tweet("NASA", "203")],
            fetched_ids=["203"],
            seen_ids=["100"],
        )
        result = scheduler_module.ScheduledCheckResult(
            reason="summary_alias",
            group_id="global",
            group_type="blogger",
            targets=[target],
        )

        await scheduler._send_ordinary_batches(
            [batch],
            result,
            [target],
            target_interval=0,
            user_interval=0,
            batch_summary="📬 默认分组 · 1 位博主 · 1 条新推文",
            history_group_id="global",
            history_source="scheduled",
        )

        self.assertEqual(sender.summary_sends, [])
        self.assertEqual(len(sender.sent), 1)

    def test_send_batch_summary_enabled_property_parsing(self):
        cases = [
            ({}, True),
            ({"send_batch_summary_enabled": True}, True),
            ({"send_batch_summary_enabled": False}, False),
            ({"push": {"send_batch_summary_enabled": True}}, True),
            ({"push": {"send_batch_summary_enabled": False}}, False),
            ({"push": {"send_batch_summary_enabled": "false"}}, False),
            ({"push": {"send_batch_summary_enabled": "0"}}, False),
            ({"push": {"send_batch_summary_enabled": "off"}}, False),
            ({"push": {"send_batch_summary_enabled": "true"}}, True),
        ]
        for cfg, expected in cases:
            with self.subTest(cfg=cfg, expected=expected):
                scheduler = self._create_scheduler(cfg)
                self.assertIs(scheduler.send_batch_summary_enabled, expected)

    async def test_run_check_ordinary_batches_summary_enabled_calls_send_summary(self):
        target = "telegram:FriendMessage:1"
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": [self._make_tweet("NASA", "101")],
                        "scanned_status_ids": ["101", "100"],
                        "anchor_status_ids": ["101", "100"],
                    }
                ]
            }
        )
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "push": {"send_batch_summary_enabled": True},
                "tweet_groups": [
                    {
                        "group_id": "default",
                        "name": "默认分组",
                        "enabled": True,
                        "watch_users": ["NASA"],
                        "push_targets": [target],
                    }
                ],
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("default", "NASA", ["100"])
        await scheduler.storage.set_scan_watermark("default", "NASA", ["100"])

        result = await scheduler.run_check(
            reason="test_summary_enabled_run_check", group_name="default"
        )

        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(len(sender.summary_sends), 1)
        self.assertEqual(sender.summary_sends[0][0], target)
        self.assertIn("1 位博主", sender.summary_sends[0][1])
        self.assertEqual(len(sender.sent), 1)

    async def test_run_check_ordinary_batches_summary_disabled_suppresses_send_summary(
        self,
    ):
        target = "telegram:FriendMessage:1"
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": [self._make_tweet("NASA", "101")],
                        "scanned_status_ids": ["101", "100"],
                        "anchor_status_ids": ["101", "100"],
                    }
                ]
            }
        )
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "push": {"send_batch_summary_enabled": False},
                "tweet_groups": [
                    {
                        "group_id": "default",
                        "name": "默认分组",
                        "enabled": True,
                        "watch_users": ["NASA"],
                        "push_targets": [target],
                    }
                ],
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("default", "NASA", ["100"])
        await scheduler.storage.set_scan_watermark("default", "NASA", ["100"])

        result = await scheduler.run_check(
            reason="test_summary_disabled_run_check", group_name="default"
        )

        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(sender.summary_sends, [])
        self.assertEqual(len(sender.sent), 1)

    async def test_post_send_bookkeeping_exception_does_not_add_failed_history(self):
        target = "telegram:FriendMessage:1"
        sender = _RaisingPostSendSender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "scheduled_fetch_limit": 1,
            },
            nitter=_MultiUserNitter({"NASA": [self._make_tweet("NASA", "204")]}),
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        await scheduler.run_check(reason="test_post_send_bookkeeping")

        self.assertIn("204", await scheduler.storage.get_seen_ids("global", "NASA"))
        history = await scheduler.storage.get_push_history("global", "NASA")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].delivery_status, "success")
        self.assertEqual(history[0].delivery_error, "")

    async def test_merged_post_send_bookkeeping_exception_does_not_add_failed_history(
        self,
    ):
        target = "aiocqhttp:GroupMessage:1"
        sender = _RaisingPostSendSender(merge_targets={target})
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "scheduled_fetch_limit": 1,
                "merge_tweet_threshold": 1,
            },
            nitter=_MultiUserNitter({"NASA": [self._make_tweet("NASA", "205")]}),
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        await scheduler.run_check(reason="test_merged_post_send_bookkeeping")

        self.assertIn("205", await scheduler.storage.get_seen_ids("global", "NASA"))
        history = await scheduler.storage.get_push_history("global", "NASA")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].delivery_status, "success")
        self.assertEqual(history[0].delivery_error, "")

    async def test_partial_failed_push_records_history_and_marks_seen(self):
        target = "lark:GroupMessage:chat-1"
        sender = _PartialDeliverySender()
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "201"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "scheduled_fetch_limit": 1,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test_partial_failed_history")

        self.assertEqual(result.pushed_target_successes, 0)
        self.assertEqual(result.pushes[0].success_targets, 0)
        self.assertIn("201", await scheduler.storage.get_seen_ids("global", "NASA"))
        history = await scheduler.storage.get_push_history("global", "NASA")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].status_id, "201")
        self.assertEqual(history[0].target_umo, target)
        self.assertEqual(history[0].delivery_status, "partial_failed")
        self.assertEqual(history[0].delivery_error, "media failed")

    async def test_successful_partial_media_delivery_marks_seen_and_history(self):
        target = "lark:GroupMessage:chat-1"
        sender = _SuccessfulPartialDeliverySender(report_delivered_ids=False)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "201"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "scheduled_fetch_limit": 1,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test_partial_media_complete")

        self.assertEqual(result.pushed_target_successes, 1)
        self.assertEqual(result.pushes[0].success_targets, 1)
        self.assertIn("201", await scheduler.storage.get_seen_ids("global", "NASA"))
        history = await scheduler.storage.get_push_history("global", "NASA")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].delivery_status, "partial_failed")
        self.assertEqual(history[0].delivery_error, "media failed")

    async def test_partial_failed_without_delivered_ids_records_failed_history_and_marks_seen(
        self,
    ):
        target = "lark:GroupMessage:chat-1"
        sender = _PartialDeliverySender(report_delivered_ids=False)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "201"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "scheduled_fetch_limit": 1,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(
            reason="test_partial_failed_without_delivered_ids"
        )

        self.assertEqual(result.pushed_target_successes, 0)
        self.assertIn("201", await scheduler.storage.get_seen_ids("global", "NASA"))
        history = await scheduler.storage.get_push_history("global", "NASA")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].delivery_status, "failed")
        self.assertEqual(history[0].delivery_error, "media failed")

    def test_partial_failed_without_delivery_details_normalizes_to_failed(self):
        outcome = types.SimpleNamespace(
            success=False,
            error="",
            delivery_status="partial_failed",
            delivery_error="",
            delivered_status_ids=(),
        )

        self.assertEqual(
            NitterTweetScheduler._delivery_history_status(outcome), "failed"
        )
        self.assertEqual(NitterTweetScheduler._delivery_history_error(outcome), "")

    async def test_merged_partial_history_only_records_delivered_status_ids(self):
        target = "aiocqhttp:GroupMessage:1"
        sender = _PartialMergedDeliverySender(
            ["101"],
            merge_targets={target},
        )
        nitter = _MultiUserNitter(
            {
                "NASA": [self._make_tweet("NASA", "101")],
                "NASAHubble": [self._make_tweet("NASAHubble", "201")],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "NASAHubble"],
                "push_targets": [target],
                "scheduled_fetch_limit": 1,
                "merge_tweet_threshold": 2,
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.add_seen_ids("global", "NASAHubble", ["200"])

        result = await scheduler.run_check(reason="test_merged_partial_history")

        self.assertEqual(result.merged_push_success_targets, 0)
        nasa_history = await scheduler.storage.get_push_history("global", "NASA")
        hubble_history = await scheduler.storage.get_push_history(
            "global", "NASAHubble"
        )
        self.assertEqual([row.status_id for row in nasa_history], ["101"])
        self.assertEqual(nasa_history[0].delivery_status, "partial_failed")
        self.assertEqual(hubble_history, [])
        self.assertIn("101", await scheduler.storage.get_seen_ids("global", "NASA"))
        self.assertIn(
            "201", await scheduler.storage.get_seen_ids("global", "NASAHubble")
        )

    async def test_merged_failed_push_records_history_and_marks_seen(self):
        target = "aiocqhttp:GroupMessage:1"
        sender = _Sender(success=False, merge_targets={target})
        nitter = _MultiUserNitter({"NASA": [self._make_tweet("NASA", "301")]})
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "scheduled_fetch_limit": 1,
                "merge_tweet_threshold": 1,
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        first = await scheduler.run_check(reason="test_merged_failed_history")

        self.assertEqual(first.merged_push_success_targets, 0)
        self.assertIn("301", await scheduler.storage.get_seen_ids("global", "NASA"))
        history = await scheduler.storage.get_push_history("global", "NASA")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].delivery_status, "failed")
        self.assertEqual(history[0].delivery_error, "send failed")
        second = await scheduler.run_check(reason="test_merged_failed_history_again")
        self.assertEqual(second.new_tweet_count, 0)

    async def test_merged_send_exception_records_history_and_marks_seen(self):
        target = "aiocqhttp:GroupMessage:1"
        sender = _RaisingMergedSender(merge_targets={target})
        nitter = _MultiUserNitter({"NASA": [self._make_tweet("NASA", "302")]})
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "scheduled_fetch_limit": 1,
                "merge_tweet_threshold": 1,
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        await scheduler.run_check(reason="test_merged_exception_history")

        self.assertIn("302", await scheduler.storage.get_seen_ids("global", "NASA"))
        history = await scheduler.storage.get_push_history("global", "NASA")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].delivery_status, "failed")
        self.assertEqual(history[0].delivery_error, "merge crashed")
        second = await scheduler.run_check(reason="test_merged_exception_history_again")
        self.assertEqual(second.new_tweet_count, 0)

    async def test_media_only_ready_sends_without_translation_or_body(self):
        events = []
        target = "telegram:FriendMessage:1"
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": [self._make_tweet("NASA", "101")],
                        "scanned_status_ids": ["101", "100"],
                        "anchor_status_ids": ["101", "100"],
                    }
                ]
            }
        )
        media = _StatusMedia({"101": ("ready", Path("101.jpg"))}, events)
        translator = _RecordingTranslator(events)
        sender = _Sender(events=events)
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "send_image_attachments": True,
                "max_media_per_tweet": 4,
                "tweet_groups": [
                    {
                        "group_id": "media",
                        "name": "媒体分组",
                        "enabled": True,
                        "watch_users": ["NASA"],
                        "push_targets": [target],
                        "media_only_enabled": True,
                    }
                ],
            },
            nitter=nitter,
            media=media,
            sender=sender,
            translator=translator,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("media", "NASA", ["100"])
        await scheduler.storage.set_scan_watermark("media", "NASA", ["100"])

        result = await scheduler.run_check(
            reason="test_media_only_ready", group_name="media"
        )

        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(sender.media_only_flags, [True])
        self.assertEqual(
            [event.split(":", 1)[0] for event in events],
            [
                "media",
                "send",
                "cleanup",
            ],
        )
        self.assertFalse(any(event.startswith("translate:") for event in events))
        self.assertEqual(
            await scheduler.storage.get_seen_ids("media", "NASA"), ["101", "100"]
        )
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("media"),
            {"NASA": ["101", "100"]},
        )
        self.assertEqual(len(sender.summary_sends), 1)
        self.assertIn("1 位博主", sender.summary_sends[0][1])
        self.assertIn("1 条新推文", sender.summary_sends[0][1])

    async def test_media_only_policy_skip_advances_seen_without_sending(self):
        target = "telegram:FriendMessage:1"
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": [self._make_tweet("NASA", "101")],
                        "scanned_status_ids": ["101", "100"],
                        "anchor_status_ids": ["101", "100"],
                    }
                ]
            }
        )
        sender = _Sender()
        media = _StatusMedia({"101": ("policy_skipped", None)})
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "send_image_attachments": True,
                "max_media_per_tweet": 4,
                "tweet_groups": [
                    {
                        "group_id": "media",
                        "name": "媒体分组",
                        "enabled": True,
                        "watch_users": ["NASA"],
                        "push_targets": [target],
                        "media_only_enabled": True,
                    }
                ],
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("media", "NASA", ["100"])
        await scheduler.storage.set_scan_watermark("media", "NASA", ["100"])

        result = await scheduler.run_check(
            reason="test_media_only_policy", group_name="media"
        )

        self.assertEqual(result.media_only_skipped, 1)
        self.assertEqual(sender.sent, [])
        self.assertEqual(
            await scheduler.storage.get_seen_ids("media", "NASA"), ["101", "100"]
        )
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("media"),
            {"NASA": ["101", "100"]},
        )

    async def test_media_only_transient_failure_marks_seen_and_advances_watermark(self):
        target = "telegram:FriendMessage:1"
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": [self._make_tweet("NASA", "101")],
                        "scanned_status_ids": ["101", "100"],
                        "anchor_status_ids": ["101", "100"],
                    }
                ]
            }
        )
        sender = _Sender()
        media = _StatusMedia({"101": ("transient_failure", None)})
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "send_image_attachments": True,
                "max_media_per_tweet": 4,
                "tweet_groups": [
                    {
                        "group_id": "media",
                        "name": "媒体分组",
                        "enabled": True,
                        "watch_users": ["NASA"],
                        "push_targets": [target],
                        "media_only_enabled": True,
                    }
                ],
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("media", "NASA", ["100"])
        await scheduler.storage.set_scan_watermark("media", "NASA", ["100"])

        first = await scheduler.run_check(
            reason="test_media_only_retry_first", group_name="media"
        )

        self.assertEqual(first.media_only_skipped, 1)
        self.assertEqual(first.media_only_retrying, 0)
        self.assertEqual(sender.sent, [])
        self.assertEqual(
            await scheduler.storage.get_seen_ids("media", "NASA"), ["101", "100"]
        )
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("media"),
            {"NASA": ["101", "100"]},
        )

        media.statuses["101"] = ("ready", Path("101.jpg"))
        second = await scheduler.run_check(
            reason="test_media_only_retry_second", group_name="media"
        )

        self.assertEqual(second.new_tweet_count, 0)
        self.assertEqual(sender.sent, [])
        self.assertEqual(
            await scheduler.storage.get_seen_ids("media", "NASA"), ["101", "100"]
        )
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("media"),
            {"NASA": ["101", "100"]},
        )

    async def test_concurrent_prepare_sends_in_completion_order(self):
        target = "telegram:FriendMessage:1"
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": [
                            self._make_tweet("NASA", "101"),
                            self._make_tweet("NASA", "102"),
                        ],
                        "scanned_status_ids": ["101", "102", "100"],
                        "anchor_status_ids": ["101", "102", "100"],
                    }
                ]
            }
        )
        events = []
        sender = _Sender(events=events)
        translator = _OutOfOrderTranslator(events)
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "send_image_attachments": True,
                "concurrent_prepare_enabled": True,
                "prepare_concurrency": 2,
                "tweet_groups": [
                    {
                        "group_id": "media",
                        "name": "媒体分组",
                        "enabled": True,
                        "watch_users": ["NASA"],
                        "push_targets": [target],
                    }
                ],
            },
            nitter=nitter,
            sender=sender,
            translator=translator,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("media", "NASA", ["100"])
        await scheduler.storage.set_scan_watermark("media", "NASA", ["100"])

        await scheduler.run_check(reason="test_completion_order", group_name="media")

        self.assertEqual([item[3] for item in sender.sent], [["102"], ["101"]])

    def test_media_only_renderer_does_not_leak_body_or_link(self):
        renderer = TweetMessageRenderer(
            send_image_attachments=True,
            send_video_attachments=True,
        )
        tweet = self._make_tweet("NASA", "101")
        tweet.text = "secret body"
        tweet.translation = "secret translation"
        tweet.media = [
            TweetMedia("image", "https://example.test/101.jpg", path=Path("101.jpg"))
        ]

        text = renderer.format_plain(
            "NASA",
            "https://nitter.test",
            [tweet],
            media_only=True,
        )

        self.assertIn("@NASA", text)
        self.assertNotIn("secret body", text)
        self.assertNotIn("secret translation", text)
        self.assertNotIn("https://x.com", text)

    def test_media_only_onebot_video_retry_does_not_leak_link(self):
        renderer = TweetMessageRenderer(
            send_image_attachments=True,
            send_video_attachments=True,
        )
        tweet = self._make_tweet("NASA", "101")
        tweet.text = "secret body"
        tweet.media = [
            TweetMedia("video", "https://example.test/101.mp4", path=Path("101.mp4"))
        ]

        nodes = renderer.build_merged_onebot_nodes_for_uin(
            10000,
            [("NASA", "https://nitter.test", [tweet])],
            exclude_videos=True,
            media_only=True,
        )
        rendered = repr(nodes)

        self.assertIn("@NASA", rendered)
        self.assertNotIn("secret body", rendered)
        self.assertNotIn("https://x.com", rendered)

    async def test_media_only_default_event_fallback_keeps_author_only(self):
        sender = TweetSender({})
        adapter = DefaultDeliveryAdapter(
            sender,
            types.SimpleNamespace(
                should_split_qq_direct_videos=False,
                should_split_qq_direct_images=False,
            ),
        )
        sent_chains = []

        async def fake_send_event_chain(event, chain, label):
            del event, label
            sent_chains.append(chain)
            return SendAttempt(success=True)

        sender._send_event_chain = fake_send_event_chain
        tweet = self._make_tweet("NASA", "101")
        tweet.text = "secret body"
        tweet.translation = "secret translation"

        result = await adapter._send_event_fallback(
            object(),
            "NASA",
            "https://nitter.test",
            [tweet],
            media_only=True,
        )

        self.assertTrue(result)
        self.assertEqual(len(sent_chains), 1)
        chain = sent_chains[0]
        components = getattr(chain, "components", getattr(chain, "chain", []))
        rendered = repr([getattr(component, "text", "") for component in components])
        self.assertIn("@NASA", rendered)
        self.assertNotIn("secret body", rendered)
        self.assertNotIn("secret translation", rendered)
        self.assertNotIn("https://x.com", rendered)

    async def test_scheduler_backlog_is_sent_across_rounds_without_loss(self):
        tweets = [
            self._make_tweet("NASA", str(status_id))
            for status_id in range(110, 100, -1)
        ]
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": tweets,
                        "scanned_status_ids": [
                            str(status_id) for status_id in range(110, 100, -1)
                        ],
                        "latest_status_id": "110",
                    }
                ]
            }
        )
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 5,
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.set_scan_watermark("global", "NASA", "100")

        first = await scheduler.run_check(reason="test_backlog_first")
        second = await scheduler.run_check(reason="test_backlog_second")

        sent_ids = [status_id for item in sender.sent for status_id in item[3]]
        self.assertEqual((first.new_tweet_count, second.new_tweet_count), (10, 0))
        self.assertEqual(
            sent_ids, [str(status_id) for status_id in range(110, 100, -1)]
        )
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("global"),
            {"NASA": [str(status_id) for status_id in range(110, 100, -1)]},
        )

    async def test_failed_old_tweet_advances_watermark_without_retry(self):
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": [
                            self._make_tweet("NASA", "102"),
                            self._make_tweet("NASA", "101"),
                        ],
                        "scanned_status_ids": ["102", "101"],
                        "latest_status_id": "102",
                    }
                ]
            }
        )
        sender = _FailOnceStatusSender("101")
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 5,
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.set_scan_watermark("global", "NASA", "100")

        first = await scheduler.run_check(reason="test_gap_first")
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("global"),
            {"NASA": ["102", "101"]},
        )
        second = await scheduler.run_check(reason="test_gap_retry")

        self.assertEqual((first.new_tweet_count, second.new_tweet_count), (2, 0))
        self.assertEqual(
            [status_id for item in sender.sent for status_id in item[3]],
            ["102", "101"],
        )
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("global"),
            {"NASA": ["102", "101"]},
        )

    async def test_empty_or_filtered_initial_scan_allows_next_tweet(self):
        for username, initial_scan in (
            (
                "NASA",
                {"scanned_status_ids": ["100"], "latest_status_id": "100"},
            ),
            ("OpenAI", {"scanned_status_ids": [], "latest_status_id": ""}),
        ):
            with self.subTest(username=username, initial_scan=initial_scan):
                nitter = _SchedulerNitter(
                    {
                        username: [
                            initial_scan,
                            {
                                "tweets": [self._make_tweet(username, "101")],
                                "scanned_status_ids": ["101"],
                                "latest_status_id": "101",
                            },
                        ]
                    }
                )
                sender = _Sender()
                scheduler = self._create_scheduler(
                    {
                        "schedule_enabled": True,
                        "watch_users": [username],
                        "push_targets": ["telegram:FriendMessage:1"],
                        "scheduled_fetch_limit": 5,
                        "send_target_interval": 0,
                        "send_user_interval": 0,
                    },
                    nitter=nitter,
                    sender=sender,
                )
                await scheduler.storage.migrate_and_sync(
                    scheduler._schedule_groups(log_invalid_targets=False)
                )

                first = await scheduler.run_check(reason="test_empty_initial")
                second = await scheduler.run_check(reason="test_empty_next")

                self.assertEqual(first.new_tweet_count, 0)
                self.assertEqual(second.new_tweet_count, 1)
                self.assertEqual(sender.sent[-1][3], ["101"])

    async def test_empty_scan_after_initialization_preserves_watermark(self):
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "scanned_status_ids": ["100"],
                        "latest_status_id": "100",
                    },
                    {
                        "scanned_status_ids": [],
                        "latest_status_id": "",
                    },
                    {
                        "tweets": [
                            self._make_tweet("NASA", "101"),
                            self._make_tweet("NASA", "99"),
                        ],
                        "scanned_status_ids": ["101", "100", "99"],
                        "latest_status_id": "101",
                    },
                ]
            }
        )
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 5,
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        await scheduler.run_check(reason="test_empty_after_initial")
        await scheduler.run_check(reason="test_empty_after_initial_empty")
        result = await scheduler.run_check(reason="test_empty_after_initial_next")

        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(sender.sent[-1][3], ["101"])
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("global"),
            {"NASA": ["101", "100", "99"]},
        )

    async def test_incomplete_scan_does_not_advance_seen_or_watermark(self):
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": [self._make_tweet("NASA", "101")],
                        "scanned_status_ids": ["101"],
                        "latest_status_id": "101",
                        "complete": False,
                    }
                ]
            }
        )
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 5,
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.set_scan_watermark("global", "NASA", "100")

        result = await scheduler.run_check(reason="test_incomplete_scan")

        self.assertEqual(result.new_tweet_count, 0)
        self.assertEqual(sender.sent, [])
        self.assertEqual(
            await scheduler.storage.get_seen_ids("global", "NASA"), ["100"]
        )
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("global"),
            {"NASA": ["100"]},
        )

    async def test_ordinary_targets_send_per_account_but_qq_merges_at_end(self):
        events = []
        media = _Media()
        sender = _Sender(
            merge_targets={"aiocqhttp:GroupMessage:1"},
            events=events,
        )
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "101"),
                    self._make_tweet("NASA", "100"),
                ],
                "NASAHubble": [
                    self._make_tweet("NASAHubble", "201"),
                    self._make_tweet("NASAHubble", "200"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "NASAHubble"],
                "push_targets": [
                    "telegram:FriendMessage:1",
                    "aiocqhttp:GroupMessage:1",
                ],
                "scheduled_fetch_limit": 2,
                "merge_tweet_threshold": 2,
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.add_seen_ids("global", "NASAHubble", ["200"])

        result = await scheduler.run_check(reason="test_immediate_mixed_merge")

        self.assertEqual(
            events,
            [
                "fetch:NASA",
                "fetch:NASAHubble",
                "send:telegram:FriendMessage:1:NASA",
                "send:telegram:FriendMessage:1:NASAHubble",
                "merged:aiocqhttp:GroupMessage:1",
            ],
        )
        self.assertEqual(result.push_mode, "mixed")
        self.assertEqual(result.new_tweet_count, 2)
        self.assertEqual(result.pushed_target_successes, 3)
        self.assertEqual(result.pushed_target_attempts, 3)
        self.assertEqual(
            sender.merged_sent,
            [
                (
                    "aiocqhttp:GroupMessage:1",
                    [
                        ("NASA", "https://nitter.test", ["101"]),
                        ("NASAHubble", "https://nitter.test", ["201"]),
                    ],
                )
            ],
        )
        self.assertEqual(media.cleaned, 2)
        self.assertEqual(len(sender.merged_batch_summaries), 1)
        merged_summary = sender.merged_batch_summaries[0][1]
        self.assertIn("📬", merged_summary)
        self.assertIn("2 位博主", merged_summary)
        self.assertIn("2 条新推文", merged_summary)
        self.assertIn("默认分组", merged_summary)

    async def test_serial_prepare_cancellation_cleans_buffered_and_inflight_media(self):
        target = "aiocqhttp:GroupMessage:1"
        media = _BlockingMedia("101")
        sender = _Sender(merge_targets={target})
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "102"),
                    self._make_tweet("NASA", "101"),
                ]
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "merge_tweet_threshold": 2,
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        task = asyncio.create_task(
            scheduler.run_check(reason="test_serial_prepare_cancel")
        )
        await asyncio.wait_for(media.all_attached.wait(), timeout=1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(media.attached_ids, ["102", "101"])
        self.assertEqual(media.cleaned_ids, ["102", "101"])
        self.assertEqual(
            await scheduler.storage.get_seen_ids("global", "NASA"),
            ["100"],
        )

    async def test_concurrent_prepare_cancellation_cleans_all_started_media(self):
        target = "aiocqhttp:GroupMessage:1"
        media = _BlockingMedia("102")
        sender = _Sender(merge_targets={target})
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "102"),
                    self._make_tweet("NASA", "101"),
                ]
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [target],
                "merge_tweet_threshold": 2,
                "concurrent_prepare_enabled": True,
                "prepare_concurrency": 2,
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        task = asyncio.create_task(
            scheduler.run_check(reason="test_concurrent_prepare_cancel")
        )
        await asyncio.wait_for(media.all_attached.wait(), timeout=1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertCountEqual(media.attached_ids, ["101", "102"])
        self.assertCountEqual(media.cleaned_ids, ["101", "102"])
        self.assertEqual(len(media.cleaned_ids), 2)
        self.assertEqual(
            await scheduler.storage.get_seen_ids("global", "NASA"),
            ["100"],
        )

    async def test_telegram_flood_control_waits_and_retries_same_message(self):
        sender = TweetSender({})
        calls = []
        sleep_calls = []

        class _Context:
            async def send_message(self, umo, chain):
                del chain
                calls.append(umo)
                if len(calls) == 1:
                    raise RuntimeError("Flood control exceeded. Retry in 18 seconds")
                return True

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch.object(telegram_delivery_module.asyncio, "sleep", fake_sleep):
            attempt = await sender._send_context_message(
                _Context(),
                "telegram:GroupMessage:-1001",
                _MessageChain([_Plain("hello")]),
                "direct scheduled tweets",
            )

        self.assertTrue(attempt.success)
        self.assertEqual(calls, ["telegram:GroupMessage:-1001"] * 2)
        self.assertEqual(sleep_calls, [19.0])

    async def test_telegram_flood_control_retry_failure_skips_fallback(self):
        sender = TweetSender({})
        calls = []
        sleep_calls = []

        class _Context:
            async def send_message(self, umo, chain):
                del chain
                calls.append(umo)
                raise RuntimeError("Flood control exceeded. Retry in 18 seconds")

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch.object(telegram_delivery_module.asyncio, "sleep", fake_sleep):
            outcome = await sender._send_direct_to_umo(
                _Context(),
                "telegram:GroupMessage:-1001",
                "NASA",
                "https://nitter.test",
                [self._make_tweet("NASA", "110")],
            )

        self.assertFalse(outcome.success)
        self.assertIn("Telegram 限流仍未解除", outcome.warning)
        self.assertEqual(calls, ["telegram:GroupMessage:-1001"] * 2)
        self.assertEqual(sleep_calls, [19.0])

    async def test_partial_target_failure_marks_seen_without_retrying_success(self):
        good_target = "telegram:FriendMessage:1"
        failed_target = "weixin_oc:FriendMessage:2"
        nitter = _SchedulerNitter(
            {
                "NASA": [
                    {
                        "tweets": [self._make_tweet("NASA", "101")],
                        "scanned_status_ids": ["101", "100"],
                        "latest_status_id": "101",
                    },
                    {
                        "tweets": [self._make_tweet("NASA", "101")],
                        "scanned_status_ids": ["101", "100"],
                        "latest_status_id": "101",
                    },
                ]
            }
        )
        sender = _Sender(failed_targets={failed_target})
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [good_target, failed_target],
                "send_target_interval": 0,
                "send_user_interval": 0,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        first = await scheduler.run_check(reason="partial_target_first")
        self.assertEqual(first.pushed_target_successes, 1)
        self.assertIn("101", await scheduler.storage.get_seen_ids("global", "NASA"))

        sender.failed_targets.clear()
        second = await scheduler.run_check(reason="partial_target_retry")
        self.assertEqual(second.new_tweet_count, 0)
        self.assertEqual(second.pushed_target_attempts, 0)
        self.assertEqual(len(sender.sent), 2)

    async def test_concurrent_fetch_passes_path_override_without_type_error(self):
        from unittest.mock import AsyncMock

        from media_support.client import NitterClient, SchedulerFetchResult
        from scheduler.runner_fetch import SchedulerFetchMixin

        client = NitterClient({"instances": ["http://127.0.0.1:8080"]})
        tweet = self._make_tweet("NASA", "101")
        expected = (
            "http://127.0.0.1:8080",
            SchedulerFetchResult(
                tweets=[tweet], scanned_status_ids=["101"], complete=True
            ),
        )

        with patch.object(
            client,
            "_fetch_tweets_for_scheduler_from_instances",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_inner:
            # 1. Direct call to client.fetch_tweets_for_scheduler_from_instances with path_override
            result = await client.fetch_tweets_for_scheduler_from_instances(
                "NASA",
                ["100"],
                ["http://127.0.0.1:8080"],
                start_index=0,
                skip_plain_text=True,
                retry_attempts=2,
                filter_reposts=True,
                path_override="NASA/media",
            )
            self.assertEqual(result, expected)
            mock_inner.assert_awaited_once_with(
                "NASA",
                ["100"],
                ["http://127.0.0.1:8080"],
                skip_plain_text=True,
                retry_attempts=2,
                total_retry_attempts_per_instance=False,
                filter_reposts=True,
                path_override="NASA/media",
            )

        # 2. Integration call through runner._fetch_group_user with concurrent=True
        runner = SchedulerFetchMixin()
        runner.nitter = client
        runner.config = {}
        runner._log_verbose_info = lambda *args, **kwargs: None
        runner._effective_filter_reposts = lambda group: True

        group = types.SimpleNamespace(
            group_id="test",
            group_type="blogger",
            is_tag_group=False,
            is_list_group=False,
        )
        with patch.object(
            client,
            "_fetch_tweets_for_scheduler_from_instances",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_inner:
            user_result = await runner._fetch_group_user(
                group,
                0,
                "NASA",
                20,
                skip_plain_text=True,
                scan_watermark=["100"],
                concurrent=True,
            )
            self.assertEqual(user_result.username, "NASA")
            self.assertIsNone(user_result.error)
            mock_inner.assert_awaited_once_with(
                "NASA",
                ["100"],
                ["http://127.0.0.1:8080"],
                skip_plain_text=True,
                retry_attempts=2,
                total_retry_attempts_per_instance=False,
                filter_reposts=True,
                path_override="NASA/media",
            )
