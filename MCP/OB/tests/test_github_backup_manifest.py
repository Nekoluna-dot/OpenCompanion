import base64
import hashlib
import json

import httpx
import pytest

from github_sync import GitHubSync


def _json_response(method: str, url: str, status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request(method, url),
    )


def test_backup_manifest_records_hashes_counts_and_bytes():
    sync = GitHubSync(token="token", repo="owner/repo", branch="main", path_prefix="ombre")

    manifest = sync._build_backup_manifest({
        "dynamic/a.md": b"alpha",
        "permanent/b.md": "你好".encode("utf-8"),
    })

    assert manifest["schema_version"] == 1
    assert manifest["source"] == "ombre-brain"
    assert manifest["repo"] == "owner/repo"
    assert manifest["branch"] == "main"
    assert manifest["path_prefix"] == "ombre"
    assert manifest["file_count"] == 2
    assert manifest["total_bytes"] == 5 + len("你好".encode("utf-8"))
    by_path = {item["path"]: item for item in manifest["files"]}
    assert by_path["dynamic/a.md"]["sha256"] == hashlib.sha256(b"alpha").hexdigest()
    assert by_path["dynamic/a.md"]["bytes"] == 5


@pytest.mark.asyncio
async def test_batch_commit_includes_backup_manifest_without_counting_it(monkeypatch):
    sync = GitHubSync(token="token", repo="owner/repo", branch="main", path_prefix="ombre")

    async def fake_request(_client, method: str, url: str, *, json=None, _max_retries=4):
        if method == "GET" and url.endswith("/git/ref/heads/main"):
            return _json_response(method, url, 200, {"object": {"sha": "head-sha"}})
        if method == "GET" and url.endswith("/git/commits/head-sha"):
            return _json_response(method, url, 200, {"tree": {"sha": "base-tree"}})
        if method == "POST" and url.endswith("/git/trees"):
            paths = {entry["path"] for entry in json["tree"]}
            assert "ombre/dynamic/a.md" in paths
            assert "ombre/_ombre_backup_manifest.json" in paths
            manifest_entry = next(e for e in json["tree"] if e["path"] == "ombre/_ombre_backup_manifest.json")
            manifest = json_module.loads(manifest_entry["content"])
            assert manifest["file_count"] == 1
            assert manifest["files"][0]["path"] == "dynamic/a.md"
            assert manifest["files"][0]["sha256"] == hashlib.sha256(b"alpha").hexdigest()
            return _json_response(method, url, 201, {"sha": "new-tree"})
        if method == "POST" and url.endswith("/git/commits"):
            assert json["tree"] == "new-tree"
            return _json_response(method, url, 201, {"sha": "commit-sha"})
        if method == "PATCH" and url.endswith("/git/refs/heads/main"):
            return _json_response(method, url, 200, {"ref": "refs/heads/main"})
        raise AssertionError(f"Unexpected GitHub API call: {method} {url}")

    json_module = json
    monkeypatch.setattr(sync, "_request", fake_request)

    uploaded = await sync._batch_commit({"dynamic/a.md": b"alpha"})

    assert uploaded == 1


@pytest.mark.asyncio
async def test_import_reads_backup_manifest_summary_when_present(monkeypatch, tmp_path):
    sync = GitHubSync(token="token", repo="owner/repo", branch="main", path_prefix="ombre")
    manifest = {
        "schema_version": 1,
        "generated_at": "2026-07-02T00:00:00+00:00",
        "file_count": 1,
        "total_bytes": 7,
        "files": [{"path": "dynamic/a.md", "bytes": 7, "sha256": "abc"}],
    }

    async def fake_request(_client, method: str, url: str, *, json=None, _max_retries=4):
        if method == "GET" and url.endswith("/git/ref/heads/main"):
            return _json_response(method, url, 200, {"object": {"sha": "head-sha"}})
        if method == "GET" and url.endswith("/git/commits/head-sha"):
            return _json_response(method, url, 200, {"tree": {"sha": "tree-sha"}})
        if method == "GET" and url.endswith("/git/trees/tree-sha?recursive=1"):
            return _json_response(method, url, 200, {
                "truncated": False,
                "tree": [
                    {"type": "blob", "path": "ombre/_ombre_backup_manifest.json", "sha": "manifest-sha"},
                    {"type": "blob", "path": "ombre/dynamic/a.md", "sha": "bucket-sha"},
                ],
            })
        if method == "GET" and url.endswith("/git/blobs/manifest-sha"):
            data = base64.b64encode(json_module.dumps(manifest).encode("utf-8")).decode()
            return _json_response(method, url, 200, {"encoding": "base64", "content": data})
        if method == "GET" and url.endswith("/git/blobs/bucket-sha"):
            data = base64.b64encode(b"# hello").decode()
            return _json_response(method, url, 200, {"encoding": "base64", "content": data})
        raise AssertionError(f"Unexpected GitHub API call: {method} {url}")

    json_module = json
    monkeypatch.setattr(sync, "_request", fake_request)

    result = await sync.import_from_github(str(tmp_path))

    assert result["ok"] is True
    assert result["imported"] == 1
    assert result["backup_manifest"] == {
        "present": True,
        "schema_version": 1,
        "generated_at": "2026-07-02T00:00:00+00:00",
        "file_count": 1,
        "total_bytes": 7,
    }
    assert (tmp_path / "dynamic" / "a.md").read_text(encoding="utf-8") == "# hello"

