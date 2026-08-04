import json

import pytest

from web import auth as auth_web


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
    def __init__(self, body):
        self._body = body
        self.headers = {}
        self.cookies = {}
        self.client = type("Client", (), {"host": "127.0.0.1"})()

    async def json(self):
        return self._body


def _payload(response):
    return json.loads(response.body)


@pytest.fixture
def auth_routes(monkeypatch):
    monkeypatch.setattr(auth_web.sh, "_is_setup_needed", lambda: True)
    monkeypatch.setattr(auth_web.sh, "_require_auth", lambda _request: None)
    monkeypatch.setattr(auth_web.sh, "_load_auth_data", lambda: {
        "security_answer_hash": "configured"
    })
    monkeypatch.setattr(auth_web.sh, "_login_retry_after", lambda _request: 0)
    mcp = FakeMCP()
    auth_web.register(mcp)
    return mcp.routes


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/auth/setup", "/auth/change-password", "/auth/security-question"])
async def test_auth_mutations_reject_non_object_json(auth_routes, path):
    response = await auth_routes[("POST", path)](JsonRequest(["not", "an", "object"]))

    assert response.status_code == 400
    assert _payload(response)["error"] == "JSON body must be an object"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/auth/login", "/auth/recover"])
async def test_public_auth_mutations_count_non_object_json_as_failure(
    auth_routes, monkeypatch, path
):
    failures = []
    monkeypatch.setattr(
        auth_web.sh, "_record_login_failure", lambda request: failures.append(request)
    )

    response = await auth_routes[("POST", path)](JsonRequest("not-an-object"))

    assert response.status_code == 400
    assert failures


@pytest.mark.asyncio
async def test_setup_rejects_oversized_password_without_saving(auth_routes, monkeypatch):
    saved = []
    monkeypatch.setattr(auth_web.sh, "_save_password_hash", saved.append)

    response = await auth_routes[("POST", "/auth/setup")](
        JsonRequest({"password": "x" * 1025})
    )

    assert response.status_code == 400
    assert saved == []


@pytest.mark.asyncio
async def test_recover_does_not_clear_failures_for_invalid_new_password(
    auth_routes, monkeypatch
):
    successes = []
    saved = []
    monkeypatch.setattr(auth_web.sh, "_verify_security_answer", lambda _answer: True)
    monkeypatch.setattr(
        auth_web.sh, "_record_login_success", lambda request: successes.append(request)
    )
    monkeypatch.setattr(auth_web.sh, "_save_password_hash", lambda *args, **kwargs: saved.append(args))

    response = await auth_routes[("POST", "/auth/recover")](
        JsonRequest({"answer": "correct", "new_password": "short"})
    )

    assert response.status_code == 400
    assert successes == []
    assert saved == []
