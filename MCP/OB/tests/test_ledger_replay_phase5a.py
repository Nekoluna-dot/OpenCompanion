from ledger_mirror import LedgerMirror
from ledger_replay import LedgerReplayValidator


def test_ledger_replay_validator_accepts_rebuildable_lifecycle(tmp_path):
    ledger = LedgerMirror(tmp_path / "events.jsonl")
    ledger.append_event(
        event_type="TraceCreated",
        trace_id="b1",
        trace_kind="dynamic",
        payload={"name": "seed"},
        body="one",
    )
    ledger.append_event(
        event_type="TraceUpdated",
        trace_id="b1",
        trace_kind="dynamic",
        payload={"resolved": True},
        body="one",
    )
    ledger.append_event(
        event_type="TraceTouched",
        trace_id="b1",
        trace_kind="dynamic",
        payload={"activation_count": 1},
        body="one",
    )
    ledger.append_event(
        event_type="TraceDeletedToArchive",
        trace_id="b1",
        trace_kind="dynamic",
        payload={
            "deleted_at": "2026-07-02T00:00:00+00:00",
            "tombstone": True,
            "tombstoned_at": "2026-07-02T00:00:00+00:00",
            "erasure_mode": "tombstone_only",
        },
        body="one",
    )

    report = LedgerReplayValidator.default().validate(ledger.iter_events())

    assert report["ok"] is True
    assert report["event_count"] == 4
    assert report["latest_seq"] == 4
    assert report["projection_name"] == "trace_catalog"
    assert report["projection_trace_count"] == 1
    assert report["tombstone_count"] == 1
    assert report["unknown_event_count"] == 0
    assert report["violations"] == []


def test_ledger_replay_validator_reports_structural_violations():
    events = [
        {
            "seq": 1,
            "event_type": "TraceCreated",
            "trace_id": "b1",
            "trace_kind": "dynamic",
            "body_hash": "sha256:" + ("a" * 64),
            "payload": {},
        },
        {
            "seq": 1,
            "event_type": "TraceUpdated",
            "trace_id": "b1",
            "trace_kind": "dynamic",
            "body_hash": "not-a-sha",
            "payload": {},
        },
        {
            "seq": 2,
            "event_type": "TraceUpdated",
            "trace_id": "",
            "trace_kind": "dynamic",
            "body_hash": "sha256:" + ("b" * 64),
            "payload": {},
        },
    ]

    report = LedgerReplayValidator.default().validate(events)
    violation_codes = {violation["code"] for violation in report["violations"]}

    assert report["ok"] is False
    assert "non_increasing_seq" in violation_codes
    assert "invalid_body_hash" in violation_codes
    assert "missing_trace_id" in violation_codes
