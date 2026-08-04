from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v3_noncommercial_notice_documents_allowed_and_restricted_uses() -> None:
    text = (ROOT / "LICENSE.v2.4.0-NONCOMMERCIAL-NOTICE.md").read_text(encoding="utf-8")

    assert "source-available" in text
    assert "noncommercial self-hosting" in text
    assert "commercial hosting" in text
    assert "paid resale" in text
    assert "renamed resale" in text
    assert "SaaS resale" in text
    assert "requires prior written permission" in text


def test_readme_links_v3_notice_without_replacing_existing_license() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "v2.4.0 noncommercial notice" in text.lower()
    assert "LICENSE.v2.4.0-NONCOMMERCIAL-NOTICE.md" in text
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_v3_release_notes_summarize_foundation_and_future_transport_work() -> None:
    text = (ROOT / "docs" / "V2.4.0_RELEASE_NOTES_DRAFT.md").read_text(encoding="utf-8")

    assert "v2.4.0 Foundation" in text
    assert "collaboration graph" in text
    assert "Raft-style local cluster simulator" in text
    assert "manifest-driven hot update policy" in text
    assert "full multi-node production transport remains future work" in text
