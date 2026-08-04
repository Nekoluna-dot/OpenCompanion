import json
import base64
import hashlib
import time
import urllib.parse

import pytest

import web.oauth as oauth_mod


class FakeMCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def decorator(fn):
            for method in methods:
                self.routes[(method, path)] = fn
            return fn

        return decorator


class FakeUrl:
    scheme = "https"
    netloc = "ombre.example"


class JsonRequest:
    def __init__(self, body=None, *, headers=None, path_params=None,
                 method="POST", query_params=None, client_host="127.0.0.1"):
        self._body = {} if body is None else body
        self.headers = headers or {"content-type": "application/json", "host": "ombre.example"}
        self.url = FakeUrl()
        self.path_params = path_params or {}
        self.method = method
        self.query_params = query_params or {}
        self.client = type("Client", (), {"host": client_host})()

    async def json(self):
        return self._body

    async def form(self):
        return self._body


def _payload(response):
    return json.loads(response.body)


def _fresh_oauth_routes(monkeypatch, tmp_path, *, auth_required=True):
    oauth_mod._oauth_clients.clear()
    oauth_mod._oauth_codes.clear()
    oauth_mod._mcp_tokens.clear()
    oauth_mod._mcp_token_resources.clear()
    if hasattr(oauth_mod, "_mcp_refresh_tokens"):
        oauth_mod._mcp_refresh_tokens.clear()
    oauth_mod.sh._login_failures.clear()
    oauth_mod.sh._login_locked_until.clear()
    monkeypatch.setattr(oauth_mod.sh, "config", {
        "buckets_dir": str(tmp_path / "buckets"),
        "mcp_require_auth": auth_required,
    })

    mcp = FakeMCP()
    oauth_mod.register(mcp)
    return mcp.routes


