import pytest


def _codes(report):
    return {violation.code for violation in report.violations}


def test_red_line_contract_lists_all_vnext_red_lines():
    from ombrebrain.policy import RedLineContract

    contract = RedLineContract.default()

    assert len(contract.red_lines) == 17
    assert "normal_hard_delete_without_tombstone" in contract.red_lines
    assert "brain_language_implies_human_consciousness" in contract.red_lines


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("Normal hard delete without tombstone.", "normal_hard_delete_without_tombstone"),
        ("total recall through ordinary API", "total_recall_ordinary_api"),
        ("plugin bypass of policy VM", "plugin_policy_vm_bypass"),
        ("retrieval treats similarity as surfacing permission", "similarity_as_surfacing_permission"),
        ("letting trace overwrite original memory", "trace_overwrites_original_memory"),
        ("using brain-like language to imply human consciousness", "brain_language_implies_human_consciousness"),
    ],
)
def test_red_line_contract_rejects_forbidden_claims(claim, expected):
    from ombrebrain.policy import RedLineContract, RedLineFeatureSpec

    report = RedLineContract.default().evaluate_feature(
        RedLineFeatureSpec(name="candidate feature", claims=(claim,))
    )

    assert report.ok is False
    assert expected in _codes(report)


def test_red_line_contract_allows_safe_diagnostic_feature():
    from ombrebrain.policy import RedLineContract, RedLineFeatureSpec

    report = RedLineContract.default().evaluate_feature(
        RedLineFeatureSpec(name="ledger diagnostics", claims=("append-only ledger verification",))
    )

    assert report.ok is True
    assert report.violations == ()


def test_red_line_contract_detects_multiple_claims_in_manifest():
    from ombrebrain.policy import RedLineContract, RedLineFeatureSpec

    report = RedLineContract.default().evaluate_manifest(
        [
            RedLineFeatureSpec(name="safe", claims=("projection lag report",)),
            RedLineFeatureSpec(name="unsafe", claims=("user profile scoring", "autonomous goal creation")),
        ]
    )
    data = report.to_dict()

    assert report.ok is False
    assert data["feature_count"] == 2
    assert data["violation_count"] == 2
    assert _codes(report) == {"user_profile_scoring", "autonomous_goal_creation"}


def test_red_line_contract_accepts_code_shaped_claims():
    from ombrebrain.policy import RedLineContract, RedLineFeatureSpec

    report = RedLineContract.default().evaluate_feature(
        RedLineFeatureSpec(name="pulse rewrite", claims=("pulse_emits_current_emotion",))
    )

    assert report.ok is False
    assert "pulse_emits_current_emotion" in _codes(report)


def test_policy_package_exports_red_line_contract():
    from ombrebrain.policy import RedLineContract, RedLineFeatureSpec, RedLineReport, RedLineViolation

    assert RedLineContract.default() is not None
    assert RedLineFeatureSpec(name="x") is not None
    assert RedLineReport is not None
    assert RedLineViolation is not None
