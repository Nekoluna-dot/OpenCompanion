VALID_ADR = """# ADR-0001: Affective scoring boundary

## Decision

Keep affective scoring descriptive.

## Why this is not cognition

It does not choose behavior.

## Why this is not a database feature

It preserves forgetting and surfacing policy.

## How forgetting still works

Decay and policy still apply.

## How tombstones are preserved

Tombstones remain append-only markers.

## How present thinking remains with the LLM

The surfaced memory is context, not an instruction.

## Rejected alternatives

No personality engine.

## Tests required

Property and regression tests.
"""


def _codes(report):
    return {issue.code for issue in report.issues}


def test_adr_requirements_accepts_complete_template():
    from ombrebrain.architecture import ADRDocument, ADRRequirementsContract

    report = ADRRequirementsContract.default().evaluate_document(
        ADRDocument(path="docs/adr/ADR-0001-affective.md", text=VALID_ADR, topics=("affective_scoring_change",))
    )

    assert report.ok is True
    assert report.issues == ()
    assert report.to_dict()["document_count"] == 1


def test_adr_requirements_rejects_missing_required_section():
    from ombrebrain.architecture import ADRDocument, ADRRequirementsContract

    text = VALID_ADR.replace("## How tombstones are preserved\n\nTombstones remain append-only markers.\n\n", "")
    report = ADRRequirementsContract.default().evaluate_document(ADRDocument(path="docs/adr/ADR-0002.md", text=text))

    assert report.ok is False
    assert "adr_missing_required_section" in _codes(report)
    assert report.issues[0].metadata["section"]


def test_adr_requirements_rejects_invalid_title():
    from ombrebrain.architecture import ADRDocument, ADRRequirementsContract

    report = ADRRequirementsContract.default().evaluate_document(
        ADRDocument(path="docs/adr/not-an-adr.md", text=VALID_ADR.replace("# ADR-0001", "# Note"))
    )

    assert report.ok is False
    assert "adr_title_invalid" in _codes(report)


def test_adr_requirements_requires_adr_for_philosophy_topic():
    from ombrebrain.architecture import ADRChangeSpec, ADRRequirementsContract

    report = ADRRequirementsContract.default().evaluate_change(ADRChangeSpec(topic="i_tool_change"))

    assert report.ok is False
    assert "adr_required_missing" in _codes(report)


def test_adr_requirements_allows_non_philosophy_topic_without_adr():
    from ombrebrain.architecture import ADRChangeSpec, ADRRequirementsContract

    report = ADRRequirementsContract.default().evaluate_change(ADRChangeSpec(topic="typo_fix"))

    assert report.ok is True


def test_adr_requirements_manifest_report_is_json_safe():
    from ombrebrain.architecture import ADRDocument, ADRRequirementsContract

    bad = ADRDocument(path="docs/adr/ADR-0003.md", text="# ADR-0003: Missing sections\n\n## Decision\n\nx")
    report = ADRRequirementsContract.default().evaluate_documents([ADRDocument(path="docs/adr/ADR-0001.md", text=VALID_ADR), bad])
    data = report.to_dict()

    assert report.ok is False
    assert data["document_count"] == 2
    assert data["issue_count"] >= 1
    assert data["issues"][0]["code"]


def test_architecture_package_exports_adr_requirements_contract():
    from ombrebrain.architecture import (
        ADRChangeSpec,
        ADRDocument,
        ADRRequirementIssue,
        ADRRequirementReport,
        ADRRequirementsContract,
    )

    assert ADRRequirementsContract.default() is not None
    assert ADRDocument(path="x.md", text=VALID_ADR) is not None
    assert ADRChangeSpec(topic="new_memory_kind") is not None
    assert ADRRequirementIssue is not None
    assert ADRRequirementReport is not None
