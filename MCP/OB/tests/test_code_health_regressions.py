import json

import httpx
import pytest

from tools.i import core as i_tool
from web import embedding as embedding_web
from web import import_api as import_web
from web import plans as plans_web


class FakeMCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def decorator(handler):
            for method in methods:
                self.routes[(method, path)] = handler
            return handler

        return decorator


class JsonRequest:
    def __init__(self, body=None, *, path_params=None):
        self._body = body or {}
        self.path_params = path_params or {}
        self.headers = {}
        self.query_params = {}

    async def json(self):
        return self._body


def _json(response):
    return json.loads(response.body.decode("utf-8"))


@pytest.mark.asyncio
async def test_I_rejects_unknown_aspect_before_writing(monkeypatch):
    class Decay:
        async def ensure_started(self):
            return None

    class BucketManager:
        async def create(self, **_kwargs):
            pytest.fail("invalid aspect must not create a bucket")

    monkeypatch.setattr(i_tool.rt, "decay_engine", Decay(), raising=False)
    monkeypatch.setattr(i_tool.rt, "bucket_mgr", BucketManager(), raising=False)
    monkeypatch.setattr(i_tool.rt, "mark_op", None, raising=False)

    result = await i_tool.i_core(content="identity", aspect="prompt-injected")

    assert "aspect 无效" in result
    assert "values" in result


@pytest.mark.asyncio
async def test_streaming_import_upload_stops_at_size_limit():
    class StreamRequest:
        headers = {}

        async def stream(self):
            yield b"1234"
            yield b"5678"

    with pytest.raises(ValueError, match="Upload too large"):
        await import_web._read_body_limited(StreamRequest(), limit=6)


@pytest.mark.asyncio
async def test_multipart_upload_reads_only_limit_plus_one_bytes():
    class FileField:
        requested = None

        async def read(self, size):
            self.requested = size
            return b"x" * size

    field = FileField()
    with pytest.raises(ValueError, match="Upload too large"):
        await import_web._read_file_field_limited(field, limit=8)
    assert field.requested == 9


@pytest.mark.asyncio
async def test_plan_edit_rejects_oversized_content_without_updating(monkeypatch):
    class BucketManager:
        def __init__(self):
            self.updated = False

        async def get(self, bucket_id):
            return {
                "id": bucket_id,
                "content": "before",
                "metadata": {"type": "plan", "status": "active"},
            }

        async def update(self, _bucket_id, **_updates):
            self.updated = True
            return True

    manager = BucketManager()
    monkeypatch.setattr(plans_web.sh, "_require_auth", lambda _request: None)
    monkeypatch.setattr(plans_web.sh, "bucket_mgr", manager, raising=False)
    monkeypatch.setattr(plans_web, "check_content_size", lambda _content: "content too large")
    mcp = FakeMCP()
    plans_web.register(mcp)

    response = await mcp.routes[("POST", "/api/plans/{bucket_id}/action")](
        JsonRequest(
            {"action": "edit", "content": "x" * 100},
            path_params={"bucket_id": "plan-1"},
        )
    )

    assert response.status_code == 400
    assert _json(response)["error"] == "content too large"
    assert manager.updated is False


@pytest.mark.asyncio
async def test_ollama_pull_bounds_connection_waits_but_allows_long_stream(monkeypatch):
    captured = {}

    class StreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def aiter_lines(self):
            yield '{"status":"success"}'

    class Client:
        def __init__(self, *, timeout, trust_env):
            captured["timeout"] = timeout
            captured["trust_env"] = trust_env

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def stream(self, method, url, *, json):
            captured.update(method=method, url=url, payload=json)
            return StreamResponse()

    monkeypatch.setattr(embedding_web.httpx, "AsyncClient", Client)

    await embedding_web._ollama_pull_run("http://127.0.0.1:11434", "bge-m3")

    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 10.0
    assert timeout.write == 30.0
    assert timeout.pool == 10.0
    assert timeout.read is None
    assert captured["trust_env"] is False
    assert captured["payload"] == {"name": "bge-m3", "stream": True}
    assert embedding_web._ollama_pull_state["status"] == "success"
