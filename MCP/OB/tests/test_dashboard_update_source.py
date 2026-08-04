from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_version_check_uses_github_api_before_raw_cdn_fallback():
    api_url = "https://api.github.com/repos/P0luz/Ombre-Brain/contents/VERSION?ref=main"
    raw_url = "https://raw.githubusercontent.com/P0luz/Ombre-Brain/main/VERSION?t="

    for rel_path in ("frontend/dashboard.html",):
        html = (ROOT / rel_path).read_text(encoding="utf-8")

        assert api_url in html
        assert raw_url in html
        assert html.index(api_url) < html.index(raw_url)
