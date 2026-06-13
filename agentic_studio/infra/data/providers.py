"""EvidenceProvider —— 证据源抽象（能力与数据源之间的缝）。

plugin 的 outline.yaml 里每节声明证据规格 `{kind: ..., ...args}`；能力层（grounded_brief）
只做 scope 绑定/展开，然后按 kind 派发给 provider 取证据——能力层不知道任何具体数据源。

provider 由 plugin 的 **datasource.yaml** 声明并在此组装（`build_provider_set`）。当前实现
`kind: metric_postgres`（经 MetricStore 安全中介，agent 不写 SQL）；新增数据源 = 新增一个
provider 实现 + 在 `_BUILDERS` 注册，plugin 侧只改 yaml。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from agentic_studio.infra.data.metric_store import MetricSourceConfig, MetricStore


class EvidenceProvider(Protocol):
    """一种证据规格 kind 的取数器。gather 吃**已绑定 scope** 的规格，返回证据记录列表。"""

    kind: str
    fanout_keys: tuple[str, ...]  # 这些参数若为列表 → 能力层展开成多次调用（如多地区对比）

    def gather(self, spec: dict) -> list[dict]: ...

    def lint(self, spec: dict) -> str | None:
        """静态校验一条**未绑定**规格（$占位跳过）。返回问题描述或 None。"""
        ...


class ArtifactRenderer(Protocol):
    """一种图/表规格 kind 的**确定性渲染器**（数据直出，不经 LLM）。

    render 吃已绑定 scope 的规格，返回 (markdown块, 标题) 或 None（该 scope 下无数据）；
    markdown 里的编号用 artifacts.FIG_TOKEN/TAB_TOKEN 占位，装配时全文统一编号。
    列表值（多地区对比等）由 renderer 自行决定合并画/分别画——不走 fanout。
    """

    kind: str

    def render(self, spec: dict, *, ws: Path, sid: str, idx: int) -> tuple[str, str] | None: ...

    def lint(self, spec: dict) -> str | None: ...


@dataclass
class ProviderSet:
    """一个 plugin 的全部证据 provider + 图表 renderer + 配套件（校验器/可用性/生命周期）。"""

    providers: dict[str, EvidenceProvider] = field(default_factory=dict)
    renderers: dict[str, ArtifactRenderer] = field(default_factory=dict)
    # scope 参数 check 名 → 校验器（返回错误消息或 None）
    validators: dict[str, Callable[[Any], str | None]] = field(default_factory=dict)
    availability: Callable[[], str] = lambda: "（本 plugin 未声明数据源）"
    close: Callable[[], None] = lambda: None


def _years_of(v: Any) -> tuple[int, int] | None:
    if not v:
        return None
    lo, hi = int(v[0]), int(v[1])
    return (min(lo, hi), max(lo, hi))


@dataclass
class MetricSeriesProvider:
    """kind=series：某指标在某地区的历年时序 → 一条证据。region 可随 scope 列表展开。"""

    store: MetricStore
    kind: str = "series"
    fanout_keys: tuple[str, ...] = ("region",)

    def gather(self, spec: dict) -> list[dict]:
        e = self.store.as_evidence(
            spec["code"], spec.get("region"), years=_years_of(spec.get("years"))
        )
        return [e] if e else []

    def lint(self, spec: dict) -> str | None:
        code = spec.get("code")
        if not code:
            return "series 规格缺 code"
        if code not in self.store.indicators():
            return f"指标 code 不在白名单：{code}"
        return None


@dataclass
class MetricByRegionProvider:
    """kind=by_region：某指标某年在 parent 下各子地区 → 一条对比证据。

    spec.year 是 plugin 声明的对比年；若 scope 绑了 years 区间则夹到区间内
    （年份语义在 provider，不在能力层）。
    """

    store: MetricStore
    kind: str = "by_region"
    fanout_keys: tuple[str, ...] = ("parent",)

    def gather(self, spec: dict) -> list[dict]:
        year = int(spec["year"])
        yrs = _years_of(spec.get("years"))
        if yrs:
            year = max(yrs[0], min(yrs[1], year))
        e = self.store.region_evidence(
            spec["code"], year, parent=spec.get("parent"), top=int(spec.get("top", 30))
        )
        return [e] if e else []

    def lint(self, spec: dict) -> str | None:
        code = spec.get("code")
        if not code:
            return "by_region 规格缺 code"
        if code not in self.store.indicators():
            return f"指标 code 不在白名单：{code}"
        y = spec.get("year")
        if y is None:
            return "by_region 规格缺 year"
        if not (isinstance(y, int) or (isinstance(y, str) and y.startswith("$"))):
            return f"by_region year 须为整数或 $scope 引用：{y!r}"
        return None


# ───────────────────── metric 图表 renderer（确定性，数据直出）─────────────────────


def _norm_list(v: Any) -> list:
    if v is None:
        return [None]
    return [v] if isinstance(v, str) else list(v)


def _codes_of(spec: dict) -> list[str]:
    return list(spec.get("codes") or ([spec["code"]] if spec.get("code") else []))


def _lint_codes(store: MetricStore, spec: dict, kind: str) -> str | None:
    codes = _codes_of(spec)
    if not codes:
        return f"{kind} 规格缺 code/codes"
    for c in codes:
        if isinstance(c, str) and not c.startswith("$") and c not in store.indicators():
            return f"指标 code 不在白名单：{c}"
    return None


def _fig_name(sid: str, idx: int, sub: int = -1) -> str:
    base = f"figures/s{sid.replace('.', '_')}-{idx}"
    # 交互图谱（Plotly figure JSON）；前端按 .plotly.json 扩展名识别并交互式渲染。
    return f"{base}-{sub}.plotly.json" if sub >= 0 else f"{base}.plotly.json"


@dataclass
class SeriesTableRenderer:
    """kind=series_table：若干指标 ×（可多）地区的历年值 → markdown 表（行=年份）。"""

    store: MetricStore
    kind: str = "series_table"

    def render(self, spec: dict, *, ws: Path, sid: str, idx: int) -> tuple[str, str] | None:
        from agentic_studio.infra.writing.artifacts import TAB_TOKEN, md_table

        regions = _norm_list(spec.get("region"))
        years = _years_of(spec.get("years"))
        cols: list[tuple[str, dict[int, float]]] = []
        for r in regions:
            for c in _codes_of(spec):
                s = self.store.series(c, r, years=years)
                if not s.points:
                    continue
                head = (f"{s.name}（{s.unit}）" if len(regions) == 1
                        else f"{s.region}{s.name}（{s.unit}）")
                cols.append((head, dict(s.points)))
        if not cols:
            return None
        all_years = sorted({y for _, pts in cols for y in pts})
        headers = ["年份"] + [h for h, _ in cols]
        rows = [[str(y)] + [f"{pts[y]:.2f}" if y in pts else "—" for _, pts in cols]
                for y in all_years]
        caption = spec.get("caption") or "历年指标数据"
        return f"**{TAB_TOKEN}：{caption}**\n\n" + md_table(headers, rows), caption

    def lint(self, spec: dict) -> str | None:
        return _lint_codes(self.store, spec, self.kind)


@dataclass
class ByRegionTableRenderer:
    """kind=by_region_table：parent 下各子地区在期初/期末两年的值与变化量 → markdown 表。

    年界取该指标在 parent 的实际数据范围（受 spec.years 限定）；变化量为确定性计算。
    """

    store: MetricStore
    kind: str = "by_region_table"

    def render(self, spec: dict, *, ws: Path, sid: str, idx: int) -> tuple[str, str] | None:
        from agentic_studio.infra.writing.artifacts import TAB_TOKEN, md_table

        code = spec["code"]
        parents = _norm_list(spec.get("parent"))
        top = int(spec.get("top", 30))
        blocks: list[str] = []
        caps: list[str] = []
        for p in parents:
            s = self.store.series(code, p, years=_years_of(spec.get("years")))
            if len(s.points) < 1:
                continue
            y0, y1 = s.points[0][0], s.points[-1][0]
            m0 = dict(self.store.by_region(code, y0, parent=p))
            m1 = dict(self.store.by_region(code, y1, parent=p))
            regs = sorted(set(m0) | set(m1),
                          key=lambda r: -(m1.get(r) if m1.get(r) is not None else m0.get(r, 0.0)))
            regs = regs[:top]
            if not regs:
                continue
            name, unit, _k = self.store.indicators()[code]
            headers = ["地区", f"{y0}年（{unit}）", f"{y1}年（{unit}）", "变化量"]
            rows = []
            for r in regs:
                v0, v1 = m0.get(r), m1.get(r)
                rows.append([
                    r,
                    f"{v0:.2f}" if v0 is not None else "—",
                    f"{v1:.2f}" if v1 is not None else "—",
                    f"{v1 - v0:+.2f}" if v0 is not None and v1 is not None else "—",
                ])
            cap = spec.get("caption") or f"{s.region}各地区{name}"
            cap = f"{cap}（{y0}—{y1}）" if "（" not in cap else cap
            if len(parents) > 1:
                cap = f"{s.region}·{cap}"
            blocks.append(f"**{TAB_TOKEN}：{cap}**\n\n" + md_table(headers, rows))
            caps.append(cap)
        if not blocks:
            return None
        return "\n\n".join(blocks), "；".join(caps)

    def lint(self, spec: dict) -> str | None:
        return _lint_codes(self.store, spec, self.kind)


def _chart_lint(store: MetricStore, spec: dict, kind: str) -> str | None:
    from agentic_studio.infra.writing.artifacts import has_plotly

    if not has_plotly():
        return f"声明了图（{kind}）但未安装 plotly（安装 viz extra：uv …  --extra viz）"
    return _lint_codes(store, spec, kind)


@dataclass
class LineChartRenderer:
    """kind=line_chart：若干指标 ×（可多）地区的时序折线 → PNG（多地区=多线对比）。"""

    store: MetricStore
    kind: str = "line_chart"

    def render(self, spec: dict, *, ws: Path, sid: str, idx: int) -> tuple[str, str] | None:
        from agentic_studio.infra.writing import artifacts as art

        regions = _norm_list(spec.get("region"))
        codes = _codes_of(spec)
        years = _years_of(spec.get("years"))
        series: list[tuple[str, list[tuple[int, float]]]] = []
        units: set[str] = set()
        names: list[str] = []
        for r in regions:
            for c in codes:
                s = self.store.series(c, r, years=years)
                if not s.points:
                    continue
                if len(regions) > 1 and len(codes) > 1:
                    label = f"{s.region}·{s.name}"
                elif len(regions) > 1:
                    label = s.region
                else:
                    label = s.name
                series.append((label, s.points))
                units.add(s.unit)
                names.append(s.name)
        if not series:
            return None
        caption = spec.get("caption") or "、".join(dict.fromkeys(names)) + "历年变化"
        fname = _fig_name(str(sid), idx)
        art.save_line_chart(ws / fname, series,
                            ylabel=units.pop() if len(units) == 1 else "", title=caption)
        return f"![{caption}]({fname})\n\n*{art.FIG_TOKEN}：{caption}*", caption

    def lint(self, spec: dict) -> str | None:
        return _chart_lint(self.store, spec, self.kind)


@dataclass
class BarChartRenderer:
    """kind=bar_chart：某指标某年 parent 下各子地区横向条形对比 → PNG。

    year 缺省取数据末年；受 spec.years 夹取。parent 为列表时一地区一图。
    """

    store: MetricStore
    kind: str = "bar_chart"

    def render(self, spec: dict, *, ws: Path, sid: str, idx: int) -> tuple[str, str] | None:
        from agentic_studio.infra.writing import artifacts as art

        code = spec["code"]
        parents = _norm_list(spec.get("parent"))
        top = int(spec.get("top", 30))
        yrs = _years_of(spec.get("years"))
        blocks: list[str] = []
        caps: list[str] = []
        for j, p in enumerate(parents):
            year = int(spec.get("year") or 0)
            if yrs and year:
                year = max(yrs[0], min(yrs[1], year))
            if not year:
                s = self.store.series(code, p, years=yrs)
                if not s.points:
                    continue
                year = s.points[-1][0]
            rows = self.store.by_region(code, year, parent=p)[:top]
            if not rows:
                continue
            name, unit, _k = self.store.indicators()[code]
            parent_name = p or self.store.cfg.default_region
            cap = spec.get("caption") or f"{year}年{parent_name}各地区{name}"
            if len(parents) > 1 and spec.get("caption"):
                cap = f"{parent_name}·{cap}"
            fname = _fig_name(str(sid), idx, sub=j if len(parents) > 1 else -1)
            art.save_bar_chart(ws / fname, [r for r, _ in rows], [v for _, v in rows],
                               xlabel=f"{name}（{unit}）", title=cap)
            blocks.append(f"![{cap}]({fname})\n\n*{art.FIG_TOKEN}：{cap}*")
            caps.append(cap)
        if not blocks:
            return None
        return "\n\n".join(blocks), "；".join(caps)

    def lint(self, spec: dict) -> str | None:
        return _chart_lint(self.store, spec, self.kind)


def _build_metric_postgres(cfg: dict, plugin_dir: Path) -> ProviderSet:
    mc = MetricSourceConfig.from_dict(cfg)
    if not mc.dsn_env:
        raise ValueError(f"datasource.yaml（{plugin_dir.name}）缺 dsn_env：DSN 必须经环境变量注入")
    dsn = os.environ.get(mc.dsn_env, "")
    if not dsn:
        raise RuntimeError(
            f"环境变量 {mc.dsn_env} 未设置（plugin {plugin_dir.name} 的数据源 DSN）"
        )
    store = MetricStore(dsn, config=mc)

    def check_region(v: Any) -> str | None:
        r = str(v)
        if r not in store.known_regions():
            return "不在地区维表（名称写错？）"
        if not store.has_data(r):
            return "地区存在但**无指标数据**（数据未覆盖该层级；可调 availability 查看覆盖范围）"
        return None

    return ProviderSet(
        providers={
            "series": MetricSeriesProvider(store),
            "by_region": MetricByRegionProvider(store),
        },
        renderers={
            "series_table": SeriesTableRenderer(store),
            "by_region_table": ByRegionTableRenderer(store),
            "line_chart": LineChartRenderer(store),
            "bar_chart": BarChartRenderer(store),
        },
        validators={"region": check_region},
        availability=store.availability_text,
        close=store.close,
    )


_BUILDERS: dict[str, Callable[[dict, Path], ProviderSet]] = {
    "metric_postgres": _build_metric_postgres,
}


def build_provider_set(plugin_dir: str | Path) -> ProviderSet:
    """读 plugin 的 datasource.yaml → 组装 ProviderSet。无声明则返回空集（纯语料 plugin）。"""
    import yaml

    p = Path(plugin_dir)
    f = p / "datasource.yaml"
    if not f.is_file():
        return ProviderSet()
    cfg = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    kind = cfg.get("kind", "")
    if kind not in _BUILDERS:
        raise ValueError(
            f"未知 datasource kind：{kind!r}（{f}）。已支持：{', '.join(_BUILDERS)}"
        )
    return _BUILDERS[kind](cfg, p)
