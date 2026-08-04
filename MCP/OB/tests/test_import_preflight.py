import json

import pytest

import web.import_api as import_api


class FakeMCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def decorator(fn):
            for method in methods:
                self.routes[(method, path)] = fn
            return fn

        return decorator


class BodyRequest:
    def __init__(self, body: str, filename: str = "upload.md"):
        self.headers = {}
        self.query_params = {"filename": filename}
        self._body = body.encode("utf-8")

    async def body(self):
        return self._body


class FakeDehydrator:
    api_available = True


class FakeImportEngine:
    is_running = False
    dehydrator = FakeDehydrator()


def test_preview_import_counts_turns_chunks_and_estimated_calls():
    from import_memory import preview_import

    raw = "Human: 我喜欢茶\nAssistant: 我记住了\nUser: 明天提醒我整理导入体验"

    preview = preview_import(raw, filename="chat.md", human_label="阿立")

    assert preview["ok"] is True
    assert preview["detected_format"] == "markdown"
    assert preview["turns_count"] == 3
    assert preview["chunks_count"] == 1
    assert preview["estimated_api_calls"] == 1
    assert "[阿立]" in preview["first_chunk_preview"]


def test_preview_import_warns_when_invalid_json_falls_back_to_text():
    from import_memory import preview_import

    preview = preview_import("{not json", filename="bad.json")

    assert preview["ok"] is True
    assert preview["detected_format"] == "text"
    assert preview["turns_count"] == 1
    assert any("JSON" in warning for warning in preview["warnings"])


@pytest.mark.asyncio
async def test_import_preflight_route_returns_preview_with_runtime_readiness(monkeypatch):
    monkeypatch.setattr(import_api.sh, "_require_auth", lambda request: None)
    monkeypatch.setattr(import_api.sh, "import_engine", FakeImportEngine())
    monkeypatch.setattr(import_api.sh, "config", {"human": "阿立"})

    mcp = FakeMCP()
    import_api.register(mcp)

    response = await mcp.routes[("POST", "/api/import/preflight")](
        BodyRequest("Human: hi\nAssistant: hello", filename="chat.md")
    )
    payload = json.loads(response.body)

    assert payload["ok"] is True
    assert payload["can_start"] is True
    assert payload["llm_ready"] is True
    assert payload["import_running"] is False
    assert payload["filename"] == "chat.md"
    assert payload["turns_count"] == 2
    assert payload["chunks_count"] == 1

