import pytest

from ombrebrain.app.execution import (
    ExecutionEnvelope,
    ExecutionPhase,
    LegacyExecutionPipeline,
)
from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.kernel.errors import PolicyViolation
from ombrebrain.protocol.schemas import MemoryType


def test_execution_pipeline_returns_handler_result_and_records_trace(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(
        module="decay_engine",
        operation="calculate_score",
        payload={"importance": 9, "token": "secret"},
        actor_name="test-suite",
        permissions=("legacy:execute",),
    )

    result = runtime.execution_pipeline.run(envelope, lambda: 42)

    assert result == 42
    event = runtime.fabric.replay_events()[0]
    assert event.memory_type == MemoryType.TRACE
    assert event.source_chain == ("legacy_execution", "decay_engine", "calculate_score")
    assert event.metadata["ok"] is True
    assert event.metadata["payload"]["importance"] == 9
    assert event.metadata["payload"]["token"] == "[REDACTED]"
    assert event.metadata["phase_history"][-1] == ExecutionPhase.COMPLETED.value


def test_execution_pipeline_keeps_result_passthrough_with_decision_debug(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.breath", operation="breath", payload={"query": "x"})

    result = runtime.execution_pipeline.run(envelope, lambda: {"legacy": "result"})
    decision = runtime.debug_decisions(limit=1)["records"][0]

    assert result == {"legacy": "result"}
    assert decision["module"] == "tools.breath"
    assert runtime.replay_decision(decision["id"])["record"]["id"] == decision["id"]


def test_execution_pipeline_reraises_handler_error_after_recording(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="github_sync", operation="sync")

    def boom():
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError, match="network down"):
        runtime.execution_pipeline.run(envelope, boom)

    event = runtime.fabric.replay_events()[0]
    assert event.metadata["ok"] is False
    assert event.metadata["error_type"] == "RuntimeError"
    assert event.metadata["phase_history"][-1] == ExecutionPhase.FAILED.value


@pytest.mark.asyncio
async def test_execution_pipeline_supports_async_handlers(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.breath", operation="dispatch")

    async def handler():
        return "breath result"

    assert await runtime.execution_pipeline.run_async(envelope, handler) == "breath result"


def test_execution_pipeline_is_noop_without_runtime() -> None:
    pipeline = LegacyExecutionPipeline()

    assert pipeline.run(ExecutionEnvelope(module="web.dashboard", operation="route"), lambda: "ok") == "ok"


def test_execution_pipeline_audit_mode_keeps_policy_deny_non_blocking(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(
        module="tools.trace",
        operation="trace",
        payload={"bucket_id": "b1"},
        permissions=(),
    )
    calls: list[str] = []

    def handler() -> str:
        calls.append("called")
        return "legacy result"

    result = runtime.execution_pipeline.run(envelope, handler)

    event = runtime.fabric.replay_events()[0]
    assert result == "legacy result"
    assert calls == ["called"]
    assert event.metadata["ok"] is True
    assert event.metadata["policy_verdict"]["allowed"] is False
    assert event.metadata["policy_verdict"]["effective_allowed"] is True
    assert event.metadata["policy_verdict"]["metadata"]["enforcement_mode"] == "audit"


def test_execution_pipeline_enforce_mode_blocks_effective_policy_deny_and_records_trace(tmp_path) -> None:
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
        permissions=(),
    )
    calls: list[str] = []

    def handler() -> str:
        calls.append("called")
        return "legacy result"

    with pytest.raises(PolicyViolation, match="policy denied"):
        runtime.execution_pipeline.run(envelope, handler)

    event = runtime.fabric.replay_events()[0]
    assert calls == []
    assert event.metadata["ok"] is False
    assert event.metadata["error_type"] == "PolicyViolation"
    assert ExecutionPhase.EXECUTING.value not in event.metadata["phase_history"]
    assert event.metadata["phase_history"][-1] == ExecutionPhase.FAILED.value
    assert event.metadata["policy_verdict"]["allowed"] is False
    assert event.metadata["policy_verdict"]["effective_allowed"] is False
    assert event.metadata["policy_verdict"]["metadata"]["enforcement_mode"] == "enforce"
    assert event.metadata["decision_record"]["summary"]["policy_effective_allowed"] is False
