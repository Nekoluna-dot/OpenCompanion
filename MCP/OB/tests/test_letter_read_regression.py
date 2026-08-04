from unittest.mock import MagicMock

import pytest

import tools._runtime as rt
from tools.plan.core import letter_read


class DisabledEmbedding:
    enabled = False


def install_letter_runtime(bucket_mgr):
    rt.bucket_mgr = bucket_mgr
    rt.embedding_engine = DisabledEmbedding()
    rt.logger = MagicMock()


@pytest.mark.asyncio
async def test_letter_read_query_uses_keyword_filter_when_embedding_is_disabled(bucket_mgr):
    await bucket_mgr.create(
        content="A letter about apples and orchards.",
        bucket_type="letter",
        domain=["letter"],
    )
    await bucket_mgr.create(
        content="A letter about trains and stations.",
        bucket_type="letter",
        domain=["letter"],
    )
    install_letter_runtime(bucket_mgr)

    missing = await letter_read(query="nonexistent zebra phrase", limit=10)
    apples = await letter_read(query="orchards", limit=10)

    assert "没有找到匹配的信件" in missing
    assert "apples and orchards" in apples
    assert "trains and stations" not in apples