@pytest.fixture
def oauth_routes(monkeypatch, tmp_path):
    return _fresh_oauth_routes(monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_oauth_metadata_and_registration_advertise_refresh_token(oauth_routes):
    metadata_response = await oauth_routes[("GET", "/.well-known/oauth-authorization-server")](
        JsonRequest()
    )
    metadata = _payload(metadata_response)

    register_response = await oauth_routes[("POST", "/oauth/register")](
        JsonRequest({"redirect_uris": ["https://client.example/callback"]})
    )
    registration = _payload(register_response)

    assert "refresh_token" in metadata["grant_types_supported"]
    assert "refresh_token" in registration["grant_types"]


@pytest.mark.asyncio
async def test_oauth_routes_are_not_advertised_when_mcp_auth_is_disabled(
    monkeypatch, tmp_path
):
    routes = _fresh_oauth_routes(
        monkeypatch, tmp_path, auth_required=False
    )

    requests = [
        (("GET", "/.well-known/oauth-protected-resource"), JsonRequest(method="GET")),
        (
            ("GET", "/.well-known/oauth-protected-resource/{resource_path:path}"),
            JsonRequest(method="GET", path_params={"resource_path": "mcp"}),
        ),
        (("GET", "/.well-known/oauth-authorization-server"), JsonRequest(method="GET")),
        (("POST", "/oauth/register"), JsonRequest()),
        (("GET", "/oauth/authorize"), JsonRequest(method="GET")),
        (("POST", "/oauth/token"), JsonRequest()),
    ]

    for route, request in requests:
        response = await routes[route](request)
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_protected_resource_metadata_rejects_unknown_mcp_path(
    oauth_routes,
):
    response = await oauth_routes[
        ("GET", "/.well-known/oauth-protected-resource/{resource_path:path}")
    ](
        JsonRequest(
            method="GET",
            path_params={"resource_path": "retired-mcp-endpoint"},
        )
    )

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_protected_resource_metadata_only_describes_real_mcp_resource(
    oauth_routes,
):
    root_response = await oauth_routes[
        ("GET", "/.well-known/oauth-protected-resource")
    ](JsonRequest(method="GET"))
    mcp_response = await oauth_routes[
        ("GET", "/.well-known/oauth-protected-resource/{resource_path:path}")
    ](JsonRequest(method="GET", path_params={"resource_path": "mcp"}))

    assert root_response.status_code == 200
    assert _payload(root_response)["resource"] == "https://ombre.example/mcp"
    assert root_response.headers["cache-control"] == "no-store"
    assert mcp_response.status_code == 200
    assert _payload(mcp_response)["resource"] == "https://ombre.example/mcp"
    assert mcp_response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_oauth_route_visibility_uses_startup_config_snapshot(
    monkeypatch, tmp_path
):
    enabled_routes = _fresh_oauth_routes(
        monkeypatch, tmp_path, auth_required=True
    )
    oauth_mod.sh.config["mcp_require_auth"] = False

    enabled_response = await enabled_routes[
        ("GET", "/.well-known/oauth-protected-resource")
    ](JsonRequest(method="GET"))
    assert enabled_response.status_code == 200

    disabled_routes = _fresh_oauth_routes(
        monkeypatch, tmp_path, auth_required=False
    )
    oauth_mod.sh.config["mcp_require_auth"] = True

    disabled_response = await disabled_routes[
        ("GET", "/.well-known/oauth-protected-resource")
    ](JsonRequest(method="GET"))
    assert disabled_response.status_code == 404


@pytest.mark.asyncio
async def test_refresh_token_grant_renews_access_without_browser_authorization(oauth_routes):
    oauth_mod._oauth_clients["client-1"] = {
        "redirect_uris": ["https://client.example/callback"],
        "client_name": "Headless Client",
    }
    oauth_mod._oauth_codes["code-1"] = {
        "client_id": "client-1",
        "redirect_uri": "https://client.example/callback",
        "code_challenge": "",
        "expires": time.time() + 60,
    }

    token_response = await oauth_routes[("POST", "/oauth/token")](
        JsonRequest({
            "grant_type": "authorization_code",
            "code": "code-1",
            "client_id": "client-1",
        })
    )
    initial = _payload(token_response)
    first_access_token = initial["access_token"]
    refresh_token = initial["refresh_token"]

    oauth_mod._mcp_tokens[first_access_token] = time.time() - 1
    assert oauth_mod._is_valid_mcp_token(first_access_token) is False

    refresh_response = await oauth_routes[("POST", "/oauth/token")](
        JsonRequest({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "client-1",
        })
    )
    refreshed = _payload(refresh_response)

    assert refreshed["access_token"] != first_access_token
    assert refreshed["token_type"] == "Bearer"
    assert refreshed["scope"] == "mcp"
    assert oauth_mod._is_valid_mcp_token(refreshed["access_token"]) is True


@pytest.mark.asyncio
async def test_refresh_token_survives_process_restart(oauth_routes):
    oauth_mod._oauth_clients["client-1"] = {
        "redirect_uris": ["https://client.example/callback"],
        "client_name": "Headless Client",
    }
    oauth_mod._oauth_codes["code-1"] = {
        "client_id": "client-1",
        "redirect_uri": "https://client.example/callback",
        "code_challenge": "",
        "expires": time.time() + 60,
    }

    token_response = await oauth_routes[("POST", "/oauth/token")](
        JsonRequest({
            "grant_type": "authorization_code",
            "code": "code-1",
            "client_id": "client-1",
        })
    )
    refresh_token = _payload(token_response)["refresh_token"]

    oauth_mod._mcp_tokens.clear()
    oauth_mod._mcp_refresh_tokens.clear()
    oauth_mod._load_mcp_tokens()

    refresh_response = await oauth_routes[("POST", "/oauth/token")](
        JsonRequest({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "client-1",
        })
    )
    refreshed = _payload(refresh_response)

    assert refresh_response.status_code == 200
    assert oauth_mod._is_valid_mcp_token(refreshed["access_token"]) is True


@pytest.mark.asyncio
async def test_refresh_token_grant_rejects_unknown_refresh_token(oauth_routes):
    response = await oauth_routes[("POST", "/oauth/token")](
        JsonRequest({
            "grant_type": "refresh_token",
            "refresh_token": "not-issued",
            "client_id": "client-1",
        })
    )
    payload = _payload(response)

    assert response.status_code == 400
    assert payload["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_oauth_popup_completes_pkce_flow_and_binds_mcp_resource(
    oauth_routes, monkeypatch
):
    """回归：授权页弹出后必须能完整走通 code + PKCE + resource 换 token。"""
    client_id = "client-browser"
    redirect_uri = "https://client.example/callback"
    resource = "https://ombre.example/mcp"
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    oauth_mod._oauth_clients[client_id] = {
        "redirect_uris": [redirect_uri],
        "client_name": "Browser Client",
    }
    monkeypatch.setattr(oauth_mod.sh, "_is_setup_needed", lambda: False)
    monkeypatch.setattr(
        oauth_mod.sh, "_verify_any_password", lambda password: password == "secret"
    )

    authorize_get = await oauth_routes[("GET", "/oauth/authorize")](
        JsonRequest(
            method="GET",
            query_params={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "state": "state-1",
                "scope": "mcp",
                "resource": resource,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
    )
    assert authorize_get.status_code == 200
    assert f'name="resource" value="{resource}"' in authorize_get.body.decode()

    authorize_post = await oauth_routes[("POST", "/oauth/authorize")](
        JsonRequest({
            "password": "secret",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": "state-1",
            "scope": "mcp",
            "resource": resource,
            "code_challenge": challenge,
        })
    )
    assert authorize_post.status_code == 302
    location = authorize_post.headers["location"]
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
    assert query["state"] == ["state-1"]
    code = query["code"][0]

    token_response = await oauth_routes[("POST", "/oauth/token")](
        JsonRequest({
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "resource": resource,
        })
    )
    token = _payload(token_response)

    assert token_response.status_code == 200
    assert token_response.headers["cache-control"] == "no-store"
    assert 0 < token["expires_in"] < 2_147_483_647
    assert oauth_mod._is_valid_mcp_token(token["access_token"], resource) is True
    assert oauth_mod._is_valid_mcp_token(
        token["access_token"], "https://other.example/mcp"
    ) is False

    refresh_response = await oauth_routes[("POST", "/oauth/token")](
        JsonRequest({
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": client_id,
            "resource": resource,
        })
    )
    refreshed = _payload(refresh_response)
    assert refresh_response.status_code == 200
    assert oauth_mod._is_valid_mcp_token(refreshed["access_token"], resource) is True


@pytest.mark.asyncio
async def test_oauth_popup_explains_missing_dashboard_setup(oauth_routes, monkeypatch):
    oauth_mod._oauth_clients["client-setup"] = {
        "redirect_uris": ["https://client.example/callback"],
        "client_name": "Setup Client",
    }
    monkeypatch.setattr(oauth_mod.sh, "_is_setup_needed", lambda: True)

    response = await oauth_routes[("GET", "/oauth/authorize")](
        JsonRequest(
            method="GET",
            query_params={
                "client_id": "client-setup",
                "redirect_uri": "https://client.example/callback",
                "response_type": "code",
                "resource": "https://ombre.example/mcp",
                "code_challenge": "s" * 43,
                "code_challenge_method": "S256",
            },
        )
    )

    assert response.status_code == 503
    assert "尚未设置 Dashboard 密码" in response.body.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        [],
        {"redirect_uris": "https://client.example/callback"},
        {"redirect_uris": ["javascript:alert(1)"]},
        {"redirect_uris": ["file:///tmp/token"]},
        {"redirect_uris": ["http://attacker.example/callback"]},
        {"redirect_uris": ["https://user:pass@client.example/callback"]},
    ],
)
async def test_oauth_registration_rejects_unsafe_metadata(oauth_routes, body):
    response = await oauth_routes[("POST", "/oauth/register")](JsonRequest(body))

    assert response.status_code == 400
    assert _payload(response)["error"] == "invalid_client_metadata"


@pytest.mark.asyncio
async def test_oauth_registration_allows_https_loopback_and_native_callbacks(
    oauth_routes,
):
    callbacks = [
        "https://client.example/callback",
        "http://127.0.0.1:8765/callback",
        "vscode://ombre/callback",
    ]

    response = await oauth_routes[("POST", "/oauth/register")](
        JsonRequest({"redirect_uris": callbacks, "client_name": "Safe Client"})
    )

    assert response.status_code == 201
    assert _payload(response)["redirect_uris"] == callbacks


@pytest.mark.asyncio
async def test_oauth_registration_state_is_bounded(
    oauth_routes, monkeypatch
):
    monkeypatch.setattr(oauth_mod, "_MAX_OAUTH_CLIENTS", 1)
    body = {"redirect_uris": ["https://client.example/callback"]}

    first = await oauth_routes[("POST", "/oauth/register")](JsonRequest(body))
    second = await oauth_routes[("POST", "/oauth/register")](JsonRequest(body))

    assert first.status_code == 201
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_oauth_authorize_password_failures_share_login_lockout(
    oauth_routes, monkeypatch
):
    oauth_mod._oauth_clients["client-rate"] = {
        "redirect_uris": ["https://client.example/callback"],
        "client_name": "Rate Test",
    }
    monkeypatch.setattr(oauth_mod.sh, "_is_setup_needed", lambda: False)
    monkeypatch.setattr(oauth_mod.sh, "_verify_any_password", lambda _password: False)
    body = {
        "password": "wrong",
        "client_id": "client-rate",
        "redirect_uri": "https://client.example/callback",
        "scope": "mcp",
        "resource": "https://ombre.example/mcp",
        "code_challenge": "c" * 43,
    }

    for _ in range(oauth_mod.sh._LOGIN_MAX_FAILURES):
        response = await oauth_routes[("POST", "/oauth/authorize")](
            JsonRequest(body, client_host="198.51.100.40")
        )
        assert response.status_code == 401

    locked = await oauth_routes[("POST", "/oauth/authorize")](
        JsonRequest(body, client_host="198.51.100.40")
    )
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0


@pytest.mark.asyncio
async def test_oauth_authorize_rejects_invalid_scope_and_pkce(
    oauth_routes, monkeypatch
):
    oauth_mod._oauth_clients["client-validation"] = {
        "redirect_uris": ["https://client.example/callback"],
        "client_name": "Validation Test",
    }
    monkeypatch.setattr(oauth_mod.sh, "_is_setup_needed", lambda: False)
    base = {
        "client_id": "client-validation",
        "redirect_uri": "https://client.example/callback",
        "response_type": "code",
        "resource": "https://ombre.example/mcp",
        "code_challenge_method": "S256",
    }

    bad_scope = await oauth_routes[("GET", "/oauth/authorize")](
        JsonRequest(
            method="GET",
            query_params={**base, "scope": "mcp admin", "code_challenge": "c" * 43},
        )
    )
    bad_pkce = await oauth_routes[("GET", "/oauth/authorize")](
        JsonRequest(
            method="GET",
            query_params={**base, "scope": "mcp", "code_challenge": "short"},
        )
    )

    assert bad_scope.status_code == 400
    assert bad_pkce.status_code == 400


def test_oauth_forwarded_host_is_only_used_from_trusted_proxy(monkeypatch):
    monkeypatch.setenv("OMBRE_TRUSTED_PROXY_CIDRS", "127.0.0.0/8")
    headers = {
        "host": "ombre.example",
        "x-forwarded-host": "evil.example",
        "x-forwarded-proto": "http",
    }

    direct = JsonRequest(headers=headers, client_host="198.51.100.4")
    proxied = JsonRequest(headers=headers, client_host="127.0.0.1")

    assert oauth_mod._public_base_url(direct) == "https://ombre.example"
    assert oauth_mod._public_base_url(proxied) == "http://evil.example"
