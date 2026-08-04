from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "frontend" / "dashboard.html"


def test_dashboard_contains_v3_debug_tab_and_view() -> None:
    text = DASHBOARD.read_text(encoding="utf-8")

    assert 'data-tab="v3-debug"' in text
    assert 'id="v3-debug-view"' in text
    assert 'id="v3-debug-list"' in text
    assert 'id="v3-debug-detail"' in text


def test_dashboard_v3_debug_view_calls_read_only_endpoints() -> None:
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "function loadV3Debug" in text
    assert "function replayV3Decision" in text
    assert "/api/v3/debug/decisions" in text
    assert "/api/v3/debug/replay/" in text
    assert "method: 'POST'" not in _v3_debug_script(text)


def _v3_debug_script(text: str) -> str:
    start = text.index("// v3-debug-panel")
    end = text.index("// v3-debug-panel-end")
    return text[start:end]
