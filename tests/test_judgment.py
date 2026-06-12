"""判断队列契约：稳定 id（跨进程可比）+ 杠杆映射。"""

from agentic_studio.core.judgment import LEVERAGE, JudgmentItem


def test_make_id_is_stable_and_deterministic():
    a = JudgmentItem.make("gap", "1.1", "缺人口数据")
    b = JudgmentItem.make("gap", "1.1", "缺人口数据")
    assert a.id == b.id  # crc32：同输入恒同 id（hash() 每进程随机化，不可用）
    assert a.id.startswith("gap-1.1-")


def test_ungrounded_number_is_top_leverage():
    assert LEVERAGE["ungrounded_number"] == 5
    it = JudgmentItem.make("ungrounded_number", "4.1", "数字 0.02 未见于证据")
    assert it.leverage == 5
