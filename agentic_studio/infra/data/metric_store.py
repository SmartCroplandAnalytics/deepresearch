"""MetricStore —— 指标数据库的**安全中介取数层**（架构「DB 双通道」之安全版）。

设计原则：**agent 永不写 SQL、永不直连库**。只暴露一组**具名、只读、参数化**的取数原语：

- **只读**：连接即 `SET default_transaction_read_only = on` + `statement_timeout`，服务端拒写/拒慢。
- **白名单**：indicator_code 必须在 meta 表加载的集合内、region 必须在地区维表内，否则拒绝。
- **无字符串拼接**：表/视图名来自 **plugin 的 datasource.yaml**（人写的可信配置，且经标识符
  白名单正则校验），值一律走参数占位符；agent 输入永远只是"值"。
- **产物是证据**：`as_evidence()` 渲染成与语料证据同构的 `{id,title,text,importance,source}`。

**领域无关**：库结构（视图/meta 表/地区表/默认地区/来源名）全部由 `MetricSourceConfig`
注入（来自 plugin），本文件不含任何具体领域字面量。依赖 psycopg（sync）；DSN 由调用方传入。

**线程模型**：psycopg3 连接 threadsafety=2（自带内部锁）——多线程共享一条连接是安全的，
但命令会串行化；run_brief 的节级并行在 DB 侧退化为串行（可接受：瓶颈在 LLM 调用）。
连接断开时 `_q` 自动重连一次再重试（长会话/库重启的韧性）。
"""

from __future__ import annotations

import re
import threading
import zlib
from dataclasses import dataclass
from typing import Any

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ident(name: str) -> str:
    """SQL 标识符白名单校验（配置可信但仍设防线；值参数不经此路径）。"""
    if not _IDENT.match(name or ""):
        raise ValueError(f"非法 SQL 标识符（datasource 配置错误）：{name!r}")
    return name


def _slug(s: str) -> str:
    """稳定短哈希（crc32）。Python hash() 对 str 每进程随机化，不可用于持久 id。"""
    return f"{zlib.crc32(s.encode('utf-8')):x}"


@dataclass(frozen=True)
class MetricSourceConfig:
    """一个指标库的绑定声明（来自 plugin 的 datasource.yaml）。"""

    raw_view: str = "vw_region_time_indicator_raw"
    derived_view: str = "vw_region_time_indicator_derived"
    raw_meta: str = "raw_indicator_meta"
    derived_meta: str = "derived_indicator_meta"
    region_table: str = "region"
    time_table: str = "time_dimension"
    default_region: str = ""
    source_name: str = "metric_db"
    dsn_env: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> MetricSourceConfig:
        views = d.get("views") or {}
        meta = d.get("meta_tables") or {}
        return cls(
            raw_view=views.get("raw", cls.raw_view),
            derived_view=views.get("derived", cls.derived_view),
            raw_meta=meta.get("raw", cls.raw_meta),
            derived_meta=meta.get("derived", cls.derived_meta),
            region_table=d.get("region_table", cls.region_table),
            time_table=d.get("time_table", cls.time_table),
            default_region=d.get("default_region", ""),
            source_name=d.get("source_name", cls.source_name),
            dsn_env=d.get("dsn_env", ""),
        )

    def __post_init__(self) -> None:
        for f in (self.raw_view, self.derived_view, self.raw_meta, self.derived_meta,
                  self.region_table, self.time_table):
            _ident(f)


def _summarize(s: MetricSeries) -> str:
    """确定性派生摘要：期初/期末/累计变化/变化率/年均——放进证据，免模型自算（防算术错）。"""
    if len(s.points) < 2:
        return ""
    (y0, v0), (yn, vn) = s.points[0], s.points[-1]
    delta = vn - v0
    span = yn - y0
    word = "增加" if delta > 0 else ("减少" if delta < 0 else "持平")
    parts = [
        f"期初{y0}年{v0:.2f}{s.unit}、期末{yn}年{vn:.2f}{s.unit}",
        f"累计{word}{abs(delta):.2f}{s.unit}",
    ]
    if v0:
        parts.append(f"变化率{delta / v0 * 100:+.2f}%")
    if span:
        parts.append(f"年均{delta / span:+.2f}{s.unit}")
    return "派生量（确定性计算，可直接引用）：" + "、".join(parts) + "。"


