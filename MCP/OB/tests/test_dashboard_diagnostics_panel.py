from pathlib import Path


def test_dashboard_contains_system_diagnostics_panel_and_loader():
    for rel in ("frontend/dashboard.html",):
        html = Path(rel).read_text(encoding="utf-8")

        assert 'id="system-diagnostics-summary"' in html
        assert 'id="system-diagnostics-list"' in html
        assert "async function loadSystemDiagnostics()" in html
        assert "/api/system/diagnostics" in html
        assert "loadSystemDiagnostics();" in html


def test_dashboard_forgotten_state_uses_supported_lucide_icon():
    html = Path("frontend/dashboard.html").read_text(encoding="utf-8")

    assert 'data-lucide="moon-off"' not in html
    assert html.count('data-lucide="eye-off"') >= 4

