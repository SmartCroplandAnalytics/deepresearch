"""统一装配：[id]→[N] 首次出现序重编号 + 来源列表。"""

from agentic_studio.infra.writing.assemble import assemble


def test_renumber_first_appearance_order():
    drafted = [
        {"heading": "## 1 甲", "text": "甲 [B] 又 [A]。"},
        {"heading": "## 2 乙", "text": "乙 [A] 再 [C]。"},
    ]
    body, refs = assemble(drafted, lambda nid: f"src-{nid}", ref_heading="## 数据来源")
    assert "[1]" in body and "甲 [1] 又 [2]" in body  # B=1, A=2
    assert "乙 [2] 再 [3]" in body
    assert refs.splitlines()[0] == "## 数据来源"
    assert "[1] src-B" in refs and "[2] src-A" in refs and "[3] src-C" in refs


def test_unknown_bracket_left_untouched():
    drafted = [{"heading": "## 1", "text": "见 [A]。坡度2-6°不变。"}]
    body, _ = assemble(drafted, lambda nid: nid)
    assert "坡度2-6°" in body  # 非 id 的括号文本不受影响
