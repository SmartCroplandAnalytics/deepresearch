"""写作微环确定性自检（count_words / cite_check / number_check）。"""

from agentic_studio.infra.writing.compose import cite_check, count_words, number_check


def test_count_words_cjk_plus_english():
    assert count_words("耕地面积 increase 显著") == 7  # 6 CJK 字 + 1 英文词


def test_cite_check_dangling_and_uncited():
    cc = cite_check("有据 [A]，无据 [X]。", ["A", "B"])
    assert cc["dangling"] == ["X"]
    assert cc["uncited_evidence"] == ["B"]


EV = ["成都市耕地面积（万亩）历年数据：2020年 486.47万亩；2023年 499.60万亩。"
      "派生量：累计增加13.13万亩、变化率+2.70%、年均+4.38万亩。"]


def test_number_check_grounded_numbers_pass():
    text = "2020年为486.47万亩 [FARMLAND_AREA]，2023年达499.60万亩，累计增加13.13万亩（+2.70%）。"
    assert number_check(text, EV) == []


def test_number_check_catches_fabricated():
    bad = number_check("全省总量为10020万亩 [FARMLAND_AREA]。", EV)
    assert [t for t, _ in bad] == ["10020"]


def test_number_check_catches_rounding():
    bad = number_check("约486.5万亩。", EV)  # 486.47 被四舍五入 → 必须抓
    assert [t for t, _ in bad] == ["486.5"]


def test_number_check_float_equal_tolerated():
    assert number_check("年均4.380万亩。", EV) == []  # 4.380 == 4.38 数值相等


def test_number_check_skips_short_enums_and_cite_ids():
    # "21 个市州"（两位枚举整数）与引用 id 里的数字（SLOPE_15_25 之类）不应误报
    assert number_check("覆盖21个市州 [SLOPE_15_25_AREA]，3类齐全。", EV) == []


def test_number_check_unit_aware_short_int():
    # 短整数 + 量纲单位（面积/比例）= 载荷数字，不论位数都核
    assert [t for t, _ in number_check("净增加21万亩。", EV)] == ["21"]
    assert [t for t, _ in number_check("水田占55%。", EV)] == ["55"]


def test_number_check_catches_out_of_scope_year():
    bad = number_check("自三调（2019年）以来持续增加。", EV)  # 证据只有 2020-2023
    assert [t for t, _ in bad] == ["2019"]
