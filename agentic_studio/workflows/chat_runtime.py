"""chat runtime —— 通用对话外壳的**工具层**（runtime/harness 是更高抽象，能力是可插的 /-workflow）。

三层关系（工程规范 §13）：
- **runtime**：会话 + 工作区 VFS + skill 挂载/拉起 + 能力工具注入。**不绑定任何领域/能力**——
  不挂能力时就是普通对话 agent。会话装配在 `session/build.py::build_chat_session`（分层：
  本文件只产工具；重框架装配归 session/infra 层）。
- **能力（capability）**：一组带前缀的工具（`gw_*`）+ 能力 SKILL.md（policy）。经
  `CAPABILITY_TOOLSETS` 注册，按 `capabilities=[...]` 列表注入会话。
  调用形态：`/<能力> @<plugin> <需求>`（约定写在薄 runtime 系统提示里）。
- **plugin（领域）**：挂在 skills 目录下的 skill-set；能力工具以 plugin 名为参数动态消费
  ——**会话不绑死单 plugin**，挂进 /skills 即可被拉起。

意图理解（自然语言→scope）发生在对话层、按 plugin SKILL.md 的维度说明做；
能力层只接 scope dict（grounded_brief.validate_scope 校验）。
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from agentic_studio import prompts
from agentic_studio.infra.llm import get_chat_model
from agentic_studio.workflows import grounded_brief as gb

# ───────────────────────── runtime 级工具（skill 挂载/拉起）─────────────────────────


def make_runtime_tools(skills_root: str) -> list:
    """list_skills / launch_skill：人把 skill 放进 skills 目录 = 挂载；agent 按需拉起。"""
    root = Path(skills_root)

    @tool
    def list_skills() -> str:
        """列出已挂载、可拉起的 skill（能力与领域 plugin；名称+简介）。"""
        rows = []
        for d in sorted(root.iterdir()):
            f = d / "SKILL.md"
            if not f.is_file():
                continue
            desc = kind = ""
            for ln in f.read_text(encoding="utf-8").splitlines():
                if ln.startswith("description:"):
                    desc = ln.split(":", 1)[1].strip()
                elif ln.startswith("kind:"):
                    kind = ln.split(":", 1)[1].strip()
            rows.append(f"- {d.name}（{kind or 'skill'}）：{desc}")
        return "已挂载 skill：\n" + "\n".join(rows)

    @tool
    def launch_skill(name: str) -> str:
        """拉起（加载）一个已挂载的 skill：返回其 SKILL.md 全文作为后续操作的指引。"""
        f = root / name / "SKILL.md"
        if not f.is_file():
            return f"无此 skill：{name}。可先调 list_skills 查看可用 skill。"
        return f"已拉起 skill「{name}」，按以下指引执行：\n\n{f.read_text(encoding='utf-8')}"

    return [list_skills, launch_skill]


# ───────────────────────── grounded-writing 能力工具集 ─────────────────────────


def make_grounded_write_tools(
    skills_root: str,
    workspace: str,
    model_spec: str,
    closers: list[Callable[[], None]],
    *,
    full_body: bool = True,
) -> list:
    """gw_* 工具：以 plugin 名为参数（会话不绑死单 plugin）。

    - plugin 元数据（yaml）与数据源（ProviderSet）**分开懒加载**：查 schema/列 plugin
      不要求 DSN 可连；首次取数才建连接，并把 close 登记进会话 closers。
    - 幂等以 brief_state.json 为准（plugin + 归一化 scope 相等 → 返回既有稿件，跨进程有效）。
    - generate/revise 经同一把 workspace 锁串行化（防同轮并发工具调用交错写产物）。
    - full_body=False（统一 workspace 外壳）：generate 返回摘要 + "先 read_file 再汇报"指引，
      不整篇回灌上下文；True（裸外壳，无文件工具）：返回全文（唯一 grounding 通道）。
    """
    root = Path(skills_root)
    meta_cache: dict[str, dict] = {}
    pset_cache: dict[str, Any] = {}
    _verifier: list[Any] = []
    wlock = threading.Lock()

    def _verifier_get() -> Any:
        if not _verifier:
            from agentic_studio.infra.research.verify import Verifier

            _verifier.append(Verifier(model_spec))
        return _verifier[0]

    def _meta(name: str) -> dict:
        """plugin 元数据（纯 yaml，不碰数据源）。"""
        if name in meta_cache:
            return meta_cache[name]
        d = root / name
        if not (d / "outline.yaml").is_file():
            avail = [p.parent.name for p in root.glob("*/outline.yaml")]
            raise ValueError(
                f"无此领域 plugin：{name}。可用：{', '.join(avail) or '（无）'}（gw_plugins 可查）"
            )
        meta_cache[name] = {"dir": str(d), "plugin": gb.load_plugin(d)}
        return meta_cache[name]

    def _pset(name: str) -> Any:
        """plugin 数据源（按需建连接、缓存、登记会话级关闭）。"""
        if name not in pset_cache:
            ps = gb.build_provider_set(_meta(name)["dir"])
            closers.append(ps.close)
            pset_cache[name] = ps
        return pset_cache[name]

    def _scope_dict(scope: Any) -> dict:
        if scope is None:
            return {}
        if isinstance(scope, str):
            scope = json.loads(scope or "{}")
        if not isinstance(scope, dict):
            raise ValueError("scope 须为 JSON 对象（dict）")
        return scope

    def _read_state() -> dict | None:
        f = Path(workspace) / gb.STATE_FILE
        if not f.is_file():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    @tool
    def gw_plugins() -> str:
        """列出已挂载的 grounded-writing 领域 plugin（名称+简介）。"""
        rows = []
        for f in sorted(root.glob("*/outline.yaml")):
            d = f.parent
            desc = ""
            sk = d / "SKILL.md"
            if sk.is_file():
                for ln in sk.read_text(encoding="utf-8").splitlines():
                    if ln.startswith("description:"):
                        desc = ln.split(":", 1)[1].strip()
                        break
            rows.append(f"- {d.name}：{desc}")
        return "已挂载领域 plugin：\n" + ("\n".join(rows) or "（无）")

    @tool
    def gw_scope_schema(plugin: str) -> str:
        """查某 plugin 声明的 scope 维度（参数/类型/默认/说明）与可选章节。意图解析前调用。"""
        p = _meta(plugin)["plugin"]
        schema = (p["outline"].get("scope") or {}).get("params") or {}
        lines = [f"plugin「{plugin}」的 scope 维度："]
        for name, spec in schema.items():
            lines.append(
                f"- {name}（{spec.get('type', 'str')}，默认 {spec.get('default')!r}）："
                f"{spec.get('desc', '')}"
            )
        lines.append("- sections（list，能力级保留键）：只写哪些顶层章节")
        lines.append("顶层章节：" + "；".join(
            f"{s.get('id')} {s.get('title')}" for s in p["outline"].get("sections", [])
        ))
        return "\n".join(lines)

    @tool
    def gw_availability(plugin: str) -> str:
        """查某 plugin 数据源**实际覆盖**哪些对象/层级/年份。不确定能不能做时先调它，诚实第一。"""
        return _pset(plugin).availability()

    @tool
    def gw_generate(plugin: str, scope: dict | None = None) -> str:
        """按 scope 生成全篇（grounded-write）。scope 是 JSON 对象，键见 gw_scope_schema。
        产物落工作区：/manuscript.md、/evidence/、/judgment_queue.md。"""
        with wlock:
            try:
                info = _meta(plugin)
                pset = _pset(plugin)
                norm = gb.validate_scope(info["plugin"], _scope_dict(scope), pset.validators)
            except ValueError as e:
                return f"无法生成：{e}"
            # 幂等：以落盘状态为准（同 plugin + 同归一化 scope → 不重跑，跨进程有效）
            state = _read_state()
            same = (
                state is not None
                and state.get("plugin_dir") == str(Path(info["dir"]).resolve())
                and state.get("scope") == gb.scope_jsonable(norm)
                and (Path(workspace) / "manuscript.md").is_file()
            )
            if same:
                return _generate_reply(
                    "该 scope 的简报**已生成过**（不重复生成）。", None, full_body, workspace
                )
            overwrite = ""
            if state is not None:
                overwrite = f"（注意：已覆盖此前简报，原范围：{state.get('label', '?')}）\n"
            try:
                res = gb.run_brief(
                    info["dir"], model_spec, workspace,
                    scope=norm, provider_set=pset, verifier=_verifier_get(),
                )
            except ValueError as e:
                return f"无法生成：{e}"
            gaps = "；".join(res["gaps"]) if res["gaps"] else "无"
            skipped = "、".join(res["skipped"]) if res["skipped"] else "无"
            errors = ("；**生成失败节：" + "、".join(res["errors"]) + "（可 gw_revise 单节重试）**"
                      if res["errors"] else "")
            head = (
                f"{overwrite}已生成。范围：{res['scope']}；{res['sections']} 节"
                f"（跳过：{skipped}{errors}），证据 {res['evidence']} 条，"
                f"判断队列 {res['judgment_items']} 项；数据缺口：{gaps}"
            )
            return _generate_reply(head, res["manuscript_path"], full_body, workspace)

    @tool
    def gw_revise(plugin: str, section_id: str, instruction: str) -> str:
        """单节修订：按指令重取证据并重写该节（如"3.1 突出建设占用对比"），整篇自动重装配；
        该节旧判断项自动失效（superseded）。不要为局部改动重跑 gw_generate。"""
        with wlock:
            try:
                info = _meta(plugin)
                res = gb.revise_section(
                    info["dir"], workspace, section_id, instruction, model_spec,
                    provider_set=_pset(plugin), verifier=_verifier_get(),
                )
            except ValueError as e:
                return f"无法修订：{e}"
        if not res.get("ok"):
            return res.get("message", "修订失败")
        return (
            f"已修订节 {res['section']}（{res['word_count']} 字，"
            f"未着地数字 {res['ungrounded_numbers']} 个，新判断项 {res['judgment_items']}）。\n"
            "【修订后该节正文如下，汇报只能引用其中数字】\n"
            f"{res['text']}"
        )

    @tool
    def gw_judgments() -> str:
        """查看判断队列（待人裁决的高杠杆项，按杠杆降序）。生成/修订后主动调用并向用户呈报。"""
        rows = gb.load_queue(workspace)
        if not rows:
            return "判断队列为空（无待裁决项）。"
        return "待裁决判断项：\n" + "\n".join(
            f"- id={d['id']} [{d['type']} L{d['leverage']}] ({d['ref']}) {d['detail']}"
            f" → 建议：{d['suggested_action']}"
            for d in rows
        )

    @tool
    def gw_resolve_judgment(item_id: str, resolution: str, note: str = "") -> str:
        """处置一条判断项：resolution = resolved（已按裁决处理）或 dismissed（用户决定忽略）。
        只在用户明确裁决后调用，并在 note 里记下裁决内容。"""
        try:
            hit = gb.set_judgment_status(workspace, item_id, resolution, note)
        except ValueError as e:
            return f"处置失败：{e}"
        return f"已处置 {hit['id']} → {resolution}（{note or '无备注'}）"

    return [gw_plugins, gw_scope_schema, gw_availability, gw_generate, gw_revise,
            gw_judgments, gw_resolve_judgment]


def _generate_reply(head: str, manuscript_path: str | None, full_body: bool, workspace: str) -> str:
    """generate 的回包：裸外壳回全文（唯一 grounding 通道）；VFS 外壳回摘要+读稿指引。"""
    mp = Path(manuscript_path) if manuscript_path else Path(workspace) / "manuscript.md"
    if full_body:
        body = mp.read_text(encoding="utf-8")
        return (
            f"{head}\n正文已写入工作区 /manuscript.md。\n\n"
            "【以下是简报正文。向用户汇报时只能引用此正文中的内容与数字，"
            "严禁改写、四舍五入或编造任何数字；如需概述也必须忠于下文】\n"
            f"{body}"
        )
    return (
        f"{head}\n正文已写入工作区 /manuscript.md。\n"
        "**汇报前必须先用 read_file 读 /manuscript.md（或相关节），只引用读到的内容与数字；"
        "严禁凭记忆概述、改写或四舍五入。**"
    )


# ───────────────────────── metric-query 能力工具集（正常对话查库真值）─────────────────────────


def make_metric_query_tools(
    skills_root: str,
    workspace: str,
    model_spec: str,
    closers: list[Callable[[], None]],
    *,
    full_body: bool = True,
) -> list:
    """db_* 工具：正常对话里**像简报一样**从指标库取真值。

    复用 plugin datasource.yaml 声明的同一条安全取数路径（MetricStore：只读 +
    指标/地区白名单 + 参数化，agent 不写 SQL、不见 DSN）——所以对话里查到的值与简报
    证据**逐字一致**。以 plugin 名为参数（会话不绑死单 plugin）；provider 懒建、登记会话级关闭。
    """
    root = Path(skills_root)
    pset_cache: dict[str, Any] = {}

    def _store(plugin: str) -> Any:
        if plugin not in pset_cache:
            d = root / plugin
            if not (d / "datasource.yaml").is_file():
                avail = [p.parent.name for p in root.glob("*/datasource.yaml")]
                raise ValueError(
                    f"领域 plugin「{plugin}」无数据源声明。可查库的 plugin："
                    f"{', '.join(avail) or '（无）'}"
                )
            ps = gb.build_provider_set(str(d))
            closers.append(ps.close)
            pset_cache[plugin] = ps
        sp = pset_cache[plugin].providers.get("series")
        store = getattr(sp, "store", None)
        if store is None:
            raise ValueError(f"plugin「{plugin}」的数据源不支持指标查询")
        return store

    def _years(years: str) -> tuple[int, int] | None:
        nums = re.findall(r"\d{4}", years or "")
        if len(nums) >= 2:
            return (int(nums[0]), int(nums[1]))
        if len(nums) == 1:
            return (int(nums[0]), int(nums[0]))
        return None

    @tool
    def db_indicators(plugin: str) -> str:
        """列出该领域指标库里**可查询的全部指标**（code — 名称（单位）[原始/派生]）。
        想查某个具体数值前，先用它确认指标 code（如 SLOPE_0_2_AREA）。"""
        try:
            store = _store(plugin)
        except (ValueError, RuntimeError) as e:
            return f"无法查询：{e}"
        kind_zh = {"raw": "原始", "derived": "派生"}
        rows = [
            f"- {c} — {n}（{u}）[{kind_zh.get(k, k)}]"
            for c, (n, u, k) in sorted(store.indicators().items())
        ]
        return f"plugin「{plugin}」可查指标（{len(rows)} 个）：\n" + "\n".join(rows)

    @tool
    def db_series(plugin: str, code: str, region: str = "", years: str = "") -> str:
        """查某指标在某地区的**历年真值**（直接来自数据库；含确定性派生量：累计变化/变化率/年均）。
        region 缺省=该领域默认地区；years 形如 "2020-2023" 限定区间。
        这是"数据库里这个值是多少"的权威答案——请逐字引用、严禁改写或四舍五入。"""
        try:
            store = _store(plugin)
            e = store.as_evidence(code, region or None, years=_years(years))
        except (ValueError, RuntimeError) as exc:
            return f"无法查询：{exc}"
        if e is None:
            return f"指标 {code} 在{region or '默认地区'}无数据（该年份/地区未覆盖）。"
        return e["text"]

    @tool
    def db_compare(plugin: str, code: str, year: int, parent: str = "") -> str:
        """某指标**某年**在 parent（缺省=默认地区）下各子地区的值（降序）——分区对比。"""
        try:
            store = _store(plugin)
            e = store.region_evidence(code, int(year), parent=parent or None)
        except (ValueError, RuntimeError) as exc:
            return f"无法查询：{exc}"
        if e is None:
            return f"{year}年{parent or '默认地区'}下无 {code} 的分区数据。"
        return e["text"]

    @tool
    def db_coverage(plugin: str) -> str:
        """查该领域指标库**实际覆盖**的地区层级与年份（诚实判断"有没有这个粒度/年份"）。"""
        try:
            store = _store(plugin)
        except (ValueError, RuntimeError) as e:
            return f"无法查询：{e}"
        return store.availability_text()

    return [db_indicators, db_series, db_compare, db_coverage]


# 能力注册表：能力名 → 工具工厂（skills_root, workspace, model_spec, closers, *, full_body）
CAPABILITY_TOOLSETS: dict[str, Callable[..., list]] = {
    "grounded-writing": make_grounded_write_tools,
    "metric-query": make_metric_query_tools,
}


def build_capability_tools(
    skills_root: str,
    workspace: str,
    model_spec: str,
    capabilities: Sequence[str],
    *,
    full_body: bool = True,
) -> tuple[list, list[Callable[[], None]]]:
    """runtime 工具 + 按列表注入的能力工具。返回 (tools, closers)——closers 由会话 close 调用，
    **传引用**给会话（能力工具会在运行中途登记新关闭器，如 plugin 首次取数建的连接）。"""
    closers: list[Callable[[], None]] = []
    tools = make_runtime_tools(skills_root)
    for cap in capabilities:
        if cap not in CAPABILITY_TOOLSETS:
            raise ValueError(f"未注册的能力：{cap}。已注册：{', '.join(CAPABILITY_TOOLSETS)}")
        tools += CAPABILITY_TOOLSETS[cap](
            skills_root, workspace, model_spec, closers, full_body=full_body
        )
    return tools, closers


# ───────────────────────── 裸 langgraph 外壳（实验/调试用）─────────────────────────


def build_react_agent(
    workspace: str,
    model_spec: str,
    *,
    skills_root: str,
    capabilities: Sequence[str] = ("grounded-writing",),
    checkpointer: Any = None,
) -> Any:
    """裸 langgraph 外壳（无 VFS/文件工具；轻、便宜，验证意图→执行用）。

    无文件工具 ⇒ gw_generate 用 full_body=True（全文回包是它唯一的 grounding 通道）。
    生产会话外壳见 session/build.py::build_chat_session（统一 workspace + 持久线程）。
    """
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.prebuilt import create_react_agent

    tools, _closers = build_capability_tools(
        skills_root, workspace, model_spec, capabilities, full_body=True
    )
    return create_react_agent(
        get_chat_model(model_spec, temperature=0),
        tools,
        prompt=prompts.load("runtime_sys"),
        checkpointer=checkpointer or MemorySaver(),
    )
