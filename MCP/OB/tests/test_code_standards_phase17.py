import pytest


def _codes(report):
    return {issue.code for issue in report.issues}


def test_code_standards_accepts_current_python_adapter_shape():
    from ombrebrain.architecture import ArtifactLanguage, ArtifactRole, CodeArtifactSpec, HighestDifficultyCodeStandards

    report = HighestDifficultyCodeStandards.default().evaluate_artifact(
        CodeArtifactSpec(
            path="src/web/search.py",
            language=ArtifactLanguage.PYTHON,
            role=ArtifactRole.ADAPTER,
            type_checked=True,
            uses_explicit_commands=True,
            tests=("property",),
        )
    )

    assert report.ok is True
    assert report.issues == ()


def test_code_standards_rejects_python_direct_canonical_mutation():
    from ombrebrain.architecture import ArtifactLanguage, ArtifactRole, CodeArtifactSpec, HighestDifficultyCodeStandards

    report = HighestDifficultyCodeStandards.default().evaluate_artifact(
        CodeArtifactSpec(
            path="src/web/admin.py",
            language=ArtifactLanguage.PYTHON,
            role=ArtifactRole.ADAPTER,
            directly_mutates_canonical_memory=True,
            uses_explicit_commands=False,
        )
    )

    assert report.ok is False
    assert "python_direct_canonical_mutation" in _codes(report)
    assert "python_missing_explicit_command_boundary" in _codes(report)


def test_code_standards_rejects_rust_kernel_without_append_only_policy():
    from ombrebrain.architecture import ArtifactLanguage, ArtifactRole, CodeArtifactSpec, HighestDifficultyCodeStandards

    report = HighestDifficultyCodeStandards.default().evaluate_artifact(
        CodeArtifactSpec(
            path="kernel/src/lib.rs",
            language=ArtifactLanguage.RUST,
            role=ArtifactRole.KERNEL,
            appends_ledger_events=False,
            validates_policy=False,
            denial_reasons_explicit=False,
            exposes_hard_delete_api=True,
        )
    )

    assert report.ok is False
    assert _codes(report) >= {
        "rust_kernel_not_append_only",
        "rust_kernel_bypasses_policy_vm",
        "policy_denial_reasons_not_explicit",
        "normal_hard_delete_api_exposed",
    }


@pytest.mark.parametrize(
    ("role", "kwargs", "expected"),
    [
        ("async_task", {"async_idempotent": False}, "async_task_not_idempotent"),
        ("projection", {"reports_projection_lag": False}, "projection_lag_not_reported"),
        ("dashboard_action", {"capability_scoped": False}, "dashboard_action_not_capability_scoped"),
    ],
)
def test_code_standards_rejects_role_specific_boundary_breaks(role, kwargs, expected):
    from ombrebrain.architecture import ArtifactLanguage, CodeArtifactSpec, HighestDifficultyCodeStandards

    report = HighestDifficultyCodeStandards.default().evaluate_artifact(
        CodeArtifactSpec(path="src/example.py", language=ArtifactLanguage.PYTHON, role=role, **kwargs)
    )

    assert report.ok is False
    assert expected in _codes(report)


@pytest.mark.parametrize(
    "change_kind",
    [
        "new_memory_kind",
        "deletion_behavior_change",
        "total_recall_like_feature",
        "plugin_capability_expansion",
        "affective_scoring_change",
        "dream_behavior_change",
    ],
)
def test_code_standards_requires_adr_for_philosophy_touching_changes(change_kind):
    from ombrebrain.architecture import ArtifactLanguage, ArtifactRole, CodeArtifactSpec, HighestDifficultyCodeStandards

    report = HighestDifficultyCodeStandards.default().evaluate_artifact(
        CodeArtifactSpec(
            path="src/ombrebrain/policy/new_rule.py",
            language=ArtifactLanguage.PYTHON,
            role=ArtifactRole.POLICY_RULE,
            change_kind=change_kind,
        )
    )

    assert report.ok is False
    assert "adr_required_missing" in _codes(report)


def test_code_standards_accepts_adr_backed_philosophy_change_with_test_evidence():
    from ombrebrain.architecture import ArtifactLanguage, ArtifactRole, CodeArtifactSpec, HighestDifficultyCodeStandards

    report = HighestDifficultyCodeStandards.default().evaluate_artifact(
        CodeArtifactSpec(
            path="src/ombrebrain/policy/surfacing.py",
            language=ArtifactLanguage.PYTHON,
            role=ArtifactRole.POLICY_RULE,
            change_kind="affective_scoring_change",
            adr_path="docs/adr/ADR-0001-affective-scoring.md",
            tests=("property", "mutation"),
        )
    )

    assert report.ok is True
    assert report.to_dict()["artifact_count"] == 1


def test_code_standards_manifest_report_is_json_safe():
    from ombrebrain.architecture import ArtifactLanguage, ArtifactRole, CodeArtifactSpec, HighestDifficultyCodeStandards

    report = HighestDifficultyCodeStandards.default().evaluate_manifest(
        [
            CodeArtifactSpec(path="src/web/search.py", language=ArtifactLanguage.PYTHON, role=ArtifactRole.ADAPTER),
            CodeArtifactSpec(
                path="src/web/delete.py",
                language=ArtifactLanguage.PYTHON,
                role=ArtifactRole.DASHBOARD_ACTION,
                exposes_hard_delete_api=True,
                capability_scoped=False,
            ),
        ]
    )
    data = report.to_dict()

    assert report.ok is False
    assert data["artifact_count"] == 2
    assert data["issue_count"] >= 2
    assert data["issues"][0]["code"]


def test_architecture_package_exports_code_standards_contract():
    from ombrebrain.architecture import (
        ArtifactLanguage,
        ArtifactRole,
        CodeArtifactSpec,
        CodeStandardIssue,
        CodeStandardReport,
        HighestDifficultyCodeStandards,
    )

    assert HighestDifficultyCodeStandards.default() is not None
    assert CodeArtifactSpec(path="x.py", language="python", role="adapter") is not None
    assert CodeStandardIssue is not None
    assert CodeStandardReport is not None
    assert ArtifactLanguage.PYTHON.value == "python"
    assert ArtifactRole.KERNEL.value == "kernel"
