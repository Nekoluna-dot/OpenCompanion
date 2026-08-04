"""记忆归属（多人共用一套 OB）后端测试。

覆盖：
- get_owner_name / get_owner_count 的环境变量读取与回退
- GET /api/config 是否把 owner_name / owner_count 暴露给前端
- OWNER_NAME 只从进程环境读，不写共享 .env（隔离不串名）
"""
import json

import pytest

import web.config_api as config_api
from utils import get_owner_name, get_owner_count


class FakeMCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def decorator(fn):
            for method in methods:
                self.routes[(method, path)] = fn
            return fn

        return decorator


class GetRequest:
    headers: dict = {}


def test_owner_name_defaults_empty(monkeypatch):
    monkeypatch.delenv("OMBRE_OWNER_NAME", raising=False)
    assert get_owner_name() == ""


def test_owner_name_reads_env(monkeypatch):
    monkeypatch.setenv("OMBRE_OWNER_NAME", "  小明 ")
    assert get_owner_name() == "小明"


def test_owner_count_defaults_one(monkeypatch):
    monkeypatch.delenv("OMBRE_OWNER_COUNT", raising=False)
    assert get_owner_count() == 1


@pytest.mark.parametrize("raw,expected", [("2", 2), ("3", 3), ("1", 1), ("0", 1), ("-5", 1), ("abc", 1), ("", 1)])
def test_owner_count_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("OMBRE_OWNER_COUNT", raw)
    assert get_owner_count() == expected


@pytest.mark.asyncio
async def test_config_get_exposes_owner_fields(monkeypatch):
    monkeypatch.setenv("OMBRE_OWNER_NAME", "小红")
    monkeypatch.setenv("OMBRE_OWNER_COUNT", "2")
    monkeypatch.setattr(config_api.sh, "_require_auth", lambda request: None)
    monkeypatch.setattr(config_api.sh, "config", {})
    monkeypatch.setattr(config_api.sh, "in_docker", lambda: False)

    mcp = FakeMCP()
    config_api.register(mcp)

    response = await mcp.routes[("GET", "/api/config")](GetRequest())
    payload = json.loads(response.body)

    assert payload["owner_name"] == "小红"
    assert payload["owner_count"] == 2


@pytest.mark.asyncio
async def test_config_get_single_owner_defaults(monkeypatch):
    monkeypatch.delenv("OMBRE_OWNER_NAME", raising=False)
    monkeypatch.delenv("OMBRE_OWNER_COUNT", raising=False)
    monkeypatch.setattr(config_api.sh, "_require_auth", lambda request: None)
    monkeypatch.setattr(config_api.sh, "config", {})
    monkeypatch.setattr(config_api.sh, "in_docker", lambda: False)

    mcp = FakeMCP()
    config_api.register(mcp)

    response = await mcp.routes[("GET", "/api/config")](GetRequest())
    payload = json.loads(response.body)

    assert payload["owner_name"] == ""
    assert payload["owner_count"] == 1
