import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from web import letters


ROOT = Path(__file__).resolve().parents[1]


class FakeMCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def decorator(fn):
            for method in methods:
                self.routes[(method, path)] = fn
            return fn

        return decorator


class DeleteRequest:
    path_params = {"letter_id": "letter-ghost"}
    query_params = {"confirm": "true"}


class MissingBucketManager:
    def __init__(self):
        self.embedding_outbox = SimpleNamespace(discard=lambda bucket_id: None)
        self.invalidated = False

    async def get(self, bucket_id):
        return None

    def _invalidate_bm25(self):
        self.invalidated = True


def payload(response):
    return json.loads(response.body.decode("utf-8"))


def test_dashboard_lucide_observer_cannot_eat_button_clicks():
    dashboard = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")

    assert "button i, button svg { pointer-events: none; }" in dashboard
    assert "obs.disconnect();" in dashboard
    assert "finally {" in dashboard
    assert "obs.observe(document.body, {childList: true, subtree: true});" in dashboard
    assert 'data-lucide="moon-off"' not in dashboard


@pytest.mark.asyncio
async def test_delete_missing_letter_repairs_vector_and_runtime_cache(monkeypatch):
    manager = MissingBucketManager()
    deleted_vectors = []
    monkeypatch.setattr(letters.sh, "_require_auth", lambda request: None)
    monkeypatch.setattr(letters.sh, "bucket_mgr", manager)
    monkeypatch.setattr(
        letters.sh,
        "embedding_engine",
        SimpleNamespace(delete_embedding=deleted_vectors.append),
    )
    mcp = FakeMCP()
    letters.register(mcp)

    response = await mcp.routes[("DELETE", "/api/letter/{letter_id}")](DeleteRequest())
    body = payload(response)

    assert response.status_code == 200
    assert body == {
        "ok": True,
        "deleted": False,
        "cleaned": True,
        "already_missing": True,
    }
    assert deleted_vectors == ["letter-ghost"]
    assert manager.invalidated is True
