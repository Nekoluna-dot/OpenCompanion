from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_doc(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def test_acceptance_checklist_requires_local_verification_and_no_publication() -> None:
    text = _read_doc("V2.4.0_ACCEPTANCE_CHECKLIST.md")

    for phrase in (
        "py -3.10 -m pytest -q",
        "No commit",
        "No push",
        "No release",
        "No cloud server",
        "MCP tool names unchanged",
        "bucket markdown unchanged",
        "Dashboard existing routes unchanged",
        "Rollback",
    ):
        assert phrase in text


def test_rollback_doc_names_state_surfaces_and_safe_revert_paths() -> None:
    text = _read_doc("V2.4.0_ROLLBACK.md")

    for phrase in (
        ".ombrebrain-v3",
        "git",
        "artifacts",
        "config",
        "buckets",
        "vector",
        "No cloud server",
        "No commit",
    ):
        assert phrase in text


def test_release_notes_cover_debug_audit_resilience_maintenance_and_acceptance() -> None:
    text = _read_doc("V2.4.0_RELEASE_NOTES_DRAFT.md")

    for phrase in (
        "Decision Debug Service",
        "ArchitectureAuditor",
        "V3ResilienceScanner",
        "V3MaintenanceReportBuilder",
        "2.4.0 Debug Dashboard",
        "pre-release acceptance",
        "F -> G -> H -> I -> J",
    ):
        assert phrase in text
