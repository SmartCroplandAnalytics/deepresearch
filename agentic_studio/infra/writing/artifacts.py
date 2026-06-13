"""确定性图/表渲染（能力级、领域无关）——**图表不经 LLM**。

表 = markdown 直出；图 = **Plotly figure JSON** 落进 workspace `figures/*.plotly.json`。数据由
数据源 renderer（如 metric_postgres 的 series/by_region）直接查得 → 图表数字**构造即有据**，
模型只在行文里用「下图/下表」衔接，不画图、不填表、不复述。

图为何用 Plotly JSON 而非 PNG：前端用 plotly.js **交互式**渲染（缩放/悬停/图例），PNG 由
图上工具栏（或导出按钮）**客户端**导出——服务端只产确定性的图谱规格（data+layout），不依赖
任何渲染后端（无 kaleido/matplotlib）。markdown 里仍用 `![标题](figures/x.plotly.json)` 引用，
前端按扩展名识别为交互图。中文字体走浏览器，无需服务端字体配置。

编号：渲染时打占位 token `[[图]]`/`[[表]]`（CJK，避开引用正则 `[0-9A-Za-z_]`，不会被
assemble 的 [id]→[N] 重编号误吃），装配时 `number_artifacts` 按全文出现顺序替换为 图1/表1…。

plotly 是可选依赖（extra: `viz`）：未装时表照常、图在 plugin lint 期被明确拒绝。
"""

from __future__ import annotations

import json
from pathlib import Path

FIG_TOKEN = "[[图]]"
TAB_TOKEN = "[[表]]"

# 浏览器端字体级联（plotly.js 用浏览器字体渲染 CJK）。
_FONT_FAMILY = "Microsoft YaHei, SimHei, Noto Sans CJK SC, PingFang SC, sans-serif"
# 配色（plotly 离散色板，足够多条线/柱）。
_COLORS = [
    "#2E86AB", "#E1812C", "#3A923A", "#C03D3E", "#8463A8",
    "#946B55", "#D684BD", "#7F7F7F", "#BCBD45", "#39ACC9",
]


def has_plotly() -> bool:
    try:
        import plotly  # noqa: F401

        return True
    except ImportError:
        return False


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    """markdown 表（值已格式化为字符串）。"""
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(" --- " for _ in headers) + "|"
    body = ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join([head, sep, *body])


def number_artifacts(text: str) -> str:
    """把 [[图]]/[[表]] 占位按全文出现顺序替换为 图1…/表1…（装配时一次成型）。"""
    fig = tab = 0
    out: list[str] = []
    i = 0
    while True:
        pf = text.find(FIG_TOKEN, i)
        pt = text.find(TAB_TOKEN, i)
        if pf < 0 and pt < 0:
            out.append(text[i:])
            return "".join(out)
        if pt < 0 or (0 <= pf < pt):
            fig += 1
            out.append(text[i:pf])
            out.append(f"图{fig}")
            i = pf + len(FIG_TOKEN)
        else:
            tab += 1
            out.append(text[i:pt])
            out.append(f"表{tab}")
            i = pt + len(TAB_TOKEN)


def _base_layout(title: str) -> dict:
    """统一版式：白底、中文字体级联、紧凑边距、悬停统一。"""
    return {
        "title": {"text": title, "x": 0.02, "xanchor": "left",
                  "font": {"size": 16}},
        "template": "plotly_white",
        "font": {"family": _FONT_FAMILY, "size": 12, "color": "#333333"},
        "margin": {"l": 60, "r": 24, "t": 48, "b": 48},
        "hovermode": "x unified",
        "autosize": True,
    }


def _write_fig(path: str | Path, fig: dict) -> None:
    """落 Plotly figure JSON（{data, layout}）到 figures/*.plotly.json。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(fig, ensure_ascii=False), encoding="utf-8")


def save_line_chart(
    path: str | Path,
    series: list[tuple[str, list[tuple[int, float]]]],
    *,
    ylabel: str = "",
    title: str = "",
) -> None:
    """折线图（时序）。series = [(label, [(x, y), …]), …] → Plotly figure JSON。"""
    data = []
    xs_all: set[int] = set()
    for i, (label, pts) in enumerate(series):
        xs = [x for x, _ in pts]
        ys = [v for _, v in pts]
        xs_all.update(xs)
        data.append({
            "type": "scatter",
            "mode": "lines+markers" + ("+text" if len(series) <= 3 else ""),
            "name": label,
            "x": xs,
            "y": ys,
            "line": {"color": _COLORS[i % len(_COLORS)], "width": 2.4},
            "marker": {"size": 7, "color": _COLORS[i % len(_COLORS)]},
            "text": [f"{v:.2f}" for v in ys] if len(series) <= 3 else None,
            "textposition": "top center",
            "textfont": {"size": 10},
            "hovertemplate": f"{label}: %{{y:.2f}}<extra></extra>",
        })
    layout = _base_layout(title)
    layout["xaxis"] = {"tickmode": "array", "tickvals": sorted(xs_all),
                       "dtick": 1}
    if ylabel:
        layout["yaxis"] = {"title": {"text": ylabel}}
    layout["showlegend"] = len(series) > 1
    _write_fig(path, {"data": data, "layout": layout})


def save_bar_chart(
    path: str | Path,
    labels: list[str],
    values: list[float],
    *,
    xlabel: str = "",
    title: str = "",
) -> None:
    """横向条形图（分区对比，最大值在上、条端标数值）→ Plotly figure JSON。"""
    # plotly 横向条形：列表顺序自下而上，故反转使最大值（首项）在顶部。
    labels_r = list(labels)[::-1]
    values_r = list(values)[::-1]
    data = [{
        "type": "bar",
        "orientation": "h",
        "x": values_r,
        "y": labels_r,
        "marker": {"color": _COLORS[0]},
        "text": [f"{v:.2f}" for v in values_r],
        "textposition": "outside",
        "texttemplate": "%{text}",
        "hovertemplate": "%{y}: %{x:.2f}<extra></extra>",
    }]
    layout = _base_layout(title)
    layout["margin"]["l"] = 110  # 地区名较长，留宽左边距
    layout["height"] = max(260, 30 * len(labels) + 120)
    if xlabel:
        layout["xaxis"] = {"title": {"text": xlabel}}
    _write_fig(path, {"data": data, "layout": layout})
