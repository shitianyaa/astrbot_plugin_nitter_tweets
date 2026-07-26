from __future__ import annotations

import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from media_support import service as service_module
from media_support.cache import MediaCacheMixin
from media_support.service import MediaService
from shared import TweetMedia


class _Cache(MediaCacheMixin):
    def __init__(self, root: Path):
        self.cache_dir = root / "cache"
        self.legacy_cache_dir = root / "legacy"
        self.cache_dir.mkdir()
        self.legacy_cache_dir.mkdir()


@pytest.fixture(autouse=True)
def _clear_process_leases():
    with MediaCacheMixin._lease_lock:
        MediaCacheMixin._active_leases.clear()
    yield
    with MediaCacheMixin._lease_lock:
        MediaCacheMixin._active_leases.clear()


def _tweet(media: TweetMedia):
    return SimpleNamespace(media=[media])


def test_cleanup_accepts_string_paths_and_keeps_other_lease(tmp_path):
    cache = _Cache(tmp_path)
    path = cache.cache_dir / "shared.jpg"
    path.write_bytes(b"image")
    cache.register_media_path(path)
    cache.register_media_path(str(path))

    first = TweetMedia("image", "https://example.test/shared.jpg", path=str(path))
    second = TweetMedia("image", "https://example.test/shared.jpg", path=path)
    cache.cleanup_after_send([_tweet(first)])

    assert first.path is None
    assert path.exists()
    with MediaCacheMixin._lease_lock:
        assert MediaCacheMixin._active_leases[MediaCacheMixin._lease_key(path)] == 1

    result = cache.clear_cache()
    assert result.skipped_active == 1
    assert path.exists()

    cache.cleanup_after_send([_tweet(second)])
    assert second.path is None
    assert not path.exists()


def test_failed_unlink_does_not_leave_permanent_active_lease(tmp_path, monkeypatch):
    cache = _Cache(tmp_path)
    path = cache.cache_dir / "retry.jpg"
    path.write_bytes(b"image")
    media = TweetMedia("image", "https://example.test/retry.jpg", path=path)
    cache.register_media_path(path)

    original_unlink = Path.unlink
    state = {"failed": False}

    def flaky_unlink(self, *args, **kwargs):
        if self == path and not state["failed"]:
            state["failed"] = True
            raise PermissionError("busy")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    cache.cleanup_after_send([_tweet(media)])

    assert media.path == path
    with MediaCacheMixin._lease_lock:
        assert MediaCacheMixin._lease_key(path) not in MediaCacheMixin._active_leases

    result = cache.clear_cache()
    assert result.removed == 1
    assert not path.exists()


def test_clear_cache_preserves_legacy_staged_queue_media(tmp_path):
    cache = _Cache(tmp_path)
    normal = cache.cache_dir / "ordinary.jpg"
    staged_dir = cache.cache_dir / "staged" / "default" / "7"
    staged_dir.mkdir(parents=True)
    staged = staged_dir / "pending.jpg"
    normal.write_bytes(b"ordinary")
    staged.write_bytes(b"pending")

    result = cache.clear_cache()

    assert not normal.exists()
    assert staged.read_bytes() == b"pending"
    assert result.removed == 1
    assert result.skipped_dirs == 1


def test_download_registers_lease_before_return_and_cleanup_releases_it(
    tmp_path, monkeypatch
):
    service = object.__new__(MediaService)
    service.cache_dir = tmp_path / "cache"
    service.cache_dir.mkdir()
    service.max_bytes = 1024
    service.timeout = 5.0
    service.user_agent = "test"

    class _Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, _size):
            if getattr(self, "done", False):
                return b""
            self.done = True
            return b"payload"

    monkeypatch.setattr(service_module, "compat_urlopen", lambda *_args: _Response())
    media = TweetMedia("image", "https://example.test/a.jpg")
    path = service._download(media)

    assert path.exists()
    with MediaCacheMixin._lease_lock:
        assert MediaCacheMixin._active_leases[MediaCacheMixin._lease_key(path)] == 1

    media.path = path
    service.legacy_cache_dir = tmp_path / "legacy"
    service.legacy_cache_dir.mkdir()
    service.cleanup_after_send([_tweet(media)])
    assert media.path is None
    assert not path.exists()


