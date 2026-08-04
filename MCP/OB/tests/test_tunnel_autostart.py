import json
from pathlib import Path

import pytest

from web import tunnel


ROOT = Path(__file__).resolve().parents[1]


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
    def __init__(self, body=None):
        self._body = body

    async def json(self):
        return self._body


def _payload(response):
    return json.loads(response.body.decode("utf-8"))


@pytest.fixture
def tunnel_routes(monkeypatch, tmp_path):
    monkeypatch.setattr(tunnel.sh, "_require_auth", lambda _request: None)
    monkeypatch.setattr(tunnel.sh, "config", {"buckets_dir": str(tmp_path)})
    monkeypatch.setattr(tunnel, "_tunnel_proc", None)
    monkeypatch.setattr(tunnel, "_tunnel_last_error", "")

    mcp = FakeMCP()
    tunnel.register(mcp)
    return mcp.routes, tmp_path


@pytest.mark.asyncio
async def test_autostart_can_be_enabled_without_resending_saved_token(tunnel_routes):
    routes, buckets_dir = tunnel_routes
    config_path = buckets_dir / ".tunnel_config.json"
    config_path.write_text(
        json.dumps({"token": "existing-token", "auto_start": False}),
        encoding="utf-8",
    )

    response = await routes[("POST", "/api/tunnel/config")](
        JsonRequest({"auto_start": True})
    )

    assert response.status_code == 200
    assert _payload(response) == {
        "ok": True,
        "token_set": True,
        "auto_start": True,
        "persisted": True,
    }
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "token": "existing-token",
        "auto_start": True,
    }

    status = await routes[("GET", "/api/tunnel/status")](JsonRequest())
    assert _payload(status)["auto_start"] is True


@pytest.mark.asyncio
async def test_token_only_update_does_not_reset_saved_autostart(tunnel_routes):
    routes, buckets_dir = tunnel_routes
    config_path = buckets_dir / ".tunnel_config.json"
    config_path.write_text(json.dumps({"auto_start": True}), encoding="utf-8")

    response = await routes[("POST", "/api/tunnel/config")](
        JsonRequest({"token": "new-token"})
    )

    assert response.status_code == 200
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "auto_start": True,
        "token": "new-token",
    }


@pytest.mark.asyncio
async def test_invalid_autostart_does_not_change_tunnel_config(tunnel_routes):
    routes, buckets_dir = tunnel_routes
    config_path = buckets_dir / ".tunnel_config.json"
    original = {"token": "existing-token", "auto_start": False}
    config_path.write_text(json.dumps(original), encoding="utf-8")

    response = await routes[("POST", "/api/tunnel/config")](
        JsonRequest({"auto_start": "sometimes"})
    )

    assert response.status_code == 400
    assert json.loads(config_path.read_text(encoding="utf-8")) == original


@pytest.mark.asyncio
async def test_save_failure_is_reported_and_does_not_claim_persistence(
    tunnel_routes, monkeypatch
):
    routes, _buckets_dir = tunnel_routes

    def fail_save(_data):
        raise OSError("read-only volume")

    monkeypatch.setattr(tunnel, "_save_tunnel_config", fail_save)
    response = await routes[("POST", "/api/tunnel/config")](
        JsonRequest({"auto_start": True})
    )

    assert response.status_code == 500
    payload = _payload(response)
    assert "read-only volume" in payload["error"]


def test_dashboard_autostart_switch_saves_independently_and_rolls_back_on_error():
    dashboard = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")

    assert 'onclick="toggleTunnelAutoStart(this)"' in dashboard
    assert "body: JSON.stringify({auto_start: autoStart})" in dashboard
    assert "setHwSwitch('tunnel-autostart', previous)" in dashboard
    assert "if (!data.persisted)" in dashboard
    assert "if (!_tunnelAutoStartSaving) setHwSwitch('tunnel-autostart', d.auto_start)" in dashboard
    assert "tunnel-auth-danger" in dashboard
