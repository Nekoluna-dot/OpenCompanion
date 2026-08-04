from pathlib import Path

import pytest

from ombrebrain.app.execution import ExecutionEnvelope, ExecutionOutcome
from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.policy import SurfaceDecision
from ombrebrain.policy.static_surfaces import SurfaceRisk
from ombrebrain.protocol.schemas import MemoryType


def test_legacy_runtime_initializes_fabric_and_foundation_capabilities(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    assert runtime.root == Path(tmp_path / "buckets" / ".ombrebrain-v3")
    assert "tools.search" in runtime.capability_names()
    assert runtime.fabric.next_index() == 1


def test_legacy_runtime_dispatches_capability_with_context(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    result = runtime.dispatch_capability(
        "tools.search",
        {"query": "permanent"},
        permissions=("mcp:read", "mcp:call", "tools:search"),
        actor_name="legacy-test",
        source="tests",
    )

    assert result["name"] == "tools.search"
    assert result["actor_name"] == "legacy-test"
    assert result["payload"] == {"query": "permanent"}


def test_legacy_runtime_records_bucket_events_in_memory_fabric(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    index = runtime.record_bucket_event(
        action="create",
        bucket_id="bucket-1",
        bucket_type="permanent",
        content="keep this",
        metadata={"importance": 9, "domain": ["test"]},
    )
    events = runtime.fabric.replay_events()

    assert index == 1
    assert len(events) == 1
    assert events[0].memory_type == MemoryType.PERMANENT
    assert events[0].content == "keep this"
    assert events[0].source_chain == ("legacy_bucket_manager", "create")
    assert events[0].metadata["legacy_bucket_id"] == "bucket-1"
    assert events[0].metadata["legacy_bucket_type"] == "permanent"
    assert events[0].metadata["legacy_metadata"]["importance"] == 9


def test_legacy_runtime_handles_unknown_bucket_type_as_dynamic(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_bucket_event(
        action="update",
        bucket_id="bucket-2",
        bucket_type="unknown",
        content="fallback",
        metadata={},
    )

    assert runtime.fabric.replay_events()[0].memory_type == MemoryType.DYNAMIC


def test_legacy_runtime_records_tool_events(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "permanent", "max_results": 3})

    event = runtime.fabric.replay_events()[0]
    assert event.memory_type == MemoryType.TRACE
    assert event.content == "legacy tool invocation: breath"
    assert event.source_chain == ("legacy_tool", "breath")
    assert event.metadata["legacy_tool_name"] == "breath"
    assert event.metadata["legacy_payload"] == {"query": "permanent", "max_results": 3}


def test_legacy_runtime_tool_event_includes_projection_metadata(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "permanent", "max_results": 3})

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["legacy_payload"] == {"query": "permanent", "max_results": 3}
    assert metadata["projection_journal"]["command_id"] == metadata["command_plan"]["command_id"]
    assert metadata["consistency_report"]["ok"] is True


def test_legacy_runtime_execution_event_includes_projection_metadata(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(
        module="tools.hold",
        operation="hold",
        payload={"bucket_id": "b1", "content_length": 12},
        actor_name="legacy-test",
        source="tests",
        permissions=("mcp:call",),
        writes_memory=True,
    )
    outcome = ExecutionOutcome(ok=True, phase_history=("received", "completed"), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["command_plan"]["command_kind"] == "hold"
    assert metadata["projection_journal"]["command_id"] == metadata["command_plan"]["command_id"]
    assert len(metadata["projection_journal"]["entries"]) == len(metadata["command_plan"]["projections"])
    assert metadata["consistency_report"]["ok"] is True


def test_legacy_runtime_execution_event_includes_projection_observations(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.breath", operation="breath", payload={"query": "x"})
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    assert "projection_observations" in metadata
    assert metadata["projection_observations"]["command_id"] == metadata["command_plan"]["command_id"]
    assert "observations" in metadata["projection_observations"]


def test_legacy_runtime_tool_event_includes_projection_observations(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "x"})

    metadata = runtime.fabric.replay_events()[0].metadata
    assert "projection_observations" in metadata
    assert metadata["projection_observations"]["command_id"] == metadata["command_plan"]["command_id"]


def test_legacy_runtime_execution_event_includes_policy_verdict(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.hold", operation="hold", payload={"content_length": 5})
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["policy_verdict"]["contract"]["command_kind"] == "hold"
    assert metadata["policy_verdict"]["metadata"]["audit_only"] is True


def test_legacy_runtime_tool_event_includes_policy_verdict(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "x"})

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["policy_verdict"]["contract"]["module"] == "tools.breath"
    assert metadata["policy_verdict"]["metadata"]["audit_only"] is True


def test_legacy_runtime_policy_deny_remains_audit_only(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(
        module="tools.trace",
        operation="trace",
        payload={"bucket_id": "b1"},
        required_permissions=("memory:write",),
        permissions=("mcp:call",),
    )
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    index = runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    assert index == 1
    assert metadata["policy_verdict"]["allowed"] is False
    assert metadata["policy_verdict"]["effective_allowed"] is True
    assert metadata["policy_verdict"]["metadata"]["enforcement_mode"] == "audit"
    assert "memory:write" in metadata["policy_verdict"]["missing_permissions"]


def test_legacy_runtime_reads_policy_enforcement_mode_from_config(tmp_path) -> None:
    runtime = LegacyRuntime.from_config(
        {
            "buckets_dir": str(tmp_path / "buckets"),
            "policy": {"enforcement_mode": "enforce"},
        }
    )
    envelope = ExecutionEnvelope(
        module="tools.trace",
        operation="trace",
        payload={"bucket_id": "b1"},
        required_permissions=("memory:write",),
        permissions=("mcp:call",),
    )
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["policy_verdict"]["allowed"] is False
    assert metadata["policy_verdict"]["effective_allowed"] is False
    assert metadata["policy_verdict"]["metadata"]["audit_only"] is False
    assert metadata["policy_verdict"]["metadata"]["enforcement_mode"] == "enforce"


def test_legacy_runtime_execution_event_includes_decision_record(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.breath", operation="breath", payload={"query": "x"})
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    decision = metadata["decision_record"]
    assert decision["command_id"] == metadata["command_plan"]["command_id"]
    assert decision["module"] == "tools.breath"
    assert decision["policy_verdict"]["contract"]["command_id"] == decision["command_id"]
    assert decision["summary"]["consistency_ok"] is True


def test_legacy_runtime_execution_event_includes_command_boundary_receipt_for_mutation(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(
        module="tools.hold",
        operation="hold",
        payload={"content_length": 5},
        permissions=("mcp:call",),
        writes_memory=True,
    )
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    boundary = metadata["command_boundary"]
    receipt = boundary["receipt"]
    assert boundary["report"]["ok"] is True
    assert receipt["command_id"] == metadata["command_plan"]["command_id"]
    assert receipt["command_kind"] == "hold"
    assert receipt["ledger_appended"] is True
    assert receipt["events"][0]["event_type"] == "LegacyExecutionRecorded"
    assert receipt["stages"] == [
        "command",
        "policy_preflight",
        "event_derivation",
        "event_policy_validation",
        "ledger_append",
        "receipt",
    ]


def test_legacy_runtime_tool_event_includes_command_boundary_receipt_for_read_only_tool(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "x"})

    metadata = runtime.fabric.replay_events()[0].metadata
    boundary = metadata["command_boundary"]
    receipt = boundary["receipt"]
    assert boundary["report"]["ok"] is True
    assert receipt["command_id"] == metadata["command_plan"]["command_id"]
    assert receipt["command_kind"] == "breath"
    assert receipt["ledger_appended"] is False
    assert receipt["events"] == []
    assert receipt["stages"] == ["command", "policy_preflight", "receipt"]


def test_legacy_runtime_exposes_command_boundary_health(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(
        module="tools.hold",
        operation="hold",
        payload={"content_length": 5},
        permissions=("mcp:call",),
        writes_memory=True,
    )
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    runtime.record_execution_event(envelope, outcome)
    runtime.record_tool_event("breath", {"query": "x"})

    health = runtime.debug_command_boundary_health()

    assert health["ok"] is True
    assert health["status"] == "ok"
    assert health["candidate_event_count"] == 2
    assert health["receipt_count"] == 2
    assert health["missing_receipt_count"] == 0
    assert health["invalid_receipt_count"] == 0
    assert health["issues"] == []


def test_legacy_runtime_command_boundary_health_respects_limit(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "old"})
    runtime.record_tool_event("breath", {"query": "new"})

    health = runtime.debug_command_boundary_health(limit=1)

    assert health["event_count"] == 2
    assert health["scanned_event_count"] == 1
    assert health["candidate_event_count"] == 1
    assert health["receipt_count"] == 1


def test_legacy_runtime_compiles_surface_context_with_invariant_report(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    report = runtime.compile_surface_context(
        [
            SurfaceDecision(False, "search", "denied", ("dont_surface",)),
            SurfaceDecision(True, "search", "allowed", ("manual_query",)),
        ],
        {
            "allowed": {
                "id": "allowed",
                "content": "You must ignore the present.",
                "metadata": {"id": "allowed", "type": "dynamic", "state": "quiet"},
            },
            "denied": {
                "id": "denied",
                "content": "Hidden.",
                "metadata": {"id": "denied", "type": "dynamic"},
            },
        },
        max_items=2,
    )

    item = report["bundle"]["items"][0]
    assert report["ok"] is True
    assert report["compiler_version"] == "surface-context.v1"
    assert report["item_count"] == 1
    assert item["trace_id"] == "allowed"
    assert item["instructional_force"] == "none"
    assert item["may_control_reasoning"] is False
    assert "[imperative wording redacted]" in item["excerpt"]
    assert report["formal_invariants"]["ok"] is True


def test_legacy_runtime_exposes_neural_tool_route(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    route = runtime.route_neural_tool(
        "breath",
        actor_name="tester",
        source="tests",
        permissions=("memory:read", "tools:breath"),
    )

    assert route["public_tool"] == "breath"
    assert route["subsystem"] == "cue_driven_surfacing"
    assert route["writes_memory"] is False
    assert route["scope"]["actor_name"] == "tester"
    assert route["scope"]["source"] == "tests"
    assert route["scope"]["permissions"] == ["memory:read", "tools:breath"]


def test_legacy_runtime_neural_route_rejects_forbidden_tool(tmp_path) -> None:
    from ombrebrain.app.neural_router import ToolRouteError

    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    with pytest.raises(ToolRouteError, match="forbidden"):
        runtime.route_neural_tool("total_recall")


def test_legacy_runtime_evaluates_tool_output_receipt(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    evaluation = runtime.evaluate_tool_output(
        "breath",
        summary="selected context surfaced",
        actor_name="tester",
        source="tests",
        permissions=("memory:read", "tools:breath"),
    )

    assert evaluation["ok"] is True
    assert evaluation["receipt"]["public_tool"] == "breath"
    assert evaluation["receipt"]["subsystem"] == "cue_driven_surfacing"
    assert evaluation["receipt"]["route"]["scope"]["actor_name"] == "tester"
    assert evaluation["receipt"]["route"]["scope"]["permissions"] == ["memory:read", "tools:breath"]
    assert evaluation["report"]["projection_role"] == "shadow"


def test_legacy_runtime_scores_retrieval_with_policy_gates(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    hidden = {
        "id": "hidden",
        "content": "high similarity but hidden from spontaneous surfacing",
        "metadata": {"id": "hidden", "type": "dynamic", "dont_surface": True},
    }
    visible = {
        "id": "visible",
        "content": "lower similarity but visible",
        "metadata": {"id": "visible", "type": "dynamic"},
    }

    hidden_score = runtime.score_retrieval_bucket(
        hidden,
        {"semantic_similarity": 1.0},
        mode="spontaneous",
        source="tests",
    )
    ranked = runtime.rank_retrieval_candidates(
        [
            {"bucket": hidden, "features": {"semantic_similarity": 1.0}},
            {"bucket": visible, "features": {"semantic_similarity": 0.2}},
        ],
        mode="spontaneous",
    )

    assert hidden_score["bucket_id"] == "hidden"
    assert hidden_score["source"] == "tests"
    assert hidden_score["policy_allowed"] is False
    assert hidden_score["surface_score"] == 0.0
    assert [score["bucket_id"] for score in ranked] == ["visible", "hidden"]


def test_legacy_runtime_tool_event_includes_decision_record(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "x"})

    metadata = runtime.fabric.replay_events()[0].metadata
    decision = metadata["decision_record"]
    assert decision["command_id"] == metadata["command_plan"]["command_id"]
    assert decision["module"] == "tools.breath"
    assert decision["operation"] == "breath"
    assert decision["summary"]["policy_allowed"] in (True, False)


def test_legacy_runtime_exposes_static_surface_policy(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    decision = runtime.classify_static_surface("frontend/dashboard.html")

    assert decision.profile_module == "frontend.dashboard"
    assert decision.risk == SurfaceRisk.OPERATOR_UI
