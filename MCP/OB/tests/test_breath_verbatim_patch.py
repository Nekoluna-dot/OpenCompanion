import asyncio
import hashlib
from unittest.mock import MagicMock

import pytest

import tools._runtime as rt
from tools.breath import dispatch
from tools.breath._verbatim import render_stored_bucket
from tools.breath.importance import surface_by_importance
from tools.breath.search import surface_search


class ExplodingDehydrator:
    def __init__(self):
        self.calls = 0

    async def dehydrate(self, content, meta=None):
        self.calls += 1
        raise AssertionError("breath return path must not call the LLM")


class DisabledEmbedding:
    enabled = False


class ExplodingEmbedding:
    enabled = True

    async def search_similar_strict(self, query, top_k):
        raise AssertionError("exact bucket-id lookup must not call embedding")


class NoopDecay:
    is_running = True

    async def ensure_started(self):
        return None

    def calculate_score(self, meta):
        return float(meta.get("importance") or 5)


class OrderedBucketManager:
    def __init__(self, buckets):
        self.buckets = list(buckets)
        self.touched = []
        self.search_kwargs = {}

    async def search(self, query, **kwargs):
        self.search_kwargs = dict(kwargs)
        return list(self.buckets)

    async def touch_many(self, bucket_ids, ripple=False):
        self.touched.extend(bucket_ids)

    async def list_all(self, include_archive=False):
        return list(self.buckets)


def _install_runtime(bucket_mgr, dehydrator=None):
    rt.config = {"surfacing": {}}
    rt.bucket_mgr = bucket_mgr
    rt.decay_engine = NoopDecay()
    rt.dehydrator = dehydrator or ExplodingDehydrator()
    rt.embedding_engine = DisabledEmbedding()
    rt.logger = MagicMock()
    rt.fire_webhook = None
    rt.mark_op = None
    rt.record_v3_tool_event = lambda *_args, **_kwargs: None
    return rt.dehydrator


async def _search(query, **overrides):
    params = {
        "query": query,
        "max_results": 10,
        "max_tokens": 10000,
        "domain": "",
        "valence": -1,
        "arousal": -1,
        "tag_filter": [],
    }
    params.update(overrides)
    return await surface_search(**params)


def _returned_body(output: str, bucket_id: str, expected_length: int) -> str:
    marker = f"[bucket_id:{bucket_id}]"
    marker_at = output.index(marker)
    body_start = output.index("\n", marker_at) + 1
    return output[body_start:body_start + expected_length]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_query_single_bucket_returns_stored_content_exactly(bucket_mgr, monkeypatch):
    original = (
        "第二场风暴 你只是claude\n\n"
        "原话中的次数是三次，顺序是先确认、再等待、最后离开。\n"
        "这是一段普通叙述，不是任务清单。"
    )
    bucket_id = await bucket_mgr.create(content=original, domain=["记忆"], importance=8)
    stored_before = (await bucket_mgr.get(bucket_id))["content"]
    dehydrator = _install_runtime(bucket_mgr)
    monkeypatch.setattr("tools.breath.search.random.random", lambda: 1.0)

    output = await dispatch(
        query="第二场风暴 你只是claude",
        max_tokens=10000,
        max_results=10,
    )
    actual = _returned_body(output, bucket_id, len(stored_before))
    await asyncio.sleep(0)
    stored_after = (await bucket_mgr.get(bucket_id))["content"]

    assert actual == stored_before
    assert _sha256(actual) == _sha256(stored_before)
    assert stored_after == stored_before
    assert dehydrator.calls == 0
    assert "待办" not in output
    assert "\n- " not in output


@pytest.mark.asyncio
async def test_query_equal_to_bucket_id_reads_raw_content_without_indexes(
    bucket_mgr, monkeypatch
):
    original = "- 第一条原始 bullet\n- 第二条保留缩进\n  - 子项不能被摘要\n- 第三条"
    bucket_id = await bucket_mgr.create(
        content=original, domain=["记忆"], importance=10, pinned=True
    )
    dehydrator = _install_runtime(bucket_mgr)
    rt.embedding_engine = ExplodingEmbedding()

    async def unexpected_search(*args, **kwargs):
        raise AssertionError("exact bucket-id lookup must not call BM25/search")

    monkeypatch.setattr(bucket_mgr, "search", unexpected_search)

    output = await dispatch(query=bucket_id, max_tokens=10000)
    actual = _returned_body(output, bucket_id, len(original))
    await asyncio.sleep(0)

    assert actual == original
    assert _sha256(actual) == _sha256(original)
    assert dehydrator.calls == 0


