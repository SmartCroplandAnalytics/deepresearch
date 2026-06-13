"""确定性图表件：md_table / 编号占位替换 / 折线图落盘（Plotly figure JSON，可选）。"""

import json

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


def test_save_line_chart_writes_plotly_json(tmp_path):
    from agentic_studio.infra.writing.artifacts import save_line_chart

    p = tmp_path / "figs" / "t.plotly.json"
    save_line_chart(p, [("成都市", [(2020, 486.47), (2023, 499.60)])],
                    ylabel="万亩", title="耕地面积历年变化")
    assert p.is_file()
    fig = json.loads(p.read_text(encoding="utf-8"))
    assert fig["data"] and fig["data"][0]["type"] == "scatter"
    assert fig["data"][0]["y"] == [486.47, 499.60]
    assert "耕地面积历年变化" in fig["layout"]["title"]["text"]


def test_save_bar_chart_writes_plotly_json(tmp_path):
    from agentic_studio.infra.writing.artifacts import save_bar_chart

    p = tmp_path / "figs" / "b.plotly.json"
    save_bar_chart(p, ["成都市", "绵阳市"], [499.60, 401.10], xlabel="耕地面积（万亩）",
                   title="各市对比")
    assert p.is_file()
    fig = json.loads(p.read_text(encoding="utf-8"))
    assert fig["data"][0]["type"] == "bar" and fig["data"][0]["orientation"] == "h"
    # 反转后最大值（成都市）应在末位（plotly 横向条形列表自下而上 → 顶部）
    assert fig["data"][0]["y"][-1] == "成都市"
