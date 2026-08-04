from ledger_mirror import LedgerMirror


def test_sqlite_projection_rebuilds_trace_catalog_database(tmp_path):
    from projection_sqlite import TraceSQLiteProjection

    ledger = LedgerMirror(tmp_path / "events.jsonl")
    ledger.append_event(
        event_type="TraceCreated",
        trace_id="b1",
        trace_kind="dynamic",
        payload={"name": "first memory", "importance": 7, "domain": ["work"]},
        body="body one",
    )
    ledger.append_event(
        event_type="TraceTouched",
        trace_id="b1",
        trace_kind="dynamic",
        payload={"activation_count": 1},
        body="body one",
    )
    ledger.append_event(
        event_type="TraceDeletedToArchive",
        trace_id="b2",
        trace_kind="dynamic",
        payload={
            "name": "gone memory",
            "deleted_at": "2026-07-03T00:00:00",
            "tombstone": True,
            "erasure_mode": "tombstone_only",
        },
        body="body two",
    )

    projection = TraceSQLiteProjection(tmp_path / "trace_catalog.sqlite3")
    projection.rebuild(ledger.iter_events())
    report = projection.to_report(source_latest_seq=ledger.latest_seq())

    assert (tmp_path / "trace_catalog.sqlite3").exists()
    assert report["projection_name"] == "trace_catalog_sqlite"
    assert report["projection_role"] == "shadow"
    assert report["canonical"] is False
    assert report["trace_count"] == 2
    assert report["tombstone_count"] == 1
    assert report["applied_seq"] == ledger.latest_seq()
    assert report["source_latest_seq"] == ledger.latest_seq()
    assert report["lag"] == 0

    b1 = projection.get_trace("b1")
    assert b1 is not None
    assert b1["trace_id"] == "b1"
    assert b1["state"] == "active"
    assert b1["touch_count"] == 1
    assert b1["metadata"]["name"] == "first memory"

    b2 = projection.get_trace("b2")
    assert b2 is not None
    assert b2["state"] == "tombstone"
    assert b2["tombstone"] is True


def test_sqlite_projection_searches_metadata_text(tmp_path):
    from projection_sqlite import TraceSQLiteProjection

    ledger = LedgerMirror(tmp_path / "events.jsonl")
    ledger.append_event(
        event_type="TraceCreated",
        trace_id="b1",
        trace_kind="dynamic",
        payload={
            "name": "quiet promise",
            "tags": ["contract", "launch"],
            "domain": ["release"],
            "why_remembered": "A promise should surface only through policy.",
        },
        body="body one",
    )
    ledger.append_event(
        event_type="TraceCreated",
        trace_id="b2",
        trace_kind="dynamic",
        payload={"name": "unrelated", "tags": ["garden"]},
        body="body two",
    )

    projection = TraceSQLiteProjection(tmp_path / "trace_catalog.sqlite3")
    projection.rebuild(ledger.iter_events())

    results = projection.search("promise", limit=5)

    assert [item["trace_id"] for item in results] == ["b1"]
    assert results[0]["metadata"]["name"] == "quiet promise"
