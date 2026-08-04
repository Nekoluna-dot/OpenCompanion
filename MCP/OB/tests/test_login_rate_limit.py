"""登录失败限流 / 指数退避锁定回归测试（防在线密码爆破）。

对应安全加固 #4：/auth/login、/auth/recover 之前无任何失败计数，
在线爆破完全不受限。现在按客户端标识做滑窗计数 + 指数退避锁定。
"""
import time

import pytest

import web._shared as sh


class DummyRequest:
    def __init__(self, *, headers=None, client_host="1.2.3.4"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": client_host})()


@pytest.fixture(autouse=True)
def _clear_state():
    sh._login_failures.clear()
    sh._login_locked_until.clear()
    yield
    sh._login_failures.clear()
    sh._login_locked_until.clear()


def test_not_limited_before_threshold():
    req = DummyRequest()
    for _ in range(sh._LOGIN_MAX_FAILURES - 1):
        sh._record_login_failure(req)
    assert sh._login_retry_after(req) == 0


def test_locks_after_threshold():
    req = DummyRequest()
    for _ in range(sh._LOGIN_MAX_FAILURES):
        sh._record_login_failure(req)
    retry = sh._login_retry_after(req)
    assert retry > 0
    assert retry <= sh._LOGIN_MAX_LOCK_SECONDS + 1


def test_success_clears_lock():
    req = DummyRequest()
    for _ in range(sh._LOGIN_MAX_FAILURES + 2):
        sh._record_login_failure(req)
    assert sh._login_retry_after(req) > 0
    sh._record_login_success(req)
    assert sh._login_retry_after(req) == 0
    assert req.client.host not in sh._login_failures


def test_lock_grows_with_more_failures():
    req = DummyRequest()
    for _ in range(sh._LOGIN_MAX_FAILURES):
        sh._record_login_failure(req)
    first = sh._login_locked_until[sh._client_key(req)]
    # 再连续失败若干次，锁定截止时间应被推后（指数退避）
    for _ in range(3):
        sh._record_login_failure(req)
    later = sh._login_locked_until[sh._client_key(req)]
    assert later > first


def test_different_clients_isolated():
    a = DummyRequest(client_host="10.0.0.1")
    b = DummyRequest(client_host="10.0.0.2")
    for _ in range(sh._LOGIN_MAX_FAILURES + 1):
        sh._record_login_failure(a)
    assert sh._login_retry_after(a) > 0
    assert sh._login_retry_after(b) == 0


def test_client_key_prefers_forwarded_for_from_trusted_proxy(monkeypatch):
    monkeypatch.setenv("OMBRE_TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    req = DummyRequest(headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, client_host="10.0.0.1")
    assert sh._client_key(req) == "203.0.113.9"


def test_client_key_ignores_spoofed_forwarded_for_from_direct_client(monkeypatch):
    monkeypatch.setenv("OMBRE_TRUSTED_PROXY_CIDRS", "127.0.0.0/8,::1/128")
    req = DummyRequest(
        headers={"x-forwarded-for": "203.0.113.9"},
        client_host="198.51.100.24",
    )

    assert sh._client_key(req) == "198.51.100.24"


def test_client_key_ignores_invalid_forwarded_ip(monkeypatch):
    monkeypatch.setenv("OMBRE_TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    req = DummyRequest(
        headers={"x-forwarded-for": "not-an-ip"}, client_host="10.0.0.1"
    )

    assert sh._client_key(req) == "10.0.0.1"


def test_lock_expires(monkeypatch):
    req = DummyRequest()
    for _ in range(sh._LOGIN_MAX_FAILURES):
        sh._record_login_failure(req)
    key = sh._client_key(req)
    # 把锁定截止时间挪到过去 → 视为已解锁并清理
    sh._login_locked_until[key] = time.time() - 1
    assert sh._login_retry_after(req) == 0
    assert key not in sh._login_locked_until
