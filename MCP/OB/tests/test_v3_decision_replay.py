from ombrebrain.decision.records import DecisionRecord
from ombrebrain.decision.replay import ReplayDebugger


def _record(command_id: str = "cmd_1") -> DecisionRecord:
    return DecisionRecord.new(
        module="tools.breath",
        operation="breath",
        command_plan={
            "command_id": command_id,
            "command_kind": "breath",
            "projections": [{"surface": "dashboard"}],
        },
        policy_verdict={"allowed": True, "contract": {"command_id": command_id}},
        projection_journal={"command_id": command_id, "entries": [{"surface": "dashboard"}]},
        projection_observations={
            "command_id": command_id,
            "observations": [{"surface": "dashboard", "status": "ok"}],
        },
        consistency_report={"command_id": command_id, "ok": True, "issues": []},
        outcome={"ok": True},
    )


def test_replay_debugger_accepts_coherent_record() -> None:
    result = ReplayDebugger.default().replay(_record())

    assert result.ok is True
    assert result.issues == ()
    assert result.explanation["policy_allowed"] is True
    assert result.explanation["projection_surfaces"] == ["dashboard"]


def test_replay_debugger_detects_command_id_mismatch() -> None:
    data = _record().to_dict()
    data["policy_verdict"]["contract"]["command_id"] = "cmd_other"

    result = ReplayDebugger.default().replay(DecisionRecord.from_dict(data))

    assert result.ok is False
    assert any("policy" in issue for issue in result.issues)


def test_replay_debugger_detects_projection_surface_drift() -> None:
    data = _record().to_dict()
    data["projection_journal"]["entries"] = [{"surface": "buckets"}]

    result = ReplayDebugger.default().replay(DecisionRecord.from_dict(data))

    assert result.ok is False
    assert any("surface" in issue for issue in result.issues)


def test_replay_debugger_detects_decision_id_drift() -> None:
    data = _record().to_dict()
    data["id"] = "dec_tampered"

    result = ReplayDebugger.default().replay(DecisionRecord.from_dict(data))

    assert result.ok is False
    assert any("decision id" in issue for issue in result.issues)