@dataclass
class MetricSeries:
    """一个 (指标 × 地区) 的历年时序。"""

    code: str
    name: str
    unit: str
    region: str
    points: list[tuple[int, float]]  # [(year, value)] 按年升序

    def value_at(self, year: int) -> float | None:
        for y, v in self.points:
            if y == year:
                return v
        return None


class MetricStore:
    """安全取数层：连接一个指标库，暴露具名只读查询 + 证据渲染。"""

    def __init__(
        self,
        dsn: str,
        *,
        config: MetricSourceConfig | None = None,
        statement_timeout_ms: int = 5000,
    ) -> None:
        self.cfg = config or MetricSourceConfig()
        self._dsn = dsn
        self._timeout_ms = int(statement_timeout_ms)
        self._reconnect_lock = threading.Lock()
        self._conn = self._connect()
        # 白名单：指标 code→(name,unit,kind)；地区集合。启动时一次性加载。
        self._meta: dict[str, tuple[str, str, str]] = {}
        self._regions: set[str] = set()
        self._load_allowlist()

    # ───────────────────────── 内部：连接 / 白名单加载 ─────────────────────────
    def _connect(self) -> Any:
        import psycopg

        conn = psycopg.connect(self._dsn, connect_timeout=5, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute(f"SET statement_timeout = {self._timeout_ms}")
        return conn

    def _q(self, sql: str, params: tuple = ()) -> list[tuple]:
        import psycopg

        try:
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        except psycopg.OperationalError:
            # 连接断开（空闲超时/库重启）→ 重连一次再试；只读会话级设置随 _connect 重建。
            # 互斥：并行节下多线程同时掉线时只重连一次，其余线程复用新连接。
            with self._reconnect_lock:
                if self._conn.closed or self._conn.broken:
                    try:
                        self._conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self._conn = self._connect()
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()

    def _load_allowlist(self) -> None:
        for code, name, unit in self._q(f"select code,name,unit from {self.cfg.raw_meta}"):
            self._meta[code] = (name, unit, "raw")
        for code, name, unit in self._q(f"select code,name,unit from {self.cfg.derived_meta}"):
            self._meta[code] = (name, unit, "derived")
        self._regions = {r[0] for r in self._q(f"select name from {self.cfg.region_table}")}

    def _check(self, code: str, region: str) -> str:
        if code not in self._meta:
            raise ValueError(f"未知指标 code：{code}（不在白名单 meta 表）")
        if region not in self._regions:
            raise ValueError(f"未知地区：{region}（不在地区维表）")
        return self.cfg.derived_view if self._meta[code][2] == "derived" else self.cfg.raw_view

    def _default_region(self, region: str | None) -> str:
        r = region or self.cfg.default_region
        if not r:
            raise ValueError("未指定地区，且 datasource 未声明 default_region")
        return r

    # ───────────────────────── 具名只读查询 ─────────────────────────
    def indicators(self) -> dict[str, tuple[str, str, str]]:
        """全部可用指标 code→(name,unit,kind)。"""
        return dict(self._meta)

    def known_regions(self) -> set[str]:
        """地区维表全集（scope 校验用）。"""
        return set(self._regions)

    def years(self) -> list[int]:
        rows = self._q(f"select distinct year from {self.cfg.time_table} order by year")
        return [int(r[0]) for r in rows if r[0] is not None]

    def series(
        self, code: str, region: str | None = None, *, years: tuple[int, int] | None = None
    ) -> MetricSeries:
        """某指标在某地区的历年时序（具名查询，参数化、只读）。years=(lo,hi) 限定年份区间。"""
        region = self._default_region(region)
        view = self._check(code, region)
        sql = (
            f"select year, value from {view} "
            "where indicator_code = %s and region_name = %s and year is not null"
        )
        params: tuple = (code, region)
        if years:
            sql += " and year between %s and %s"
            params += (int(years[0]), int(years[1]))
        rows = self._q(sql + " order by year", params)
        name, unit, _ = self._meta[code]
        pts = [(int(y), float(v)) for y, v in rows if v is not None]
        return MetricSeries(code=code, name=name, unit=unit, region=region, points=pts)

    def available_regions(self) -> dict[str, list[str]]:
        """实际**有指标数据**的地区，按层级分组（诚实回答"有没有这个粒度"）。"""
        rows = self._q(
            "select r.level, v.region_name from "
            f"(select distinct region_name from {self.cfg.raw_view}) v "
            f"join {self.cfg.region_table} r on r.name = v.region_name "
            "order by r.level, v.region_name"
        )
        out: dict[str, list[str]] = {}
        for level, name in rows:
            out.setdefault(level, []).append(name)
        return out

    def availability_text(self) -> str:
        """动态生成的数据覆盖说明（含维表里**存在但无数据**的层级，不靠硬编码）。"""
        av = self.available_regions()
        levels = [r[0] for r in self._q(
            f"select distinct level from {self.cfg.region_table} order by level"
        ) if r[0]]
        lines = ["数据实际覆盖（按行政/分组层级）："]
        for lv in levels or sorted(av):
            rs = av.get(lv, [])
            if rs:
                lines.append(f"- {lv}：{len(rs)} 个 —— {'、'.join(rs)}")
            else:
                lines.append(f"- {lv}：**无数据**（维表有该层级、指标值未覆盖）")
        yrs = self.years()
        if yrs:
            lines.append(f"年份：{min(yrs)}—{max(yrs)}（{'、'.join(map(str, yrs))}）")
        return "\n".join(lines)

    def has_data(self, region: str) -> bool:
        """该地区是否有指标数据（无 → 诚实返回 False）。"""
        return bool(self._q(
            f"select 1 from {self.cfg.raw_view} where region_name = %s limit 1", (region,)
        ))

    def by_region(
        self, code: str, year: int, *, parent: str | None = None
    ) -> list[tuple[str, float]]:
        """某指标某年在 parent 下各子地区的值，按值降序。"""
        parent = self._default_region(parent)
        view = self._check(code, parent)
        rows = self._q(
            f"select v.region_name, v.value from {view} v "
            f"join {self.cfg.region_table} r on r.name = v.region_name "
            f"join {self.cfg.region_table} p on p.id = r.parent_id "
            "where v.indicator_code = %s and v.year = %s and p.name = %s and v.value is not null "
            "order by v.value desc",
            (code, int(year), parent),
        )
        return [(rn, float(val)) for rn, val in rows]

    # ───────────────────────── 证据渲染（喂 grounded-write）─────────────────────────
    def as_evidence(
        self, code: str, region: str | None = None, *, years: tuple[int, int] | None = None
    ) -> dict[str, Any] | None:
        """把历年时序渲染成一条证据记录（{id,title,text,importance,source}）。

        DB 为权威源 → importance=very_high。证据 id 须为 [0-9A-Za-z_]（与 compose 引用正则
        一致）且**跨进程稳定**：默认地区用裸 code，其它地区附 crc32 短哈希后缀。
        """
        s = self.series(code, region, years=years)
        if not s.points:
            return None
        body = "；".join(f"{y}年 {v:.2f}{s.unit}" for y, v in s.points)
        rsuffix = "" if s.region == self.cfg.default_region else f"_{_slug(s.region)}"
        nid = f"{code}{rsuffix}"
        text = (
            f"{s.region}{s.name}（{s.unit}）历年数据：{body}。{_summarize(s)}"
            f"来源：{self.cfg.source_name} 指标 {code}。"
        )
        return {
            "id": nid,
            "title": f"{s.region}{s.name}历年",
            "text": text,
            "importance": "very_high",
            "source": f"{self.cfg.source_name}:{code}",
        }

    def region_evidence(
        self, code: str, year: int, *, parent: str | None = None, top: int = 30
    ) -> dict[str, Any] | None:
        """把某年 parent 下各子地区的值渲染成一条证据记录（分区对比用）。"""
        parent = self._default_region(parent)
        rows = self.by_region(code, year, parent=parent)[:top]
        if not rows:
            return None
        name, unit, _ = self._meta[code]
        body = "；".join(f"{rn} {v:.2f}{unit}" for rn, v in rows)
        psuffix = "" if parent == self.cfg.default_region else f"_{_slug(parent)}"
        nid = f"{code}_R{year}{psuffix}"
        text = (
            f"{year}年{parent}下各地区{name}（{unit}）：{body}。"
            f"来源：{self.cfg.source_name} 指标 {code}。"
        )
        return {
            "id": nid,
            "title": f"{year}年{parent}分区{name}",
            "text": text,
            "importance": "very_high",
            "source": f"{self.cfg.source_name}:{code}",
        }

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass
