"""确定性图/表渲染（能力级、领域无关）——**图表不经 LLM**。

表 = markdown 直出；图 = matplotlib 落 PNG 进 workspace `figures/`。数据由数据源 renderer
（如 metric_postgres 的 series/by_region）直接查得 → 图表数字**构造即有据**，模型只在行文里
用「下图/下表」衔接，不画图、不填表、不复述。

编号：渲染时打占位 token `[[图]]`/`[[表]]`（CJK，避开引用正则 `[0-9A-Za-z_]`，不会被
assemble 的 [id]→[N] 重编号误吃），装配时 `number_artifacts` 按全文出现顺序替换为 图1/表1…。

matplotlib+seaborn 是可选依赖（extra: `viz`）：未装时表照常、图在 plugin lint 期被明确拒绝。
绘图用 OO API（Figure 直构，无 pyplot 全局态）——节级并行下线程安全；seaborn 只做主题/配色
（rcParams 级，进程内设一次），不走它的 pyplot 绘图函数。
"""

from __future__ import annotations

from pathlib import Path

FIG_TOKEN = "[[图]]"
TAB_TOKEN = "[[表]]"

_FONTS = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "PingFang SC", "DejaVu Sans"]
_styled = False


def has_matplotlib() -> bool:
    try:
        import matplotlib  # noqa: F401

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


def _apply_style() -> None:
    """进程内一次：seaborn 主题（whitegrid）+ 中文字体（须在 set_theme 之后盖回）。"""
    global _styled
    if _styled:
        return
    import matplotlib

    try:
        import seaborn as sns

        sns.set_theme(style="whitegrid", context="notebook")
    except ImportError:
        pass
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = _FONTS
    matplotlib.rcParams["axes.unicode_minus"] = False
    _styled = True


def _palette(n: int, name: str = "deep") -> list | None:
    try:
        import seaborn as sns

        return sns.color_palette(name, n)
    except ImportError:
        return None


def _new_figure(figsize: tuple[float, float]):
    _apply_style()
    from matplotlib.figure import Figure

    return Figure(figsize=figsize, dpi=150)


def _finish(fig, ax, path: str | Path, *, title: str) -> None:
    if title:
        ax.set_title(title, fontsize=12, fontweight="semibold", pad=10)
    ax.tick_params(labelsize=8.5)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p, bbox_inches="tight", facecolor="white")


def save_line_chart(
    path: str | Path,
    series: list[tuple[str, list[tuple[int, float]]]],
    *,
    ylabel: str = "",
    title: str = "",
) -> None:
    """折线图（时序）。series = [(label, [(x, y), …]), …]；≤3 条线时末点标值。"""
    fig = _new_figure((7.6, 4.0))
    ax = fig.subplots()
    colors = _palette(max(3, len(series)))
    xs_all: set[int] = set()
    for i, (label, pts) in enumerate(series):
        xs = [x for x, _ in pts]
        ys = [v for _, v in pts]
        ax.plot(xs, ys, marker="o", markersize=4.5, linewidth=2.2, label=label,
                color=colors[i] if colors else None,
                markeredgecolor="white", markeredgewidth=0.8)
        if len(series) <= 3 and pts:
            ax.annotate(f"{ys[-1]:.2f}", (xs[-1], ys[-1]), textcoords="offset points",
                        xytext=(6, 5), fontsize=8,
                        color=colors[i] if colors else "#333333")
        xs_all.update(xs)
    ax.set_xticks(sorted(xs_all))
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9.5)
    if len(series) > 1:
        ax.legend(fontsize=8.5, frameon=False)
    ax.margins(x=0.06)
    _finish(fig, ax, path, title=title)


def save_bar_chart(
    path: str | Path,
    labels: list[str],
    values: list[float],
    *,
    xlabel: str = "",
    title: str = "",
) -> None:
    """横向条形图（分区对比，最大值在上、渐变配色、条端标数值）。"""
    fig = _new_figure((7.6, max(2.6, 0.32 * len(labels) + 1.3)))
    ax = fig.subplots()
    ys = list(range(len(labels)))[::-1]
    colors = _palette(len(labels), "crest_r") or ["#4C78A8"] * len(labels)
    ax.barh(ys, values, height=0.66, color=colors, edgecolor="white", linewidth=0.4)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=8.5)
    for y, v in zip(ys, values, strict=True):
        ax.text(v, y, f" {v:.2f}", va="center", fontsize=7.5, color="#333333")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=9.5)
    ax.margins(x=0.12)
    ax.grid(axis="y", visible=False)
    _finish(fig, ax, path, title=title)
