"""GitHub 导入前备份闸门回归测试（记忆安全红蓝测试）。

导入会覆盖本地同名记忆、不可逆。若导入前的本地 zip 备份没成功，默认必须拦下，
除非用户显式 force=true。防止「备份悄悄失败 + 导入覆盖 = 记忆无法找回」。
"""
import pytest

from web import _shared as sh
from web import github as github_web


class FakeMcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def deco(fn):
            self.routes[(path, tuple(methods))] = fn
            return fn
        return deco


class FakeRequest:
    def __init__(self, body=None):
        self._body = body or {}
        self.headers = {}
        self.query_params = {}
        self.cookies = {}

    async def json(self):
        return self._body


class FakeSync:
    def __init__(self):
        self.called = False

    async def import_from_github(self, buckets_dir):
        self.called = True
        return {"ok": True, "imported": 3, "skipped": 0}


@pytest.fixture
def import_route(monkeypatch, tmp_path):
    mcp = FakeMcp()
    github_web.register(mcp)
    monkeypatch.setattr(sh, "_require_auth", lambda req: None)
    monkeypatch.setitem(sh.config, "buckets_dir", str(tmp_path))
    fake = FakeSync()
    monkeypatch.setattr(sh, "github_sync_instance", fake)
    monkeypatch.setattr(sh, "bucket_mgr", None)
    handler = mcp.routes[("/api/github/import", ("POST",))]
    return handler, fake


async def _run(handler, body=None):
    resp = await handler(FakeRequest(body or {}))
    import json as _j
    return resp.status_code, _j.loads(bytes(resp.body).decode("utf-8"))


@pytest.mark.asyncio
async def test_import_blocked_when_backup_fails(monkeypatch, import_route):
    handler, fake = import_route
    monkeypatch.setattr(github_web, "_pre_import_backup", lambda d: "")  # 备份失败
    status, data = await _run(handler)
    assert status == 409
    assert data.get("backup_failed") is True
    assert fake.called is False   # 关键：没有触碰本地记忆


@pytest.mark.asyncio
async def test_import_proceeds_when_backup_ok(monkeypatch, import_route):
    handler, fake = import_route
    monkeypatch.setattr(github_web, "_pre_import_backup", lambda d: "/backups/x.zip")
    status, data = await _run(handler)
    assert status == 200
    assert data.get("ok") is True
    assert fake.called is True


@pytest.mark.asyncio
async def test_force_overrides_failed_backup(monkeypatch, import_route):
    handler, fake = import_route
    monkeypatch.setattr(github_web, "_pre_import_backup", lambda d: "")
    status, data = await _run(handler, {"force": True})
    assert status == 200
    assert fake.called is True
