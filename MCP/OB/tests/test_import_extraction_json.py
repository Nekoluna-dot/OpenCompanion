from import_memory import ImportEngine


def test_clean_llm_json_extracts_first_balanced_json_value():
    from utils import clean_llm_json

    raw = '说明：{"ok": true, "items": [1, 2]} done'

    assert clean_llm_json(raw) == '{"ok": true, "items": [1, 2]}'


def test_import_extraction_accepts_json_array_with_model_chatter():
    raw = """
可以，下面是我从这段对话里提取出的记忆：
[
  {
    "name": "偏好",
    "content": "用户更喜欢 Dashboard 批量导入能容忍模型在 JSON 外补充说明。",
    "domain": ["AI"],
    "valence": 0.6,
    "arousal": 0.4,
    "tags": ["导入", "DeepSeek"],
    "importance": 6,
    "preserve_raw": false,
    "is_pattern": false
  }
]
如果需要，我也可以继续帮你细分。
"""

    items = ImportEngine._parse_extraction(raw)

    assert len(items) == 1
    assert items[0]["name"] == "偏好"
    assert items[0]["tags"] == ["导入", "DeepSeek"]
