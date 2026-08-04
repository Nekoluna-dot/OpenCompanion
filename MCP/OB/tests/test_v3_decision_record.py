import json

from ombrebrain.decision.ledger import DecisionLedger
from ombrebrain.decision.records import DecisionRecord


def test_decision_record_is_stable_and_json_safe() -> None:
    record = DecisionRecord.new(
        module="tools.breath",
        operation="breath",
        command_plan={"command_id": "cmd_1", "command_kind": "breath", "projections": []},
        policy_verdict={"allowed": True, "contract": {"command_id": "cmd_1"}},
        projection_journal={"command_id": "cmd_1", "entries": []},
        projection_observations={"command_id": "cmd_1", "observations": []},
        consistency_report={"command_id": "cmd_1", "ok": True, "issues": []},
        outcome={"ok": True, "result_type": "str"},
    )
    same = DecisionRecord.new(
        module="tools.breath",
        operation="breath",
        command_plan={"command_id": "cmd_1", "command_kind": "breath", "projections": []},
        policy_verdict={"allowed": True, "contract": {"command_id": "cmd_1"}},
        projection_journal={"command_id": "cmd_1", "entries": []},
        projection_observations={"command_id": "cmd_1", "observations": []},
        consistency_report={"command_id": "cmd_1", "ok": True, "issues": []},
        outcome={"ok": True, "result_type": "str"},
    )

    assert record.id.startswith("dec_")
    assert record.id == same.id
    assert record.command_id == "cmd_1"
    assert record.summary["module"] == "tools.breath"
    assert DecisionRecord.from_dict(record.to_dict()).id == record.id
    json.dumps(record.to_dict(), ensure_ascii=False, allow_nan=False)


def test_decision_record_redacts_unserializable_values() -> None:
    record = DecisionRecord.new(
        module="web.oauth",
        operation="toggle",
        command_plan={"command_id": "cmd_web", "raw": object()},
        policy_verdict={"allowed": True, "contract": {"command_id": "cmd_web"}},
        projection_journal={"command_id": "cmd_web", "entries": []},
        projection_observations={"command_id": "cmd_web", "observations": []},
        consistency_report={"command_id": "cmd_web", "ok": True, "issues": []},
        outcome={"ok": True},
    )

    assert record.command_plan["raw"].startswith("<object object")
    json.dumps(record.to_dict(), ensure_ascii=False, allow_nan=False)


def test_decision_ledger_builds_records_from_runtime_metadata() -> None:
    record = DecisionLedger.default().record(
        module="tools.hold",
        operation="hold",
        command_plan={"command_id": "cmd_hold", "command_kind": "hold", "projections": []},
        policy_metadata={
            "policy_verdict": {
                "allowed": False,
                "effective_allowed": True,
                "missing_permissions": ["memory:write"],
                "contract": {"command_id": "cmd_hold"},
            }
        },
        projection_metadata={
            "projection_journal": {"command_id": "cmd_hold", "entries": []},
            "projection_observations": {"command_id": "cmd_hold", "observations": []},
            "consistency_report": {"command_id": "cmd_hold", "ok": True, "issues": []},
        },
        outcome={"ok": True},
    )

    assert record.policy_verdict["allowed"] is False
    assert record.summary["policy_allowed"] is False
    assert record.summary["policy_effective_allowed"] is True
    assert record.summary["consistency_ok"] is True
    assert record.summary["projection_count"] == 0
