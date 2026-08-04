def _codes(report):
    return {issue.code for issue in report.issues}


def _valid_receipt():
    from ombrebrain.domain import BoundaryStage, CommandBoundaryReceipt

    return CommandBoundaryReceipt(
        command_id="cmd_1",
        command_kind="hold",
        stages=(
            BoundaryStage.COMMAND,
            BoundaryStage.POLICY_PREFLIGHT,
            BoundaryStage.EVENT_DERIVATION,
            BoundaryStage.EVENT_POLICY_VALIDATION,
            BoundaryStage.LEDGER_APPEND,
            BoundaryStage.RECEIPT,
        ),
        events=({"event_type": "TraceCreated", "trace_id": "mem_1"},),
        ledger_appended=True,
        policy_preflight_allowed=True,
        event_validation_allowed=True,
    )


def test_command_boundary_accepts_command_policy_event_ledger_sequence():
    from ombrebrain.domain import AdvancedCommandBoundaryContract

    report = AdvancedCommandBoundaryContract.default().evaluate_receipt(_valid_receipt())

    assert report.ok is True
    assert report.issues == ()
    assert report.to_dict()["receipt_count"] == 1


def test_command_boundary_rejects_missing_policy_preflight():
    from ombrebrain.domain import AdvancedCommandBoundaryContract, BoundaryStage

    receipt = _valid_receipt().with_stages(
        (
            BoundaryStage.COMMAND,
            BoundaryStage.EVENT_DERIVATION,
            BoundaryStage.EVENT_POLICY_VALIDATION,
            BoundaryStage.LEDGER_APPEND,
            BoundaryStage.RECEIPT,
        )
    )

    report = AdvancedCommandBoundaryContract.default().evaluate_receipt(receipt)

    assert report.ok is False
    assert "missing_boundary_stage" in _codes(report)


def test_command_boundary_rejects_wrong_order_before_ledger_append():
    from ombrebrain.domain import AdvancedCommandBoundaryContract, BoundaryStage

    receipt = _valid_receipt().with_stages(
        (
            BoundaryStage.COMMAND,
            BoundaryStage.POLICY_PREFLIGHT,
            BoundaryStage.LEDGER_APPEND,
            BoundaryStage.EVENT_DERIVATION,
            BoundaryStage.EVENT_POLICY_VALIDATION,
            BoundaryStage.RECEIPT,
        )
    )

    report = AdvancedCommandBoundaryContract.default().evaluate_receipt(receipt)

    assert report.ok is False
    assert "boundary_stage_order_invalid" in _codes(report)
    assert "ledger_append_without_event_policy_validation" in _codes(report)


def test_command_boundary_rejects_policy_denied_ledger_append():
    from ombrebrain.domain import AdvancedCommandBoundaryContract

    receipt = _valid_receipt().replace(policy_preflight_allowed=False)

    report = AdvancedCommandBoundaryContract.default().evaluate_receipt(receipt)

    assert report.ok is False
    assert "ledger_append_after_policy_denial" in _codes(report)


def test_command_boundary_rejects_mutation_without_events_or_ledger():
    from ombrebrain.domain import AdvancedCommandBoundaryContract, BoundaryStage, CommandBoundaryReceipt

    receipt = CommandBoundaryReceipt(
        command_id="cmd_2",
        command_kind="trace",
        stages=(BoundaryStage.COMMAND, BoundaryStage.POLICY_PREFLIGHT, BoundaryStage.RECEIPT),
        events=(),
        ledger_appended=False,
    )

    report = AdvancedCommandBoundaryContract.default().evaluate_receipt(receipt)

    assert report.ok is False
    assert _codes(report) >= {"mutation_without_events", "mutation_without_ledger_append"}


def test_command_boundary_accepts_read_only_command_without_ledger_append():
    from ombrebrain.domain import AdvancedCommandBoundaryContract, BoundaryStage, CommandBoundaryReceipt

    receipt = CommandBoundaryReceipt(
        command_id="cmd_3",
        command_kind="breath",
        stages=(BoundaryStage.COMMAND, BoundaryStage.POLICY_PREFLIGHT, BoundaryStage.RECEIPT),
        events=(),
        ledger_appended=False,
    )

    report = AdvancedCommandBoundaryContract.default().evaluate_receipt(receipt)

    assert report.ok is True


def test_command_boundary_rejects_adapter_direct_write_marker():
    from ombrebrain.domain import AdvancedCommandBoundaryContract

    receipt = _valid_receipt().replace(adapter_direct_write=True)

    report = AdvancedCommandBoundaryContract.default().evaluate_receipt(receipt)

    assert report.ok is False
    assert "adapter_direct_memory_write" in _codes(report)


def test_command_boundary_manifest_report_is_json_safe():
    from ombrebrain.domain import AdvancedCommandBoundaryContract

    bad = _valid_receipt().replace(command_id="cmd_bad", adapter_direct_write=True)
    report = AdvancedCommandBoundaryContract.default().evaluate_manifest([_valid_receipt(), bad])
    data = report.to_dict()

    assert report.ok is False
    assert data["receipt_count"] == 2
    assert data["issue_count"] == 1
    assert data["issues"][0]["code"] == "adapter_direct_memory_write"


def test_domain_package_exports_advanced_command_boundary_contract():
    from ombrebrain.domain import (
        AdvancedCommandBoundaryContract,
        BoundaryStage,
        CommandBoundaryIssue,
        CommandBoundaryReceipt,
        CommandBoundaryReport,
    )

    assert AdvancedCommandBoundaryContract.default() is not None
    assert CommandBoundaryReceipt(command_id="cmd", command_kind="breath") is not None
    assert CommandBoundaryIssue is not None
    assert CommandBoundaryReport is not None
    assert BoundaryStage.LEDGER_APPEND.value == "ledger_append"
