import json

from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility
from ombrebrain.resilience.scanner import V3ResilienceScanner


def test_resilience_scanner_reports_clean_runtime_health(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.record_tool_event("breath", {"query": "x"})

    report = V3ResilienceScanner(runtime.fabric).scan()

    assert report.ok is True
    assert report.event_count == 1
    assert report.findings == ()
    assert report.to_dict()["checks"]["wal_replay"] == "ok"


def test_resilience_scanner_reports_corrupt_wal_without_raising(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.record_tool_event("breath", {"query": "x"})
    wal_path = runtime.fabric.wal.path
    with wal_path.open("a", encoding="utf-8") as handle:
        handle.write("{not-json}\n")

    report = V3ResilienceScanner(runtime.fabric).scan()

    assert report.ok is False
    assert any(finding.code == "wal_replay_failed" for finding in report.findings)


def test_resilience_scanner_surfaces_decision_metadata_problems(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.fabric.append_event(
        MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="test",
            memory_type=MemoryType.TRACE,
            content="bad decision metadata",
            visibility=Visibility.INTERNAL,
            source_chain=("test",),
            metadata={"decision_record": "bad"},
        )
    )

    report = V3ResilienceScanner(runtime.fabric).scan()

    assert report.ok is False
    assert any(finding.code == "decision_metadata_problem" for finding in report.findings)


def test_resilience_scanner_detects_policy_projection_shape_drift(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.fabric.append_event(
        MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="test",
            memory_type=MemoryType.TRACE,
            content="bad policy projection",
            visibility=Visibility.INTERNAL,
            source_chain=("test",),
            metadata={
                "command_plan": {"command_id": "cmd_1"},
                "policy_verdict": "bad",
                "projection_journal": [],
                "consistency_report": {"ok": True},
            },
        )
    )

    report = V3ResilienceScanner(runtime.fabric).scan()

    assert report.ok is False
    assert any(finding.code == "metadata_shape_drift" for finding in report.findings)


def test_resilience_scanner_is_side_effect_free(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.record_tool_event("breath", {"query": "x"})
    before = runtime.fabric.next_index()

    V3ResilienceScanner(runtime.fabric).scan()

    assert runtime.fabric.next_index() == before
    json.dumps(V3ResilienceScanner(runtime.fabric).scan().to_dict(), ensure_ascii=False, allow_nan=False)
