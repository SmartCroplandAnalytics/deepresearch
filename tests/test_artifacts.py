"""确定性图表件：md_table / 编号占位替换 / 折线图落盘（matplotlib 可选）。"""

import pytest

from agentic_studio.infra.writing.artifacts import (
    FIG_TOKEN,
    TAB_TOKEN,
    md_table,
    number_artifacts,
)


def test_md_table_shape():
    md = md_table(["年份", "面积"], [["2020", "486.47"], ["2023", "499.60"]])
    lines = md.splitlines()
    assert lines[0] == "| 年份 | 面积 |"
    assert lines[1] == "| --- | --- |"
    assert lines[3] == "| 2023 | 499.60 |"


def test_number_artifacts_sequence_mixed():
    t = f"a {FIG_TOKEN} b {TAB_TOKEN} c {FIG_TOKEN} d"
    assert number_artifacts(t) == "a 图1 b 表1 c 图2 d"


def test_number_artifacts_noop_without_tokens():
    assert number_artifacts("正文 [A] 不变") == "正文 [A] 不变"


def test_tokens_invisible_to_cite_regex():
    # 占位必须避开 [id] 引用正则，否则会被装配重编号吃掉
    from agentic_studio.infra.writing.compose import _CITE

    assert _CITE.findall(f"{FIG_TOKEN}{TAB_TOKEN}") == []


def test_save_line_chart_writes_png(tmp_path):
    pytest.importorskip("matplotlib")
    from agentic_studio.infra.writing.artifacts import save_line_chart

    p = tmp_path / "figs" / "t.png"
    save_line_chart(p, [("成都市", [(2020, 486.47), (2023, 499.60)])],
                    ylabel="万亩", title="耕地面积历年变化")
    assert p.is_file() and p.stat().st_size > 1000


def test_save_bar_chart_writes_png(tmp_path):
    pytest.importorskip("matplotlib")
    from agentic_studio.infra.writing.artifacts import save_bar_chart

    p = tmp_path / "figs" / "b.png"
    save_bar_chart(p, ["成都市", "绵阳市"], [499.60, 401.10], xlabel="耕地面积（万亩）",
                   title="各市对比")
    assert p.is_file() and p.stat().st_size > 1000
