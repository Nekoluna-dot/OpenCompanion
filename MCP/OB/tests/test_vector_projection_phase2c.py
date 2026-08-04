import json
import sqlite3

from ledger_mirror import LedgerMirror


def _write_embedding_db(path, rows, meta=None):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE embeddings (
                bucket_id TEXT PRIMARY KEY,
                embedding TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE embeddings_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        for key, value in (meta or {}).items():
            conn.execute(
                "INSERT INTO embeddings_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
        for bucket_id, embedding in rows:
            conn.execute(
                "INSERT INTO embeddings (bucket_id, embedding, updated_at) VALUES (?, ?, ?)",
                (bucket_id, embedding, "2026-07-03T00:00:00+00:00"),
            )


def test_vector_projection_manifest_reports_embedding_drift_without_mutation(tmp_path):
    from projection_vector import TraceVectorProjectionManifest

    ledger = LedgerMirror(tmp_path / "events.jsonl")
    ledger.append_event(
        event_type="TraceCreated",
        trace_id="active-ok",
        trace_kind="dynamic",
        payload={"name": "active ok"},
        body="body one",
    )
    ledger.append_event(
        event_type="TraceCreated",
        trace_id="active-missing",
        trace_kind="dynamic",
        payload={"name": "active missing"},
        body="body two",
    )
    ledger.append_event(
        event_type="TraceDeletedToArchive",
        trace_id="gone",
        trace_kind="dynamic",
        payload={
            "name": "gone",
            "deleted_at": "2026-07-03T00:00:00+00:00",
            "tombstone": True,
        },
        body="body three",
    )
    db_path = tmp_path / "embeddings.db"
    _write_embedding_db(
        db_path,
        [
            ("active-ok", json.dumps([0.1, 0.2, 0.3])),
            ("orphan", json.dumps([0.4, 0.5, 0.6])),
            ("bad-vector", "{not json"),
        ],
        meta={"model_name": "bge-m3", "vector_dim": "3"},
    )

    projection = TraceVectorProjectionManifest(db_path)
    report = projection.rebuild(ledger.iter_events())

    assert report["projection_name"] == "trace_vector_manifest"
    assert report["projection_role"] == "shadow"
    assert report["canonical"] is False
    assert report["db_exists"] is True
    assert report["model_name"] == "bge-m3"
    assert report["vector_dim"] == 3
    assert report["expected_trace_count"] == 2
    assert report["vector_count"] == 2
    assert report["missing_vector_count"] == 1
    assert report["orphan_vector_count"] == 2
    assert report["malformed_vector_count"] == 1
    assert report["missing_vector_ids"] == ["active-missing"]
    assert report["orphan_vector_ids"] == ["bad-vector", "orphan"]
    assert report["malformed_vector_ids"] == ["bad-vector"]
    assert report["applied_seq"] == ledger.latest_seq()


def test_bucket_manager_ledger_report_includes_vector_projection(
    test_config,
    fake_embedding_engine,
):
    import asyncio

    from bucket_manager import BucketManager

    async def scenario():
        manager = BucketManager(test_config, embedding_engine=fake_embedding_engine)
        bucket_id = await manager.create("vector projection source", domain=["vector"])
        return manager, bucket_id, manager.ledger_integrity_report()

    manager, bucket_id, report = asyncio.run(scenario())
    projection = report["vector_projection"]

    assert projection["projection_name"] == "trace_vector_manifest"
    assert projection["projection_role"] == "shadow"
    assert projection["canonical"] is False
    assert projection["path"].endswith("embeddings.db")
    assert projection["expected_trace_count"] == 1
    assert projection["applied_seq"] == report["latest_seq"]
    assert projection["source_latest_seq"] == report["latest_seq"]
    assert projection["lag"] == 0
    assert bucket_id in projection["missing_vector_ids"]
    assert str(manager.base_dir) in projection["path"]
