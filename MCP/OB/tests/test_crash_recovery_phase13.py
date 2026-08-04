def test_write_path_contract_accepts_vnext_order():
    from ombrebrain.resilience import CrashRecoveryContract, PathStep

    decision = CrashRecoveryContract.default().evaluate_write_path(
        [
            PathStep("mcp_tool_call"),
            PathStep("policy_preflight"),
            PathStep("append_event_to_wal"),
            PathStep("fsync"),
            PathStep("update_projections_async"),
            PathStep("update_markdown_vault_projection"),
            PathStep("return_trace_id"),
        ]
    )

    assert decision.ok is True
    assert decision.violations == ()


def test_write_path_contract_rejects_return_before_fsync():
    from ombrebrain.resilience import CrashRecoveryContract, PathStep

    decision = CrashRecoveryContract.default().evaluate_write_path(
        [
            PathStep("mcp_tool_call"),
            PathStep("policy_preflight"),
            PathStep("append_event_to_wal"),
            PathStep("return_trace_id"),
            PathStep("fsync"),
        ]
    )
    codes = {violation["code"] for violation in decision.violations}

    assert decision.ok is False
    assert "path_step_out_of_order" in codes
    assert "write_returned_before_fsync" in codes


def test_read_path_contract_accepts_vnext_order():
    from ombrebrain.resilience import CrashRecoveryContract, PathStep

    decision = CrashRecoveryContract.default().evaluate_read_path(
        [
            PathStep("query"),
            PathStep("candidate_generation_from_shadow_indexes"),
            PathStep("canonical_trace_verification"),
            PathStep("policy_gate"),
            PathStep("surfacing_budget"),
            PathStep("context_compiler"),
        ]
    )

    assert decision.ok is True


def test_read_path_contract_rejects_policy_before_canonical_verification():
    from ombrebrain.resilience import CrashRecoveryContract, PathStep

    decision = CrashRecoveryContract.default().evaluate_read_path(
        [
            PathStep("query"),
            PathStep("candidate_generation_from_shadow_indexes"),
            PathStep("policy_gate"),
            PathStep("canonical_trace_verification"),
            PathStep("context_compiler"),
        ]
    )
    codes = {violation["code"] for violation in decision.violations}

    assert decision.ok is False
    assert "path_step_out_of_order" in codes
    assert "missing_path_step" in codes


def test_recovery_plan_requires_ledger_wins_and_disposable_indexes():
    from ombrebrain.resilience import CrashRecoveryContract, CrashRecoveryPlan

    plan = CrashRecoveryPlan(
        ledger_wins=True,
        projections_rebuild=True,
        markdown_repaired=True,
        indexes_disposable=True,
    )

    decision = CrashRecoveryContract.default().evaluate_recovery_plan(plan)

    assert decision.ok is True
    assert decision.recovery_rule == "ledger_wins"


def test_recovery_plan_rejects_projection_as_canonical_source():
    from ombrebrain.resilience import CrashRecoveryContract, CrashRecoveryPlan

    plan = CrashRecoveryPlan(
        ledger_wins=False,
        projections_rebuild=False,
        markdown_repaired=False,
        indexes_disposable=False,
        canonical_source="sqlite_projection",
    )

    decision = CrashRecoveryContract.default().evaluate_recovery_plan(plan)
    codes = {violation["code"] for violation in decision.violations}

    assert decision.ok is False
    assert "ledger_not_declared_winner" in codes
    assert "projection_treated_as_canonical" in codes
    assert "indexes_not_disposable" in codes


def test_crash_recovery_decision_is_json_safe():
    from ombrebrain.resilience import CrashRecoveryContract, CrashRecoveryPlan

    data = CrashRecoveryContract.default().evaluate_recovery_plan(
        CrashRecoveryPlan(
            ledger_wins=False,
            projections_rebuild=True,
            markdown_repaired=True,
            indexes_disposable=True,
            canonical_source="markdown",
        )
    ).to_dict()

    assert data["ok"] is False
    assert data["contract_name"] == "crash_recovery"
    assert data["recovery_rule"] == "ledger_wins"
    assert data["violations"][0]["code"] == "ledger_not_declared_winner"


def test_resilience_package_exports_crash_recovery_symbols():
    from ombrebrain.resilience import CrashRecoveryContract, CrashRecoveryDecision, CrashRecoveryPlan, PathStep

    assert CrashRecoveryContract.default() is not None
    assert CrashRecoveryPlan() is not None
    assert CrashRecoveryDecision is not None
    assert PathStep("fsync").name == "fsync"
