def _record(trace_id: str, trace_kind: str, **overrides):
    from ombrebrain.maintenance import MigrationTraceRecord

    base = {
        "trace_id": trace_id,
        "trace_kind": trace_kind,
        "state": "active",
        "lineage": (f"source:{trace_id}",),
        "decay": {"lambda": 0.05, "threshold": 0.3},
        "tombstone": False,
        "anchor": False,
        "surfacing_rules": {"spontaneous": True, "search": True},
        "target_table": trace_kind,
    }
    base.update(overrides)
    return MigrationTraceRecord(**base)


def test_migration_contract_accepts_preserved_philosophical_fields():
    from ombrebrain.maintenance import MigrationPreservationContract

    source = [
        _record("d1", "dynamic"),
        _record("p1", "permanent", state="active", surfacing_rules={"spontaneous": True}),
        _record("a1", "archive", state="archived", surfacing_rules={"search": False}),
        _record("anchor1", "dynamic", anchor=True, surfacing_rules={"spontaneous": False}),
        _record("t1", "dynamic", state="tombstone", tombstone=True),
    ]
    target = list(source)

    decision = MigrationPreservationContract.default().evaluate_records(source, target)

    assert decision.ok is True
    assert decision.violations == ()


def test_migration_contract_rejects_flattening_into_generic_memories_table():
    from ombrebrain.maintenance import MigrationPreservationContract, MigrationTraceRecord

    source = [
        _record("d1", "dynamic"),
        _record("p1", "permanent"),
        _record("a1", "archive", state="archived"),
        _record("anchor1", "dynamic", anchor=True),
    ]
    target = [
        MigrationTraceRecord(
            trace_id=item.trace_id,
            trace_kind="memory",
            state="active",
            target_table="memories",
        )
        for item in source
    ]

    decision = MigrationPreservationContract.default().evaluate_records(source, target)
    codes = {violation["code"] for violation in decision.violations}

    assert decision.ok is False
    assert "philosophical_distinctions_flattened" in codes
    assert "trace_kind_not_preserved" in codes
    assert "state_not_preserved" in codes


def test_migration_contract_rejects_missing_target_trace():
    from ombrebrain.maintenance import MigrationPreservationContract

    decision = MigrationPreservationContract.default().evaluate_records(
        [_record("lost", "dynamic")],
        [],
    )

    assert decision.ok is False
    assert any(v["code"] == "target_trace_missing" for v in decision.violations)


def test_migration_contract_rejects_lost_tombstone_lineage_decay_and_surfacing_rules():
    from ombrebrain.maintenance import MigrationPreservationContract, MigrationTraceRecord

    source = [
        _record(
            "t1",
            "dynamic",
            state="tombstone",
            tombstone=True,
            lineage=("source:t1", "tombstone:event"),
            decay={"lambda": 0.05},
            surfacing_rules={"spontaneous": False, "search": False},
        )
    ]
    target = [
        MigrationTraceRecord(
            trace_id="t1",
            trace_kind="dynamic",
            state="tombstone",
            tombstone=False,
            lineage=(),
            decay={},
            surfacing_rules={},
        )
    ]

    decision = MigrationPreservationContract.default().evaluate_records(source, target)
    codes = {violation["code"] for violation in decision.violations}

    assert decision.ok is False
    assert "tombstone_not_preserved" in codes
    assert "lineage_not_preserved" in codes
    assert "decay_not_preserved" in codes
    assert "surfacing_rules_not_preserved" in codes


def test_migration_phase_plan_rejects_rust_as_startup_prerequisite():
    from ombrebrain.maintenance import MigrationPhasePlan, MigrationPreservationContract

    plan = MigrationPhasePlan(
        completed_phases=("rust_kernel_extraction",),
        startup_prerequisites=("rust_kernel_extraction",),
    )

    decision = MigrationPreservationContract.default().evaluate_phase_plan(plan)
    codes = {violation["code"] for violation in decision.violations}

    assert decision.ok is False
    assert "rust_extraction_as_startup_condition" in codes
    assert "python_first_phase_missing" in codes


def test_migration_decision_is_json_safe():
    from ombrebrain.maintenance import MigrationPreservationContract

    data = MigrationPreservationContract.default().evaluate_records(
        [_record("lost", "dynamic")],
        [],
    ).to_dict()

    assert data["ok"] is False
    assert data["contract_name"] == "migration_preservation"
    assert data["violations"][0]["code"] == "target_trace_missing"


def test_maintenance_package_exports_migration_contract_symbols():
    from ombrebrain.maintenance import (
        MigrationContractDecision,
        MigrationPhasePlan,
        MigrationPreservationContract,
        MigrationTraceRecord,
    )

    assert MigrationPreservationContract.default() is not None
    assert MigrationTraceRecord(trace_id="x", trace_kind="dynamic") is not None
    assert MigrationPhasePlan() is not None
    assert MigrationContractDecision is not None
