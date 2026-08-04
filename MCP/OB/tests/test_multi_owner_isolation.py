"""多人共用一套 OB 时的记忆隔离测试（存储层，网络无关）。

验证核心保证：每个人跑一个独立实例（独立 OMBRE_VAULT_DIR），一个人的记忆
不会出现在另一个人的库里；两个库的向量库路径也各自独立、不共享。
"""
import asyncio
import os

from utils import load_config
from bucket_manager import BucketManager


def _write_memory(buckets_dir: str, name: str, content: str) -> None:
    """直接往某个库的 permanent 目录写一个桶 .md，模拟一条已存记忆。"""
    pdir = os.path.join(buckets_dir, "permanent")
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(
            "---\n"
            f"id: {name}\n"
            "type: permanent\n"
            "importance: 5\n"
            "---\n\n"
            f"{content}\n"
        )


def test_two_owners_memory_isolated(monkeypatch, tmp_path):
    vault_a = tmp_path / "vault-ming"
    vault_b = tmp_path / "vault-hong"

    # 用一个不存在的 config 路径，强制走内置默认，避免读到仓库里的真实 config.yaml
    monkeypatch.setenv("OMBRE_CONFIG_PATH", str(tmp_path / "nope.yaml"))
    monkeypatch.delenv("OMBRE_BUCKETS_DIR", raising=False)

    # 小明的实例
    monkeypatch.setenv("OMBRE_VAULT_DIR", str(vault_a))
    config_a = load_config()

    # 小红的实例
    monkeypatch.setenv("OMBRE_VAULT_DIR", str(vault_b))
    config_b = load_config()

    # 两个库目录必须各自独立
    assert config_a["buckets_dir"] == str(vault_a)
    assert config_b["buckets_dir"] == str(vault_b)
    assert config_a["buckets_dir"] != config_b["buckets_dir"]

    # 向量库 / 脱水缓存也各自独立（都落在各自 buckets_dir 下）
    emb_a = os.path.join(config_a["buckets_dir"], "embeddings.db")
    emb_b = os.path.join(config_b["buckets_dir"], "embeddings.db")
    assert emb_a != emb_b

    # 小明写一条记忆
    _write_memory(config_a["buckets_dir"], "ming_secret", "小明的秘密：喜欢猫")

    mgr_a = BucketManager(config_a)
    mgr_b = BucketManager(config_b)

    stats_a = asyncio.run(mgr_a.get_stats())
    stats_b = asyncio.run(mgr_b.get_stats())

    # 小明库里看得到，小红库里完全看不到 → 记忆隔离成立
    assert stats_a["permanent_count"] == 1
    assert stats_b["permanent_count"] == 0

    ids_b = [b.get("id") for b in asyncio.run(mgr_b.list_all())]
    assert "ming_secret" not in ids_b


def test_legacy_buckets_dir_still_isolates(monkeypatch, tmp_path):
    """旧变量 OMBRE_BUCKETS_DIR 也应正确隔离（向后兼容）。"""
    vault = tmp_path / "vault-legacy"
    monkeypatch.setenv("OMBRE_CONFIG_PATH", str(tmp_path / "nope.yaml"))
    monkeypatch.delenv("OMBRE_VAULT_DIR", raising=False)
    monkeypatch.setenv("OMBRE_BUCKETS_DIR", str(vault))

    config = load_config()
    assert config["buckets_dir"] == str(vault)
