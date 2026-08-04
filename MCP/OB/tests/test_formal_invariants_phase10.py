from ledger_mirror import LedgerMirror


def test_projection_rebuild_cannot_create_or_lose_canonical_truth():
    from ombrebrain.policy.formal_invariants import FormalInvariantChecker

    checker = FormalInvariantChecker.default()

    report = checker.evaluate_projection_rebuild(
        canonical_trace_ids=["a", "b"],
        projection_trace_ids=["b", "c"],
        projection_name="sqlite_shadow",
    )
    codes = {violation.code for violation in report.violations}

    assert report.ok is False
    assert "projection_lost_canonical_truth" in codes
    assert "projection_created_noncanonical_truth" in codes
    assert report.to_dict()["projection_name"] == "formal_invariants"

    clean = checker.evaluate_projection_rebuild(
        canonical_trace_ids=["a", "b"],
        projection_trace_ids=["b", "a"],
    )
    assert clean.ok is True


def test_context_items_detect_past_affect_emitted_as_current_feeling():
    from ombrebrain.policy.formal_invariants import FormalInvariantChecker

    report = FormalInvariantChecker.default().evaluate_context_items(
        [
            {
                "trace_id": "affect-1",
                "text": "I currently feel grief from this stored memory.",
                "affect": {"valence": 0.2, "arousal": 0.8},
                "current_feeling": True,
                "instructional_force": "none",
            }
        ]
    )

    assert report.ok is False
    assert any(v.code == "past_affect_emitted_as_current_feeling" for v in report.violations)


def test_lossy_compression_must_declare_loss_and_lineage():
    from ombrebrain.policy.formal_invariants import FormalInvariantChecker

    report = FormalInvariantChecker.default().evaluate_compression_records(
        [
            {
                "trace_id": "compressed-1",
                "lossy": True,
                "declares_loss": False,
                "source_trace_id": "",
                "source_hash": "",
            }
        ]
    )
    codes = {violation.code for violation in report.violations}

    assert report.ok is False
    assert "lossy_compression_without_loss_declaration" in codes
    assert "lossy_compression_without_lineage" in codes


def test_admin_erasure_is_external_storage_action_not_internal_forgetting(tmp_path):
    from ombrebrain.policy.formal_invariants import FormalInvariantChecker

    ledger = LedgerMirror(tmp_path / "events.jsonl")
    ledger.append_event(
        event_type="AdminErasure",
        trace_id="erase-1",
        trace_kind="dynamic",
        payload={"storage_action": "internal_forgetting", "external_storage_action": False},
        body="",
    )

    report = FormalInvariantChecker.default().evaluate_ledger(ledger.iter_events())

    assert report.ok is False
    assert any(v.code == "admin_erasure_logged_as_internal_forgetting" for v in report.violations)


def test_trace_reconstruction_cannot_overwrite_original_body(tmp_path):
    from ombrebrain.policy.formal_invariants import FormalInvariantChecker

    ledger = LedgerMirror(tmp_path / "events.jsonl")
    ledger.append_event(
        event_type="TraceCreated",
        trace_id="trace-1",
        trace_kind="dynamic",
        payload={"body_hash": "hash-original"},
        body="original body",
    )
    ledger.append_event(
        event_type="TraceReconstructed",
        trace_id="trace-1",
        trace_kind="dynamic",
        payload={
            "body_hash": "hash-new",
            "original_body_hash": "hash-original",
            "overwrites_original": True,
        },
        body="rewritten body",
    )

    report = FormalInvariantChecker.default().evaluate_ledger(ledger.iter_events())

    assert report.ok is False
    assert any(v.code == "reconstruction_overwrote_original_trace" for v in report.violations)


def test_dream_receipt_cannot_create_autonomous_goals_or_current_emotion():
    from ombrebrain.policy.formal_invariants import FormalInvariantChecker

    report = FormalInvariantChecker.default().evaluate_tool_receipt(
        {
            "tool": "dream",
            "created_autonomous_goal": True,
            "generated_current_emotion": True,
            "created_behavior_command": True,
        }
    )
    codes = {violation.code for violation in report.violations}

    assert report.ok is False
    assert "dream_created_autonomous_goal" in codes
    assert "dream_generated_current_emotion" in codes
    assert "dream_created_behavior_command" in codes


def test_pulse_receipt_cannot_report_or_set_current_emotion():
    from ombrebrain.policy.formal_invariants import FormalInvariantChecker

    report = FormalInvariantChecker.default().evaluate_tool_receipt(
        {
            "tool": "pulse",
            "contains_current_emotion": True,
            "current_emotion": "sad",
        }
    )
    codes = {violation.code for violation in report.violations}

    assert report.ok is False
    assert "pulse_reported_current_emotion" in codes
    assert "pulse_set_current_emotion" in codes


def test_formal_invariants_metadata_lists_all_vnext_invariants():
    from ombrebrain.policy.formal_invariants import FormalInvariantChecker

    report = FormalInvariantChecker.default().evaluate_tool_request({"tool": "breath"})

    assert report.invariant_count == 13
    assert "admin_erasure_is_not_forgetting" in report.checked
    assert "dream_may_sediment_not_decide" in report.checked
    assert "pulse_is_not_current_feeling" in report.checked
