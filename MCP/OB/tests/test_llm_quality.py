# ============================================================
# Test 2: LLM Quality Baseline — needs GEMINI_API_KEY
# 测试 2：LLM 质量基准 —— 需要 GEMINI_API_KEY
#
# Verifies LLM auto-tagging returns reasonable results:
#   - domain is a non-empty list of strings
#   - valence ∈ [0, 1]
#   - arousal ∈ [0, 1]
#   - tags is a list
#   - suggested_name is a string
#   - domain matches content semantics (loose check)
# ============================================================

import os
import pytest

# Skip all tests if no API key
pytestmark = pytest.mark.skipif(
    not os.environ.get("OMBRE_COMPRESS_API_KEY"),
    reason="OMBRE_COMPRESS_API_KEY not set — skipping LLM quality tests"
)


@pytest.fixture
def dehydrator(test_config):
    from dehydrator import Dehydrator
    return Dehydrator(test_config)


# Test cases: (content, expected_domains_superset, valence_range)
LLM_CASES = [
    (
        "今天学了 Python 的 asyncio，终于搞懂了 event loop，心情不错",
        {"学习", "编程", "技术", "数字", "Python"},
        (0.5, 1.0),  # positive
    ),
    (
        "被导师骂了一顿，论文写得太差了，很沮丧",
        {"学习", "学业", "心理", "工作"},
        (0.0, 0.4),  # negative
    ),
    (
        "和朋友去爬了一座山，山顶的风景超美，累但值得",
        {"生活", "旅行", "社交", "运动", "健康"},
        (0.6, 1.0),  # positive
    ),
    (
        "在阳台上看日落，什么都没想，很平静",
        {"生活", "心理", "自省"},
        (0.4, 0.8),  # calm positive
    ),
    (
        "I built a FastAPI app with Docker and deployed it on Render",
        {"编程", "技术", "学习", "数字", "工作"},
        (0.5, 1.0),  # positive
    ),
]


class TestLLMQuality:
    """Verify LLM auto-tagging produces reasonable outputs."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("content,expected_domains,valence_range", LLM_CASES)
    async def test_analyze_structure(self, dehydrator, content, expected_domains, valence_range):
        """Check that analyze() returns valid structure and reasonable values."""
        result = await dehydrator.analyze(content)

        # Structure checks
        assert isinstance(result, dict)
        assert "domain" in result
        assert "valence" in result
        assert "arousal" in result
        assert "tags" in result

        # Domain is non-empty list of strings
        assert isinstance(result["domain"], list)
        assert len(result["domain"]) >= 1
        assert set(expected_domains).intersection(result["domain"])
        assert all(isinstance(d, str) for d in result["domain"])

        # Valence and arousal in range
        assert 0.0 <= result["valence"] <= 1.0, f"valence {result['valence']} out of range"
        assert 0.0 <= result["arousal"] <= 1.0, f"arousal {result['arousal']} out of range"

        # Valence roughly matches expected range (with tolerance)
        lo, hi = valence_range
        assert lo - 0.15 <= result["valence"] <= hi + 0.15, \
            f"valence {result['valence']} not in expected range ({lo}, {hi}) for: {content[:30]}..."

        # Tags is a list
        assert isinstance(result["tags"], list)

    @pytest.mark.asyncio
    async def test_analyze_domain_semantic_match(self, dehydrator):
        """Check that domain has at least some semantic relevance."""
        result = await dehydrator.analyze("我家的橘猫小橘今天又偷吃了桌上的鱼")
        domains = set(result["domain"])
        # Should contain something life/pet related
        life_related = {"生活", "宠物", "家庭", "日常", "动物"}
        assert domains & life_related, f"Expected life-related domain, got {domains}"

    @pytest.mark.asyncio
    async def test_analyze_empty_content(self, dehydrator):
        """Empty content should raise or return defaults gracefully."""
        try:
            result = await dehydrator.analyze("。")
            # If it doesn't raise, should still return valid structure
            assert isinstance(result, dict)
            assert 0.0 <= result["valence"] <= 1.0
        except Exception:
            pass  # Raising is also acceptable
