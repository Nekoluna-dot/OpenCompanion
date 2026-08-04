from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_doc(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def test_v3_architecture_doc_pins_the_execution_chain_and_read_only_tools() -> None:
    text = _read_doc("V2.4.0_ARCHITECTURE.md")

    assert "ExecutionEnvelope -> CommandPlan -> ProjectionAuditRuntime -> PolicyEngine -> DecisionLedger -> DecisionDebugService" in text
    assert "DecisionReplayService" in text
    assert "ArchitectureAuditor" in text
    assert "V3ResilienceScanner" in text
    assert "tools/v3_health_report.py" in text
    assert "read-only" in text
    assert "write-side-channel" in text
    assert "flowchart" in text


def test_v3_boundary_map_documents_protected_surfaces_and_legacy_contracts() -> None:
    text = _read_doc("V2.4.0_BOUNDARY_MAP.md")

    assert "protected surfaces" in text
    assert "config" in text
    assert "buckets" in text
    assert "vector database" in text
    assert "MCP tool names unchanged" in text
    assert "bucket markdown unchanged" in text
    assert "Dashboard existing routes unchanged" in text
    assert "No cloud server changes" in text


def test_v3_docs_reference_all_final_hardening_layers() -> None:
    combined = _read_doc("V2.4.0_ARCHITECTURE.md") + "\n" + _read_doc("V2.4.0_BOUNDARY_MAP.md")

    for phrase in (
        "ComponentGraph",
        "ArchitectureReport",
        "ResilienceReport",
        "V3MaintenanceReportBuilder",
        "DecisionRecord",
        "Policy VM",
        "Projection observers",
    ):
        assert phrase in combined
