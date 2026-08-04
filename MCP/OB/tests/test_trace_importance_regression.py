from unittest.mock import MagicMock

import pytest

import tools._runtime as rt
from tools.breath.importance import surface_by_importance
from tools.trace.core import trace_core


class EchoDehydrator:
    async def dehydrate(self, content, meta=None):
        return content


def install_runtime(bucket_mgr):
    rt.config = {"surfacing": {}}
    rt.bucket_mgr = bucket_mgr
    rt.dehydrator = EchoDehydrator()
    rt.logger = MagicMock()
    rt.fire_webhook = None
    rt.mark_op = None


@pytest.mark.asyncio
async def test_trace_importance_update_refreshes_importance_breath(bucket_mgr):
    bucket_id = await bucket_mgr.create(
        content="Plain important memory should be demoted.",
        importance=10,
        domain=["rules"],
    )
    install_runtime(bucket_mgr)

    result = await trace_core(bucket_id, importance=8)
    bucket = await bucket_mgr.get(bucket_id)
    breath = await surface_by_importance(importance_min=9, max_tokens=10000, tag_filter=[])

    assert "importance=8" in result
    assert bucket["metadata"]["importance"] == 8
    assert bucket_id not in breath


@pytest.mark.asyncio
async def test_importance_breath_keeps_threshold_bucket_visible_when_tens_fill_cap(bucket_mgr):
    install_runtime(bucket_mgr)
    for i in range(21):
        await bucket_mgr.create(
            content=f"Higher-importance memory {i}",
            importance=10,
            domain=["rules"],
        )
    bucket_id = await bucket_mgr.create(
        content="Demoted-to-nine memory should still be visible at threshold nine.",
        importance=10,
        domain=["rules"],
    )

    result = await trace_core(bucket_id, importance=9)
    bucket = await bucket_mgr.get(bucket_id)
    breath = await surface_by_importance(importance_min=9, max_tokens=10000, tag_filter=[])

    assert "importance=9" in result
    assert bucket["metadata"]["importance"] == 9
    assert bucket_id in breath
    assert "[importance:9]" in breath


@pytest.mark.asyncio
async def test_trace_importance_update_on_pinned_bucket_does_not_report_fake_success(bucket_mgr):
    bucket_id = await bucket_mgr.create(
        content="Pinned memory keeps importance locked.",
        importance=10,
        pinned=True,
        domain=["rules"],
    )
    install_runtime(bucket_mgr)

    result = await trace_core(bucket_id, importance=8)
    bucket = await bucket_mgr.get(bucket_id)
    breath = await surface_by_importance(importance_min=9, max_tokens=10000, tag_filter=[])

    assert bucket["metadata"]["importance"] == 10
    assert bucket_id in breath
    assert "importance=8" not in result
    assert "pinned" in result
