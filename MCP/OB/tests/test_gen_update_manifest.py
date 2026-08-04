"""update_manifest.json 生成器 + 与 do-update 校验器的往返测试（谨慎加固 B1）。

生成器产出的清单，必须能被 web/meta._plan_update_files 逐文件 sha256 校验通过。
这证明「发布侧生成清单」真正接上了「用户侧完整性校验」。
"""
import importlib.util
import io
import json
import zipfile
from pathlib import Path


import web.meta as meta

_GEN_PATH = Path(__file__).resolve().parents[1] / "deploy" / "gen_update_manifest.py"
_spec = importlib.util.spec_from_file_location("gen_update_manifest", _GEN_PATH)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

_TOP = "Ombre-Brain-main/"


def _fake_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "src" / "server.py").write_bytes(b"print('hello')\n")
    (tmp_path / "src" / "util.py").write_bytes(b"x = 1\n")
    (tmp_path / "frontend" / "app.js").write_bytes(b"// js\n")
    (tmp_path / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    # 缓存产物必须被生成器忽略
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "server.cpython-312.pyc").write_bytes(b"junk")
    return tmp_path


def test_manifest_excludes_pycache(tmp_path):
    repo = _fake_repo(tmp_path)
    m = gen.build_manifest(str(repo))
    paths = {e["path"] for e in m["files"]}
    assert paths == {"src/server.py", "src/util.py", "frontend/app.js"}
    assert m["version"] == "9.9.9"


def test_generated_manifest_passes_do_update_verifier(tmp_path):
    repo = _fake_repo(tmp_path)
    manifest = gen.build_manifest(str(repo))

    # 用真实文件内容 + 生成的清单打一个 release zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for e in manifest["files"]:
            zf.writestr(_TOP + e["path"], (repo / e["path"]).read_bytes())
        zf.writestr(_TOP + "update_manifest.json", json.dumps(manifest))
    buf.seek(0)

    with zipfile.ZipFile(buf) as zf:
        plan = meta._plan_update_files(zf, _TOP)

    assert plan["abort"] is None
    assert plan["verified"] is True
    assert set(plan["files"]) == {"src/server.py", "src/util.py", "frontend/app.js"}


def test_tampered_file_against_generated_manifest_aborts(tmp_path):
    repo = _fake_repo(tmp_path)
    manifest = gen.build_manifest(str(repo))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for e in manifest["files"]:
            content = (repo / e["path"]).read_bytes()
            if e["path"] == "src/server.py":
                content = b"print('TAMPERED')\n"   # 篡改一个文件
            zf.writestr(_TOP + e["path"], content)
        zf.writestr(_TOP + "update_manifest.json", json.dumps(manifest))
    buf.seek(0)

    with zipfile.ZipFile(buf) as zf:
        plan = meta._plan_update_files(zf, _TOP)

    assert plan["abort"] is not None
    assert plan["files"] == {}
