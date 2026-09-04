"""EmojiLikeArbiter 协议单元测试。

纯 mock，不依赖 QQ 或框架。覆盖 7 个关键场景：
预占认输、单参与者快路径、双 Bot 并发恰好一赢、msg_time 轮转、
set 异常认输、fetch 异常降级、确定性排序。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.arbiter import ArbiterContext, EmojiLikeArbiter  # noqa: E402


class _SharedState:
    """模拟某条群消息上的表情贴法状态。"""

    def __init__(self) -> None:
        self.likes: dict[str, set[int]] = {}

    def add(self, emoji_id: int, uid: int) -> None:
        self.likes.setdefault(str(emoji_id), set()).add(uid)

    def users(self, emoji_id: int | str) -> list[int]:
        return sorted(self.likes.get(str(emoji_id), set()))


class _FakeBot:
    """模拟 CQHTTP Bot，通过 __getattr__ 转发（与 aiocqhttp.AsyncApi 一致）。"""

    def __init__(
        self,
        state: _SharedState,
        self_id: int,
        barrier: asyncio.Barrier | None = None,
        *,
        set_throws: bool = False,
        fetch_throws: bool = False,
    ) -> None:
        self.state = state
        self.self_id = self_id
        self.barrier = barrier
        self.fail_set = set_throws
        self.fail_fetch = fetch_throws
        self._first = False

    async def set_msg_emoji_like(
        self,
        message_id: int | None = None,
        emoji_id: int | None = None,
        emoji_type: str | None = None,
        set: bool = True,  # noqa: A002
        **kw: object,
    ) -> None:
        if self.fail_set:
            raise RuntimeError("set_msg_emoji_like rejected")
        if set:
            self.state.add(emoji_id, self.self_id)  # type: ignore[arg-type]

    async def fetch_emoji_like(
        self,
        message_id: int | None = None,
        emoji_id: str | None = None,
        emojiId: str | None = None,
        emojiType: str | None = None,
        count: int | None = None,
        **kw: object,
    ) -> dict:
        if self.fail_fetch:
            raise RuntimeError("fetch_emoji_like failed")
        eid = emojiId or emoji_id
        snapshot = list(self.state.users(eid))  # 先读快照
        if self.barrier is not None and not self._first:
            self._first = True
            await self.barrier.wait()  # Phase 1 对齐后再放行
        return {"emojiLikesList": [{"tinyId": u} for u in snapshot]}


arbiter = EmojiLikeArbiter()


def _ctx(bot: _FakeBot, msg_time: int = 0) -> ArbiterContext:
    return ArbiterContext(message_id=111, msg_time=msg_time, self_id=bot.self_id)


@pytest.mark.asyncio
async def test_phase1_preoccupied_loses_without_set():
    """A: 别人已贴 289 → 立即认输，不做任何 set。"""
    st = _SharedState()
    st.add(arbiter._EMOJI_ID, 999)
    bot = _FakeBot(st, 1)
    ok = await arbiter.compete(bot, _ctx(bot))
    assert ok is False


@pytest.mark.asyncio
async def test_single_participant_fast_path_wins():
    """B: 单参与者 → 快路径直接赢，不贴 124。"""
    st = _SharedState()
    bot = _FakeBot(st, 1)
    ok = await arbiter.compete(bot, _ctx(bot))
    assert ok is True
    # 贴了 289 但没贴 124
    assert 1 in st.users(arbiter._EMOJI_ID)
    assert st.users(arbiter._FEEDBACK_EMOJI_ID) == []


@pytest.mark.asyncio
async def test_two_bots_concurrent_exactly_one_wins():
    """C: 两 Bot 真实并发(msg_time=0) → 恰好一个赢。"""
    st = _SharedState()
    gate = asyncio.Barrier(2)
    b1 = _FakeBot(st, 1, gate)
    b2 = _FakeBot(st, 2, gate)
    r1, r2 = await asyncio.gather(
        arbiter.compete(b1, _ctx(b1, 0)),
        arbiter.compete(b2, _ctx(b2, 0)),
    )
    assert (r1, r2) == (True, False)
    assert st.users(arbiter._EMOJI_ID) == [1, 2]


@pytest.mark.asyncio
async def test_msg_time_rotation_flips_winner():
    """C2: msg_time=60 → 起点轮转 → 胜者翻转。"""
    st = _SharedState()
    gate = asyncio.Barrier(2)
    b1 = _FakeBot(st, 1, gate)
    b2 = _FakeBot(st, 2, gate)
    r1, r2 = await asyncio.gather(
        arbiter.compete(b1, _ctx(b1, 60)),
        arbiter.compete(b2, _ctx(b2, 60)),
    )
    assert (r1, r2) == (False, True)
    assert st.users(arbiter._EMOJI_ID) == [1, 2]


@pytest.mark.asyncio
async def test_set_throws_loses():
    """D: set_msg_emoji_like 抛异常 → 认输。"""
    st = _SharedState()
    bot = _FakeBot(st, 1, set_throws=True)
    ok = await arbiter.compete(bot, _ctx(bot))
    assert ok is False


@pytest.mark.asyncio
async def test_fetch_throws_degrades_to_win():
    """E: fetch_emoji_like 全抛异常 → 兜底算赢（优雅降级：API 不可用时不阻塞解析）。"""
    st = _SharedState()
    bot = _FakeBot(st, 1, fetch_throws=True)
    ok = await arbiter.compete(bot, _ctx(bot))
    assert ok is True


def test_decide_order_deterministic_and_rotates():
    """F: _decide_order 同输入同输出；msg_time+60 轮转。"""
    o1 = arbiter._decide_order([2, 1, 3], 1000)
    o2 = arbiter._decide_order([2, 1, 3], 1000)
    o3 = arbiter._decide_order([2, 1, 3], 1060)
    assert o1 == o2
    assert o3 != o1
