import asyncio
import json

import web
from web import _shared as sh
from web import v3_debug


class FakeMcp:
    def __init__(self) -> None:
        self.routes = {}

    def custom_route(self, path, methods):
        def decorator(func):
            self.routes[path] = {"methods": tuple(methods), "func": func}
            return func

        return decorator


class FakeRequest:
    def __init__(self, *, query_params=None, path_params=None) -> None:
        self.query_params = query_params or {}
        self.path_params = path_params or {}
        self.cookies = {}
        self.headers = {}


def _json(response):
    return json.loads(response.body.decode("utf-8"))


def test_web_register_all_includes_v3_debug_routes() -> None:
    sh.init_runtime(v3_runtime=None)
    mcp = FakeMcp()

    web.register_all(mcp)

    assert "/api/v3/debug/decisions" in mcp.routes
    assert "/api/v3/debug/decision/{identifier}" in mcp.routes
    assert "/api/v3/debug/replay/{identifier}" in mcp.routes


def test_v3_debug_decisions_route_delegates_to_runtime(monkeypatch) -> None:
    calls = []

    class Runtime:
        def debug_decisions(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "records": [{"id": "dec_1"}], "count": 1, "problems": []}

    monkeypatch.setattr(sh, "_require_auth", lambda request: None)
    sh.init_runtime(v3_runtime=Runtime())
    mcp = FakeMcp()
    v3_debug.register(mcp)

    response = asyncio.run(
        mcp.routes["/api/v3/debug/decisions"]["func"](
            FakeRequest(query_params={"limit": "3", "module": "tools.breath", "operation": "breath"})
        )
    )

    assert calls == [{"limit": 3, "module": "tools.breath", "operation": "breath"}]
    assert _json(response)["records"][0]["id"] == "dec_1"


def test_v3_debug_replay_route_delegates_to_runtime(monkeypatch) -> None:
    calls = []

    class Runtime:
        def replay_decision(self, identifier):
            calls.append(identifier)
            return {"ok": True, "replay": {"ok": True}}

    monkeypatch.setattr(sh, "_require_auth", lambda request: None)
    sh.init_runtime(v3_runtime=Runtime())
    mcp = FakeMcp()
    v3_debug.register(mcp)

    response = asyncio.run(
        mcp.routes["/api/v3/debug/replay/{identifier}"]["func"](
            FakeRequest(path_params={"identifier": "dec_1"})
        )
    )

    assert calls == ["dec_1"]
    assert _json(response)["replay"]["ok"] is True
