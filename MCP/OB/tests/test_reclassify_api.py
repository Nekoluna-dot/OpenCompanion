import frontmatter
import pytest

from reclassify_api import reclassify, sanitize


class FixedAnalyzer:
    def __init__(self, result):
        self.result = result
        self.inputs = []

    async def analyze(self, content):
        self.inputs.append(content)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _write_legacy_bucket(vault, *, bucket_id="abc123def456", content="Original\nbody."):
    source_dir = vault / "dynamic" / "未分类"
    source_dir.mkdir(parents=True)
    source = source_dir / f"old_{bucket_id}.md"
    post = frontmatter.Post(
        content,
        id=bucket_id,
        name="Old name",
        domain=["未分类"],
        tags=["old"],
        valence=0.1,
        arousal=0.2,
    )
    source.write_text(frontmatter.dumps(post), encoding="utf-8")
    return source, frontmatter.load(source).content


@pytest.mark.asyncio
async def test_reclassify_moves_metadata_but_preserves_content_exactly(tmp_path):
    vault = tmp_path / "vault"
    source, original_content = _write_legacy_bucket(
        vault,
        content="First line.\n\nSecond line with [brackets] and punctuation!",
    )
    analyzer = FixedAnalyzer(
        {
            "domain": ["工作"],
            "tags": ["项目", "项目", "测试"],
            "suggested_name": "New name",
            "valence": 0.8,
            "arousal": 0.6,
        }
    )
    messages = []

    summary = await reclassify(
        {"buckets_dir": str(vault)},
        analyzer=analyzer,
        emit=messages.append,
    )

    destination = vault / "dynamic" / "工作" / "New name_abc123def456.md"
    assert summary == {"found": 1, "updated": 1, "failed": 0, "skipped": 0}
    assert not source.exists()
    assert destination.exists()
    moved = frontmatter.load(destination)
    assert moved.content == original_content
    assert moved.metadata["domain"] == ["工作"]
    assert moved.metadata["tags"] == ["项目", "测试"]
    assert moved.metadata["valence"] == 0.8
    assert moved.metadata["arousal"] == 0.6
    assert analyzer.inputs == [f"Old name\n{original_content}"[:2000]]


@pytest.mark.asyncio
async def test_reclassify_normalizes_nonfinite_analysis_values(tmp_path):
    vault = tmp_path / "vault"
    _write_legacy_bucket(vault)
    analyzer = FixedAnalyzer(
        {
            "domain": "测试",
            "tags": "single",
            "suggested_name": "Finite values",
            "valence": float("nan"),
            "arousal": float("inf"),
        }
    )

    summary = await reclassify(
        {"buckets_dir": str(vault)},
        analyzer=analyzer,
        emit=lambda _message: None,
    )

    destination = vault / "dynamic" / "测试" / "Finite values_abc123def456.md"
    moved = frontmatter.load(destination)
    assert summary["updated"] == 1
    assert moved.metadata["valence"] == 0.5
    assert moved.metadata["arousal"] == 0.3


@pytest.mark.asyncio
async def test_reclassify_never_overwrites_an_existing_destination(tmp_path):
    vault = tmp_path / "vault"
    source, original_content = _write_legacy_bucket(vault)
    destination = vault / "dynamic" / "工作" / "Collision_abc123def456.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("existing memory", encoding="utf-8")
    analyzer = FixedAnalyzer(
        {
            "domain": ["工作"],
            "tags": [],
            "suggested_name": "Collision",
            "valence": 0.5,
            "arousal": 0.3,
        }
    )

    summary = await reclassify(
        {"buckets_dir": str(vault)},
        analyzer=analyzer,
        emit=lambda _message: None,
    )

    assert summary == {"found": 1, "updated": 0, "failed": 1, "skipped": 0}
    assert source.exists()
    assert frontmatter.load(source).content == original_content
    assert destination.read_text(encoding="utf-8") == "existing memory"


@pytest.mark.asyncio
async def test_reclassify_analyzer_failure_leaves_source_byte_identical(tmp_path):
    vault = tmp_path / "vault"
    source, _content = _write_legacy_bucket(vault)
    before = source.read_bytes()

    summary = await reclassify(
        {"buckets_dir": str(vault)},
        analyzer=FixedAnalyzer(TimeoutError("provider unavailable")),
        emit=lambda _message: None,
    )

    assert summary["failed"] == 1
    assert source.read_bytes() == before


@pytest.mark.asyncio
async def test_reclassify_empty_vault_does_not_construct_analyzer(tmp_path):
    summary = await reclassify(
        {"buckets_dir": str(tmp_path / "empty")},
        analyzer=None,
        emit=lambda _message: None,
    )

    assert summary == {"found": 0, "updated": 0, "failed": 0, "skipped": 0}


def test_reclassify_sanitize_removes_path_components():
    assert sanitize("../../unsafe:name") == "unsafename"
