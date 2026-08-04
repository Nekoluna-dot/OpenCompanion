import os

import pytest

from bucket_manager import BucketManager
from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.protocol.schemas import MemoryType


class FakeEmbeddingEngine:
    enabled = True

    async def generate_and_store(self, bucket_id, content):
        return True

    def delete_embedding(self, bucket_id):
        return None


@pytest.fixture
def config(tmp_path):
    buckets_dir = tmp_path / "buckets"
    for dirname in ("permanent", "dynamic", "archive", "feel", "plans", "letters"):
        (buckets_dir / dirname).mkdir(parents=True, exist_ok=True)
    return {
        "buckets_dir": str(buckets_dir),
        "merge_threshold": 75,
        "matching": {"fuzzy_threshold": 30, "max_results": 10},
        "wikilink": {"enabled": False},
        "scoring_weights": {},
        "embedding": {"enabled": False, "api_key": ""},
    }


@pytest.fixture
def fake_embedding_engine():
    return FakeEmbeddingEngine()


@pytest.mark.asyncio
async def test_bucket_manager_create_records_v3_event_without_changing_markdown_behavior(config, fake_embedding_engine) -> None:
    runtime = LegacyRuntime.from_config(config)
    manager = BucketManager(config, embedding_engine=fake_embedding_engine, v3_runtime=runtime)

    bucket_id = await manager.create(
        content="legacy write",
        bucket_type="permanent",
        importance=8,
        domain=["integration"],
    )
    bucket = await manager.get(bucket_id)
    events = runtime.fabric.replay_events()

    assert bucket is not None
    assert bucket["content"] == "legacy write"
    assert os.path.exists(bucket["path"])
    assert len(events) == 1
    assert events[0].memory_type == MemoryType.PERMANENT
    assert events[0].source_chain == ("legacy_bucket_manager", "create")
    assert events[0].metadata["legacy_bucket_id"] == bucket_id


@pytest.mark.asyncio
async def test_bucket_manager_update_delete_and_archive_record_v3_lifecycle_events(config, fake_embedding_engine) -> None:
    runtime = LegacyRuntime.from_config(config)
    manager = BucketManager(config, embedding_engine=fake_embedding_engine)
    manager.attach_v3_runtime(runtime)
    bucket_id = await manager.create(content="first", bucket_type="dynamic")

    assert await manager.update(bucket_id, content="second")
    assert await manager.delete(bucket_id)
    archived_id = await manager.create(content="third", bucket_type="dynamic")
    assert await manager.archive(archived_id)

    actions = [event.metadata["legacy_action"] for event in runtime.fabric.replay_events()]
    assert actions == ["create", "update", "delete", "create", "archive"]


@pytest.mark.asyncio
async def test_bucket_manager_v3_recording_failure_does_not_break_legacy_create(config, fake_embedding_engine) -> None:
    class BrokenRuntime:
        def record_bucket_event(self, **_kwargs):
            raise RuntimeError("v2.4.0 offline")

    manager = BucketManager(config, embedding_engine=fake_embedding_engine, v3_runtime=BrokenRuntime())

    bucket_id = await manager.create(content="still works")

    assert await manager.get(bucket_id) is not None
