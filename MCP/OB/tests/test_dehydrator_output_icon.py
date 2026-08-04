"""dehydrator._format_output 图标语义回归测试。

历史 bug：无条件用 `📌 记忆桶:` 作前缀，导致 breath 浮现里每条普通动态记忆
都顶着 📌，与 docs/CLAUDE_PROMPT.md「带 📌 的是我钉的核心准则」的约定冲突
（pulse 用的是正确的 💭/📌 分级）。现在图标按 pinned/type 区分，与 pulse 一致。
"""
import pytest

from dehydrator import Dehydrator


@pytest.fixture
def dehy(tmp_path):
    return Dehydrator({
        "buckets_dir": str(tmp_path),
        "dehydration": {"api_key": "x", "model": "m", "base_url": "http://x"},
    })


def _header(dehy, meta):
    return dehy._format_output("正文内容", meta).splitlines()[0]


def test_plain_dynamic_bucket_is_not_pinned_icon(dehy):
    line = _header(dehy, {"name": "普通事", "type": "dynamic", "domain": ["工作"]})
    assert line.startswith("💭 记忆桶: 普通事")
    assert "📌" not in line


@pytest.mark.parametrize("meta,icon", [
    ({"name": "核心", "pinned": True}, "📌"),
    ({"name": "受保护", "protected": True}, "📌"),
    ({"name": "固化", "type": "permanent"}, "📦"),
    ({"name": "感受", "type": "feel"}, "🫧"),
    ({"name": "计划", "type": "plan"}, "📋"),
    ({"name": "信", "type": "letter"}, "💌"),
    ({"name": "日常", "type": "dynamic"}, "💭"),
])
def test_icon_matches_pulse_scheme(dehy, meta, icon):
    assert _header(dehy, meta).startswith(f"{icon} 记忆桶: {meta['name']}")


# --- 脱水 JSON 渲染：长内容脱水返回结构化 JSON 时，breath 不该显示原始 JSON ---

def test_dehydrated_json_renders_summary_not_raw(dehy):
    import json
    payload = json.dumps({
        "core_facts": ["与产品经理开会", "分歧在多租户 SaaS"],
        "emotion_state": "担心",
        "todos": ["周五前出风险评估"],
        "keywords": ["会议", "SaaS"],
        "summary": "讨论商业化，分歧在 SaaS 隐私，周五出评估",
    }, ensure_ascii=False)
    out = dehy._format_output(payload, {"name": "商业化讨论", "type": "dynamic"})

    # 不能出现原始 JSON 结构 / 内部字段
    assert "{" not in out and "core_facts" not in out and "keywords" not in out
    assert "emotion_state" not in out
    # summary、核心事实、待办都被可读地呈现
    assert "讨论商业化，分歧在 SaaS 隐私，周五出评估" in out
    assert "与产品经理开会" in out
    assert "待办：周五前出风险评估" in out


def test_dehydrated_json_without_summary_falls_back_to_facts(dehy):
    import json
    payload = json.dumps({"core_facts": ["事实A", "事实B"], "keywords": ["k"]}, ensure_ascii=False)
    out = dehy._format_output(payload, {"name": "x", "type": "dynamic"})
    assert "事实A" in out and "事实B" in out
    assert "core_facts" not in out and "{" not in out


def test_plain_text_content_passes_through(dehy):
    out = dehy._format_output("这是一段普通原文，不是 JSON。", {"name": "x", "type": "dynamic"})
    assert "这是一段普通原文，不是 JSON。" in out