def test_concurrent_same_url_downloads_share_one_final_file(tmp_path, monkeypatch):
    service = object.__new__(MediaService)
    service.cache_dir = tmp_path / "cache"
    service.cache_dir.mkdir()
    service.max_bytes = 1024
    service.timeout = 5.0
    service.user_agent = "test"
    barrier = Barrier(2)

    class _Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, _size):
            if getattr(self, "done", False):
                return b""
            self.done = True
            barrier.wait(timeout=10)
            return b"payload"

    monkeypatch.setattr(service_module, "compat_urlopen", lambda *_args: _Response())

    def download():
        return service._download(TweetMedia("image", "https://example.test/same.jpg"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = [future.result(timeout=20) for future in [executor.submit(download), executor.submit(download)]]

    assert paths[0] == paths[1]
    assert paths[0].read_bytes() == b"payload"
    with MediaCacheMixin._lease_lock:
        assert MediaCacheMixin._active_leases[MediaCacheMixin._lease_key(paths[0])] == 2

    service.legacy_cache_dir = tmp_path / "legacy"
    service.legacy_cache_dir.mkdir()
    first = TweetMedia("image", "https://example.test/same.jpg", path=paths[0])
    second = TweetMedia("image", "https://example.test/same.jpg", path=paths[1])
    service.cleanup_after_send([_tweet(first)])
    assert paths[0].exists()
    service.cleanup_after_send([_tweet(second)])
    assert not paths[0].exists()


@pytest.mark.asyncio
async def test_cancelled_thread_download_keeps_path_reachable_for_cleanup(
    tmp_path, monkeypatch
):
    service = object.__new__(MediaService)
    service.cache_dir = tmp_path / "cache"
    service.legacy_cache_dir = tmp_path / "legacy"
    service.cache_dir.mkdir()
    service.legacy_cache_dir.mkdir()
    path = service.cache_dir / "cancelled.jpg"
    started = Event()
    release = Event()

    def blocked_download(_media):
        started.set()
        assert release.wait(timeout=10)
        path.write_bytes(b"payload")
        service.register_media_path(path)
        return path

    monkeypatch.setattr(service, "_download_with_retries", blocked_download)
    media = TweetMedia("image", "https://example.test/cancelled.jpg")
    task = asyncio.create_task(service._download_media_path(media))
    assert await asyncio.to_thread(started.wait, 5)

    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert media.path == path
    with MediaCacheMixin._lease_lock:
        assert MediaCacheMixin._active_leases[MediaCacheMixin._lease_key(path)] == 1

    service.cleanup_after_send([_tweet(media)])
    assert media.path is None
    assert not path.exists()


@pytest.mark.asyncio
async def test_cancelled_later_media_keeps_all_downloaded_leases_reachable(
    tmp_path, monkeypatch
):
    service = object.__new__(MediaService)
    service.cache_dir = tmp_path / "cache"
    service.legacy_cache_dir = tmp_path / "legacy"
    service.cache_dir.mkdir()
    service.legacy_cache_dir.mkdir()
    service.send_image_attachments = True
    service.send_video_attachments = False
    service.max_per_tweet = 4
    first_path = service.cache_dir / "first.jpg"
    second_path = service.cache_dir / "second.jpg"
    second_started = asyncio.Event()
    calls = 0

    async def fake_download(media):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_path.write_bytes(b"first")
            service.register_media_path(first_path)
            return first_path
        second_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            second_path.write_bytes(b"second")
            service.register_media_path(second_path)
            media.path = second_path
            raise

    monkeypatch.setattr(service, "_download_media_path", fake_download)
    tweet = SimpleNamespace(
        media=[
            TweetMedia("image", "https://example.test/first.jpg"),
            TweetMedia("image", "https://example.test/second.jpg"),
        ]
    )
    task = asyncio.create_task(service._resolve_and_download_with_status(tweet))
    await second_started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [media.path for media in tweet.media] == [first_path, second_path]
    service.cleanup_after_send([tweet])
    assert not first_path.exists()
    assert not second_path.exists()
