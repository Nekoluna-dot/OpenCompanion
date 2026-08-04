import json
import os

import pytest

import web.config_api as config_api
from utils import get_ai_name


class FakeMCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def decorator(fn):
            for method in methods:
                self.routes[(method, path)] = fn
            return fn

        return decorator


class JsonRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.mark.asyncio
async def test_env_config_can_clear_ai_display_name(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_NAME", "trainsprout")
    monkeypatch.setattr(config_api.sh, "_require_auth", lambda request: None)
    monkeypatch.setattr(config_api.sh, "_project_env_path", lambda: str(tmp_path / ".env"))
    monkeypatch.setattr(config_api.sh, "config", {})

    mcp = FakeMCP()
    config_api.register(mcp)

    response = await mcp.routes[("POST", "/api/env-config")](
        JsonRequest({"updates": {"AI_NAME": ""}})
    )
    payload = json.loads(response.body)

    assert payload["ok"] is True
    assert "AI_NAME" in payload["updated"]
    assert os.environ.get("AI_NAME") is None
    assert get_ai_name() == "AI"
