import asyncio
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from bucket_manager import BucketManager
from embedding_engine import EmbeddingEngine
from embedding_outbox import EmbeddingOutbox, content_hash
from web import embedding as embedding_web


def _config(tmp_path, **embedding):
    return {
        "buckets_dir": str(tmp_path / "vault"),
        "embedding": {
            "enabled": True,
            "background_indexing": True,
            "retry_base_seconds": 0.01,
            "retry_max_seconds": 0.02,
            **embedding,
        },
    }


async def _wait_for(predicate, timeout=1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


class RecordingEngine:
    enabled = True

    def __init__(self):
        self.calls = []
        self.hashes = {}

    async def generate_and_store(self, bucket_id, content):
        self.calls.append((bucket_id, content))
        self.hashes[bucket_id] = content_hash(content)
        return True

    def list_all_ids(self):
        return list(self.hashes)

    def list_content_hashes(self):
        return dict(self.hashes)

    def delete_embedding(self, bucket_id):
        self.hashes.pop(bucket_id, None)


class BlockingEngine(RecordingEngine):
    def __init__(self, *, block_first=True):
        super().__init__()
        self.block_first = block_first
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_and_store(self, bucket_id, content):
        self.calls.append((bucket_id, content))
        if self.block_first and len(self.calls) == 1:
            self.started.set()
            await self.release.wait()
        self.hashes[bucket_id] = content_hash(content)
        return True


class FailingEngine(RecordingEngine):
    async def generate_and_store(self, bucket_id, content):
        self.calls.append((bucket_id, content))
        return False


class DisabledEngine(RecordingEngine):
    enabled = False


@pytest.mark.asyncio
async def test_background_indexing_never_blocks_markdown_write(tmp_path):
    config = _config(tmp_path)
    engine = BlockingEngine()
    manager = BucketManager(config, embedding_engine=engine)
    outbox = EmbeddingOutbox(config, manager, engine)
    manager.attach_embedding_outbox(outbox)

    await outbox.start(reconcile=False)
    try:
        bucket_id = await asyncio.wait_for(
            manager.create(content="memory survives a slow provider"),
            timeout=0.2,
        )
        bucket = await manager.get(bucket_id)

        assert bucket is not None
        assert bucket["content"] == "memory survives a slow provider"
        assert outbox.is_pending(bucket_id)
        await asyncio.wait_for(engine.started.wait(), timeout=0.5)

        engine.release.set()
        assert await outbox.wait_until_idle(timeout=1.0)
        assert engine.hashes[bucket_id] == content_hash(bucket["content"])
    finally:
        engine.release.set()
        await outbox.stop()


@pytest.mark.asyncio
async def test_retry_state_survives_restart_and_recovers(tmp_path):
    config = _config(tmp_path)
    failing = FailingEngine()
    manager = BucketManager(config, embedding_engine=failing)
    outbox = EmbeddingOutbox(config, manager, failing)
    manager.attach_embedding_outbox(outbox)

    await outbox.start(reconcile=False)
    bucket_id = await manager.create(content="retry me after restart")
    await _wait_for(lambda: outbox.status()["retrying"] == 1)
    await outbox.stop()

    payload = json.loads((tmp_path / "vault" / ".embedding_outbox.json").read_text("utf-8"))
    assert payload["items"][bucket_id]["attempts"] >= 1

    recovered = RecordingEngine()
    restarted = EmbeddingOutbox(config, manager, recovered)
    manager.embedding_engine = recovered
    manager.attach_embedding_outbox(restarted)
    await restarted.start(reconcile=False)
    try:
        assert await restarted.wait_until_idle(timeout=1.0)
        assert recovered.calls == [(bucket_id, "retry me after restart")]
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_content_changed_during_indexing_is_requeued(tmp_path):
    config = _config(tmp_path)
    engine = BlockingEngine()
    manager = BucketManager(config, embedding_engine=engine)
    outbox = EmbeddingOutbox(config, manager, engine)
    manager.attach_embedding_outbox(outbox)

    await outbox.start(reconcile=False)
    try:
        bucket_id = await manager.create(content="old content")
        await asyncio.wait_for(engine.started.wait(), timeout=0.5)
        assert await manager.update(bucket_id, content="new content")

        engine.release.set()
        assert await outbox.wait_until_idle(timeout=1.0)
        assert [content for _bucket_id, content in engine.calls] == [
            "old content",
            "new content",
        ]
        assert engine.hashes[bucket_id] == content_hash("new content")
    finally:
        engine.release.set()
        await outbox.stop()


@pytest.mark.asyncio
async def test_all_memory_types_persist_while_embedding_is_disabled(tmp_path):
    config = _config(tmp_path, enabled=False)
    engine = DisabledEngine()
    manager = BucketManager(config, embedding_engine=engine)
    outbox = EmbeddingOutbox(config, manager, engine)
    manager.attach_embedding_outbox(outbox)

    await outbox.start(reconcile=False)
    try:
        ids = []
        for bucket_type in ("dynamic", "permanent", "feel", "plan", "letter"):
            ids.append(
                await manager.create(
                    content=f"offline {bucket_type}",
                    bucket_type=bucket_type,
                )
            )

        assert outbox.status()["pending"] == len(ids)
        for bucket_id in ids:
            assert await manager.get(bucket_id) is not None
        assert engine.calls == []
    finally:
        await outbox.stop()


@pytest.mark.asyncio
async def test_provider_circuit_breaker_stops_failure_storm_and_recovers(tmp_path):
    config = _config(
        tmp_path,
        circuit_failure_threshold=2,
        circuit_base_seconds=5,
        circuit_max_seconds=5,
    )
    failing = FailingEngine()
    manager = BucketManager(config, embedding_engine=failing)
    outbox = EmbeddingOutbox(config, manager, failing)
    manager.attach_embedding_outbox(outbox)

    await outbox.start(reconcile=False)
    try:
        bucket_ids = [
            await manager.create(content=f"circuit memory {index}")
            for index in range(4)
        ]
        await _wait_for(lambda: outbox.status()["circuit"]["state"] == "open")
        calls_at_trip = len(failing.calls)
        await asyncio.sleep(0.05)

        assert calls_at_trip == 2
        assert len(failing.calls) == calls_at_trip
        assert outbox.status()["pending"] == 4
        assert outbox.status()["circuit"]["trips"] == 1

        recovered = RecordingEngine()
        manager.embedding_engine = recovered
        outbox.set_embedding_engine(recovered)
        outbox.retry_now()

        assert await outbox.wait_until_idle(timeout=1.0)
        assert {bucket_id for bucket_id, _content in recovered.calls} == set(bucket_ids)
        assert outbox.status()["circuit"]["state"] == "closed"
    finally:
        await outbox.stop()


def test_embedding_schema_migrates_and_records_content_hash(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db_path = vault / "embeddings.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE embeddings (
                bucket_id TEXT PRIMARY KEY,
                embedding TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO embeddings VALUES (?, ?, ?)",
            ("legacy", "[0.1]", "2026-01-01T00:00:00Z"),
        )

    engine = EmbeddingEngine({
        "buckets_dir": str(vault),
        "embedding": {"enabled": False},
    })
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(embeddings)")}
    assert "content_hash" in columns
    assert engine.get_content_hash("legacy") == ""

    digest = hashlib.sha256(b"current content").hexdigest()
    engine._store_embedding("legacy", [0.2, 0.3], digest)
    assert engine.get_content_hash("legacy") == digest


@pytest.mark.asyncio
async def test_dashboard_backfill_delegates_to_running_outbox(monkeypatch):
    buckets = [{"id": "one", "content": "content", "metadata": {}}]

    class Manager:
        async def list_all(self, include_archive=False):
            assert include_archive is True
            return buckets

    class Outbox:
        running = True

        def __init__(self):
            self.reconciled = False
            self.retried = False

        async def reconcile(self, **kwargs):
            self.reconciled = kwargs["buckets"] == buckets
            return 1

        def status(self):
            return {"pending": 1, "retrying": 0}

        def retry_now(self):
            self.retried = True
            return 1

    outbox = Outbox()

    class Engine(DisabledEngine):
        def list_all_ids(self):
            return ["one", "orphan"]

        def delete_embedding(self, bucket_id):
            assert bucket_id == "orphan"
            self.deleted = bucket_id

    engine = Engine()
    state = {
        "running": True,
        "scanned": 0,
        "missing": 0,
        "done": 0,
        "failed": 0,
        "queued": 0,
        "status": "scanning",
        "error": "",
    }
    monkeypatch.setattr(embedding_web.sh, "bucket_mgr", Manager())
    monkeypatch.setattr(embedding_web.sh, "embedding_outbox", outbox)
    monkeypatch.setattr(embedding_web.sh, "embedding_engine", engine)
    monkeypatch.setattr(embedding_web, "_backfill_state", state)

    await embedding_web._backfill_run()

    assert outbox.reconciled is True
    assert outbox.retried is True
    assert state["status"] == "queued"
    assert state["queued"] == 1
    assert state["orphaned"] == 1
    assert state["cleaned"] == 1
    assert state["cleanup_failed"] == 0
    assert engine.deleted == "orphan"
    assert state["running"] is False


def test_embedding_info_exposes_outbox_status(monkeypatch):
    class MCP:
        def __init__(self):
            self.routes = {}

        def custom_route(self, path, methods):
            def decorator(handler):
                for method in methods:
                    self.routes[(method, path)] = handler
                return handler

            return decorator

    backend = SimpleNamespace(model_name=lambda: "test", vector_dim=lambda: 3)
    engine = SimpleNamespace(
        enabled=True,
        backend="api",
        _backend=backend,
        db_path="",
    )
    outbox = SimpleNamespace(status=lambda: {"pending": 2, "retrying": 1})
    monkeypatch.setattr(embedding_web.sh, "_require_auth", lambda _request: None)
    monkeypatch.setattr(embedding_web.sh, "embedding_engine", engine)
    monkeypatch.setattr(embedding_web.sh, "embedding_outbox", outbox)

    mcp = MCP()
    embedding_web.register(mcp)
    response = asyncio.run(mcp.routes[("GET", "/api/embedding/info")](object()))
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["outbox"] == {"pending": 2, "retrying": 1}