@pytest.mark.asyncio
async def test_query_multiple_buckets_return_each_body_exactly(bucket_mgr, monkeypatch):
    contents = [
        "群星校验词：第一段。\n保留 [[原始双链]] 和标点；A=1。",
        "群星校验词：第二段。\n次数=7，先后顺序不能变化。\n",
    ]
    ids = [
        await bucket_mgr.create(content=content, domain=["测试"], importance=7)
        for content in contents
    ]
    stored = {bucket_id: (await bucket_mgr.get(bucket_id))["content"] for bucket_id in ids}
    dehydrator = _install_runtime(bucket_mgr)
    monkeypatch.setattr("tools.breath.search.random.random", lambda: 1.0)

    output = await _search("群星校验词")

    for bucket_id, expected in stored.items():
        actual = _returned_body(output, bucket_id, len(expected))
        assert actual == expected
        assert _sha256(actual) == _sha256(expected)
    assert dehydrator.calls == 0


@pytest.mark.asyncio
async def test_catalog_still_returns_metadata_without_body(bucket_mgr):
    body = "目录模式绝不能返回的完整私密正文。"
    await bucket_mgr.create(content=body, name="目录校验", domain=["测试"], importance=9)
    dehydrator = _install_runtime(bucket_mgr)

    output = await dispatch(catalog=True)

    assert "目录校验 | 测试 | 9" in output
    assert body not in output
    assert dehydrator.calls == 0


@pytest.mark.asyncio
async def test_token_budget_omits_whole_bucket_instead_of_truncating(monkeypatch):
    first = {
        "id": "first",
        "content": "第一条完整正文。",
        "metadata": {"type": "dynamic", "importance": 8, "domain": []},
    }
    second = {
        "id": "second",
        "content": "第二条正文绝不能只返回前半段。" * 20,
        "metadata": {"type": "dynamic", "importance": 7, "domain": []},
    }
    manager = OrderedBucketManager([first, second])
    dehydrator = _install_runtime(manager)
    monkeypatch.setattr("tools.breath.search.random.random", lambda: 1.0)
    _, first_cost = render_stored_bucket(first, "[bucket_id:first]")

    output = await _search("预算校验", max_tokens=first_cost)
    await asyncio.sleep(0)

    assert _returned_body(output, "first", len(first["content"])) == first["content"]
    assert "[bucket_id:second]" not in output
    assert second["content"][:20] not in output
    assert "token 预算不足" in output
    assert manager.touched == ["first"]
    assert dehydrator.calls == 0


@pytest.mark.asyncio
async def test_filters_and_importance_mode_remain_active(bucket_mgr, monkeypatch):
    keep_id = await bucket_mgr.create(
        content="过滤校验词：应当命中。",
        tags=["保留"],
        domain=["工作"],
        importance=9,
        valence=0.8,
        arousal=0.7,
    )
    wrong_domain_id = await bucket_mgr.create(
        content="过滤校验词：错误 domain。",
        tags=["保留"],
        domain=["私人"],
        importance=4,
    )
    wrong_tag_id = await bucket_mgr.create(
        content="过滤校验词：错误 tag。",
        tags=["忽略"],
        domain=["工作"],
        importance=4,
    )
    dehydrator = _install_runtime(bucket_mgr)
    original_search = bucket_mgr.search
    seen = {}

    async def recording_search(*args, **kwargs):
        seen.update(kwargs)
        return await original_search(*args, **kwargs)

    monkeypatch.setattr(bucket_mgr, "search", recording_search)
    monkeypatch.setattr("tools.breath.search.random.random", lambda: 1.0)

    query_output = await _search(
        "过滤校验词",
        domain="工作",
        valence=0.8,
        arousal=0.7,
        tag_filter=["保留"],
    )
    importance_output = await surface_by_importance(
        importance_min=8,
        max_tokens=10000,
        tag_filter=["保留"],
    )

    assert keep_id in query_output
    assert wrong_domain_id not in query_output
    assert wrong_tag_id not in query_output
    assert seen["domain_filter"] == ["工作"]
    assert seen["query_valence"] == 0.8
    assert seen["query_arousal"] == 0.7
    assert keep_id in importance_output
    assert wrong_domain_id not in importance_output
    assert wrong_tag_id not in importance_output
    assert dehydrator.calls == 0
