"""构建期 cloudflared 下载脚本的架构映射 / URL / 重试回归测试（用户反馈 #3）。

只测纯逻辑（不真的联网下载）：架构名映射、release URL 拼接、重试后成功/失败。
"""
import importlib.util
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "deploy" / "fetch_cloudflared.py"
_spec = importlib.util.spec_from_file_location("fetch_cloudflared", _MOD_PATH)
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


def test_arch_mapping_covers_common_platforms():
    assert fc.cloudflared_arch("x86_64") == "amd64"
    assert fc.cloudflared_arch("aarch64") == "arm64"
    assert fc.cloudflared_arch("armv7l") == "arm"
    assert fc.cloudflared_arch("i686") == "386"
    assert fc.cloudflared_arch("AMD64") == "amd64"  # 大小写不敏感


def test_arch_mapping_rejects_unknown():
    with pytest.raises(SystemExit):
        fc.cloudflared_arch("sparc64")


def test_release_url_shape():
    url = fc.release_url("amd64")
    assert url.startswith("https://github.com/cloudflare/cloudflared/releases/latest/download/")
    assert url.endswith("cloudflared-linux-amd64")


def test_download_retries_then_succeeds(monkeypatch, tmp_path):
    calls = {"n": 0}

    class _FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self, *_a):
            return b""

    def _fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("502 Bad Gateway")
        return _FakeResp()

    def _fake_copy(src, dst):
        dst.write(b"BINARY")

    monkeypatch.setattr(fc.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(fc.shutil, "copyfileobj", _fake_copy)
    monkeypatch.setattr(fc.time, "sleep", lambda *_a: None)

    dest = tmp_path / "cloudflared"
    fc.download("https://example/cf", str(dest), attempts=5)
    assert calls["n"] == 3
    assert dest.read_bytes() == b"BINARY"


def test_download_fails_after_all_retries(monkeypatch, tmp_path):
    def _always_fail(req, timeout=0):
        raise OSError("502 Bad Gateway")

    monkeypatch.setattr(fc.urllib.request, "urlopen", _always_fail)
    monkeypatch.setattr(fc.time, "sleep", lambda *_a: None)

    with pytest.raises(SystemExit):
        fc.download("https://example/cf", str(tmp_path / "cloudflared"), attempts=3)
