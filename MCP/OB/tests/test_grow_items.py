"""grow 预拆分（items）模式测试。

issue 诉求：上层 AI 已拆好的正文应逐字入库，消除「廉价 LLM 二次拆分改写」这次失真。
硬承诺：
1. 传 items 时**绝不调用 digest / merge**（谁调谁炸），只调 analyze 打元数据；
2. 存进桶的正文与传入**一字不差**；
3. 同批共享 grow_batch_id；不传 items 时行为不变（走原 digest 路径）。
"""
from unittest.mock import MagicMock

import pytest

import tools._runtime as rt
from tools.grow import dispatch
from tools.grow.core import grow_items


class StubDehydrator:
    """items 模式只允许 analyze；digest/merge 一旦被调用即判定失真回归。"""

    def __init__(self):
        self.analyze_calls = 0

    async def analyze(self, content):
        self.analyze_calls += 1
        return {"domain": ["工作"], "valence": 0.6, "arousal": 0.4,
                "tags": ["标签"], "suggested_name": "事件"}

    async def digest(self, content):
        raise AssertionError("items 模式不允许调用 digest（会造成二次改写失真）")

    async def merge(self, old_content, new_content):
        raise AssertionError("items 模式不允许调用 merge（会压缩老+新）")


class NoopDecay:
    is_running = True

    async def ensure_started(self):
        return None

    def calculate_score(self, meta):
        return 1.0


@pytest.fixture
def grow_rt(bucket_mgr, monkeypatch):
    stub = StubDehydrator()
    monkeypatch.setattr(rt, "config", {"limits": {}, "merge_threshold": 75}, raising=False)
    monkeypatch.setattr(rt, "bucket_mgr", bucket_mgr, raising=False)
    monkeypatch.setattr(rt, "dehydrator", stub, raising=False)
    monkeypatch.setattr(rt, "decay_engine", NoopDecay(), raising=False)
    monkeypatch.setattr(rt, "logger", MagicMock(), raising=False)
    monkeypatch.setattr(rt, "fire_webhook", None, raising=False)
    return bucket_mgr, stub


@pytest.mark.asyncio
async def test_items_stored_verbatim_no_digest(grow_rt):
    bucket_mgr, stub = grow_rt
    original = [
        "昨天和产品经理开会，分歧在多租户 SaaS 的隐私边界。",
        "晚上把 grow 的 items 模式草稿写完了，明天验证。",
    ]
    out = await grow_items(list(original))

    assert "2条(预拆分·逐字)" in out
    assert stub.analyze_calls == 2  # 每条只打标一次

    # 正文一字不差地存进了桶
    buckets = await bucket_mgr.list_all(include_archive=False)
    stored = sorted(b["content"] for b in buckets)
    assert stored == sorted(original)


@pytest.mark.asyncio
async def test_items_share_batch_and_metadata(grow_rt):
    bucket_mgr, stub = grow_rt
    await grow_items(["第一条内容啊啊啊啊啊", "第二条内容哦哦哦哦哦"])
    buckets = await bucket_mgr.list_all(include_archive=False)
    batch_ids = {b["metadata"].get("grow_batch_id") for b in buckets}
    assert len(batch_ids) == 1 and next(iter(batch_ids))  # 同批共享一个非空 batch_id
    for b in buckets:
        assert b["metadata"].get("source_tool") == "grow"
        assert "工作" in (b["metadata"].get("domain") or [])


@pytest.mark.asyncio
async def test_empty_items_creates_nothing(grow_rt):
    bucket_mgr, stub = grow_rt
    out = await grow_items(["", "   ", None])
    assert "未创建任何桶" in out
    assert stub.analyze_calls == 0
    assert await bucket_mgr.list_all(include_archive=False) == []


@pytest.mark.asyncio
async def test_dict_items_take_content_field(grow_rt):
    bucket_mgr, stub = grow_rt
    await grow_items([{"content": "对象形式的一条正文内容"}, "字符串形式的一条正文内容"])
    buckets = await bucket_mgr.list_all(include_archive=False)
    stored = sorted(b["content"] for b in buckets)
    assert stored == sorted(["对象形式的一条正文内容", "字符串形式的一条正文内容"])


@pytest.mark.asyncio
async def test_dispatch_routes_to_items_when_provided(grow_rt):
    bucket_mgr, stub = grow_rt
    # 传 items 时忽略 content、走逐字路径（content 给一段会触发 digest 的长文也不该炸）
    out = await dispatch(content="x" * 100, items=["逐字入库的唯一正文条目内容"])
    assert "预拆分·逐字" in out
    buckets = await bucket_mgr.list_all(include_archive=False)
    assert [b["content"] for b in buckets] == ["逐字入库的唯一正文条目内容"]


@pytest.mark.asyncio
async def test_dispatch_without_items_unchanged(grow_rt):
    # 不传 items：长文仍走 digest 路径（stub.digest 会炸，grow_core 包成 RuntimeError）
    # → 证明默认路径没变、digest 仍在原路径被调用
    with pytest.raises(RuntimeError):
        await dispatch(content="这是一段超过三十个字的长文本内容需要走 digest 拆分路径来验证向后兼容性没有被破坏")
