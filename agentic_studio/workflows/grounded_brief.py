"""grounded-brief —— grounded-write 能力的大纲驱动器（领域无关）。

消费一个 **plugin**（skill-set 目录）：
- `outline.yaml`：大纲 + 每节证据规格 + **scope schema**（本任务有哪些范围维度，能力层不预设）
- `style.md`：文风；`datasource.yaml`：数据源声明（经 EvidenceProvider 取证据）

能力层职责（全部领域无关）：
1. 校验 scope dict ←→ plugin 声明的 schema（类型/默认/校验器；`sections` 是能力级保留键）
2. 把 scope 绑进证据规格（`$param` 替换、`when:` 门控、provider fanout_keys 列表展开）
3. 逐叶子节取证据 → grounded 撰写（节级并行）→ 确定性装配（[N] + 来源）
4. 产物落 workspace：manuscript.md / evidence/manifest.json（证据全文快照，审计链）/
   judgment_queue.{json,md} / brief_state.json（节稿状态，供 revise 单节回边）

意图理解（自然语言 → scope dict）**不在本层**：那是对话层按 plugin SKILL.md 做的事。
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any

import yaml

from agentic_studio import prompts
from agentic_studio.core.judgment import JudgmentItem
from agentic_studio.infra.data import ProviderSet, build_provider_set
from agentic_studio.infra.writing import write_section
from agentic_studio.infra.writing.artifacts import FIG_TOKEN, TAB_TOKEN, number_artifacts
from agentic_studio.infra.writing.assemble import assemble

_REF = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")
STATE_FILE = "brief_state.json"


# ───────────────────────── plugin 加载 ─────────────────────────


def load_plugin(plugin_dir: str | Path) -> dict:
    """读 plugin：outline.yaml（含 scope schema）+ style.md。"""
    p = Path(plugin_dir)
    outline = yaml.safe_load((p / "outline.yaml").read_text(encoding="utf-8"))
    style = (p / "style.md").read_text(encoding="utf-8") if (p / "style.md").exists() else ""
    return {"outline": outline, "style": style, "dir": str(p)}


def _leaves(outline: dict) -> list[dict]:
    """展平出叶子节（带 evidence 或 data_gap 的最小撰写单位）。"""
    out: list[dict] = []

    def walk(node: dict) -> None:
        kids = node.get("children")
        if kids:
            for k in kids:
                walk(k)
        else:
            out.append(node)

    for s in outline.get("sections", []):
        walk(s)
    return out


# ───────────────────────── scope：schema 校验 + 标签 ─────────────────────────


def _norm_value(name: str, p: dict, val: Any) -> Any:
    t = p.get("type", "str")
    if val is None:
        return None
    if t == "bool":
        return bool(val)
    if t == "int":
        return int(val)
    if t == "str":
        return str(val)
    if t == "list_str":
        if isinstance(val, str):
            val = [val]
        return [str(x) for x in val]
    if t == "year_range":
        if isinstance(val, (list, tuple)) and len(val) == 2:
            lo, hi = int(val[0] or 0), int(val[1] or 0)
            if lo and hi:
                return (min(lo, hi), max(lo, hi))
            return None
        raise ValueError(f"scope.{name} 须为 [起, 止] 两个年份")
    raise ValueError(f"plugin scope schema 用了未知类型：{t}（参数 {name}）")


def validate_scope(
    plugin: dict, scope: dict | None, validators: dict[str, Callable[[Any], str | None]]
) -> dict:
    """scope dict ←→ plugin 声明的 schema：未知键拒绝、类型归一、默认值、check 校验。

    `sections` 是能力级保留键（大纲是能力概念）：顶层章节 id 过滤，校验存在性。
    """
    schema = (plugin["outline"].get("scope") or {}).get("params") or {}
    scope = dict(scope or {})
    sections = scope.pop("sections", None) or []

    unknown = sorted(set(scope) - set(schema))
    if unknown:
        raise ValueError(
            f"未知 scope 参数：{', '.join(unknown)}。"
            f"本 plugin 支持：{', '.join(schema) or '（无）'}（另有能力级保留键 sections）"
        )
    out: dict[str, Any] = {}
    for name, p in schema.items():
        raw = scope.get(name, p.get("default"))
        if isinstance(raw, list) and not raw:
            raw = p.get("default")  # 空列表视同"未提供"→ 回退默认（防 [] 静默生成全缺口稿）
        val = _norm_value(name, p, raw)
        chk = p.get("check")
        if val is not None and chk:
            checker = validators.get(chk)
            if checker is None:
                raise ValueError(f"plugin 声明了校验器 {chk}，但数据源未提供（datasource 缺失？）")
            for v in val if isinstance(val, list) else [val]:
                err = checker(v)
                if err:
                    raise ValueError(f"scope.{name}={v}：{err}")
        out[name] = val

    top_ids = {str(s.get("id", "")) for s in plugin["outline"].get("sections", [])}
    bad = [s for s in map(str, sections) if s not in top_ids]
    if bad:
        raise ValueError(f"未知章节 id：{', '.join(bad)}。可选：{', '.join(sorted(top_ids))}")
    out["sections"] = [str(s) for s in sections]
    return out


def scope_jsonable(scope: dict) -> dict:
    """归一化 scope → 可 JSON 序列化形态（tuple→list），供落盘与等值比较（幂等判定）。"""
    return {k: list(v) if isinstance(v, tuple) else v for k, v in scope.items()}


def _fmt(val: Any) -> str:
    if val is None:
        return "全部"
    if isinstance(val, bool):
        return "是" if val else "否"
    if isinstance(val, (list,)):
        return "、".join(map(str, val))
    if isinstance(val, tuple) and len(val) == 2:
        return f"{val[0]}—{val[1]}"
    return str(val)


def scope_label(plugin: dict, scope: dict) -> str:
    """渲染 scope 的人读标签。模板由 plugin 给（outline.scope.label，$param）；缺省 k=v。"""
    tpl = (plugin["outline"].get("scope") or {}).get("label", "")
    vals = {k: _fmt(v) for k, v in scope.items() if k != "sections"}
    label = Template(tpl).safe_substitute(**vals) if tpl else "，".join(
        f"{k}={v}" for k, v in vals.items()
    )
    if scope.get("sections"):
        label += f"，章节 {'/'.join(scope['sections'])}"
    return label or "（无范围参数）"


# ───────────────────────── 证据规格：绑定 / 门控 / 展开 ─────────────────────────


def _bind_spec(spec: dict, scope: dict) -> dict | None:
    """把 scope 值替换进规格（值为 "$param" 的键）；`when:` 为假 → 整条规格被关掉（None）。"""
    out: dict[str, Any] = {}
    for k, v in spec.items():
        if isinstance(v, str):
            m = _REF.match(v.strip())
            if m:
                name = m.group(1)
                if name not in scope:
                    raise ValueError(f"evidence 规格引用了未声明的 scope 参数 ${name}")
                v = scope[name]
        out[k] = v
    if "when" in out and not out.pop("when"):
        return None
    return out


def _expand(spec: dict, fanout_keys: tuple[str, ...]) -> list[dict]:
    """fanout 键为列表 → 展开为多次取数（如多地区对比，一地区一证据）。"""
    specs = [spec]
    for key in fanout_keys:
        nxt: list[dict] = []
        for s in specs:
            v = s.get(key)
            if isinstance(v, list):
                nxt += [{**s, key: x} for x in v]
            else:
                nxt.append(s)
        specs = nxt
    return specs


def lint_plugin(plugin: dict, pset: ProviderSet) -> list[str]:
    """载入时静态校验 plugin：kind 已注册、规格合法、$引用已声明。配置错误 fail-fast。"""
    schema = (plugin["outline"].get("scope") or {}).get("params") or {}
    problems: list[str] = []

    def check_refs(sid: str, spec: dict) -> None:
        for v in spec.values():
            if isinstance(v, str):
                m = _REF.match(v.strip())
                if m and m.group(1) not in schema:
                    problems.append(f"节 {sid}：$引用了未声明的 scope 参数 {v}")

    for leaf in _leaves(plugin["outline"]):
        sid = leaf.get("id", "?")
        for spec in leaf.get("evidence") or []:
            kind = spec.get("kind")
            prov = pset.providers.get(kind)
            if prov is None:
                problems.append(f"节 {sid}：未注册的证据 kind {kind!r}（datasource 未提供）")
                continue
            err = prov.lint(spec)
            if err:
                problems.append(f"节 {sid}：{err}")
            check_refs(sid, spec)
        for key in ("figures", "tables"):
            for spec in leaf.get(key) or []:
                kind = spec.get("kind")
                renderer = pset.renderers.get(kind)
                if renderer is None:
                    problems.append(f"节 {sid}：未注册的图表 kind {kind!r}（datasource 未提供）")
                    continue
                err = renderer.lint(spec)
                if err:
                    problems.append(f"节 {sid}：{err}")
                check_refs(sid, spec)
    return problems


def _gather(
    section: dict, pset: ProviderSet, scope: dict, warns: list[str]
) -> list[dict]:
    """按节规格 + scope 取证据。取数失败 → 记原因、诚实留空（不杜撰、不炸全篇）。

    ValueError = 白名单/规格拒绝（预期内）；其它异常（连接断等）同样降级为该节缺口
    并把异常类型记进原因——单节数据故障不应让整篇失败。
    """
    evs: list[dict] = []
    seen_ids: set[str] = set()
    for raw in section.get("evidence") or []:
        prov = pset.providers[raw.get("kind")]
        bound = _bind_spec(raw, scope)
        if bound is None:
            continue  # scope 把该规格门控掉了
        for s in _expand(bound, prov.fanout_keys):
            try:
                got = prov.gather(s)
            except ValueError as e:
                warns.append(f"{section.get('id', '?')}：{e}")
                continue
            except Exception as e:  # noqa: BLE001 —— 数据源故障：降级为缺口，不中断全篇
                warns.append(f"{section.get('id', '?')}：取数失败 {type(e).__name__}: {e}")
                continue
            for e in got:
                if e["id"] not in seen_ids:  # 跨规格撞 id（如 years 夹成同年）→ 去重
                    seen_ids.add(e["id"])
                    evs.append(e)
    return evs


def _render_artifacts(
    section: dict, pset: ProviderSet, scope: dict, ws: Path
) -> tuple[str, list[str], list[str]]:
    """渲染本节声明的确定性图表（**不经 LLM**，数字构造即有据）。

    返回 (markdown块, 标题列表, 失败列表)。单个图表失败只记失败、不毁节。
    """
    blocks: list[str] = []
    caps: list[str] = []
    fails: list[str] = []
    idx = 0
    for key in ("figures", "tables"):
        for raw in section.get(key) or []:
            kind = raw.get("kind")
            renderer = pset.renderers.get(kind)
            if renderer is None:
                fails.append(f"未注册的图表 kind {kind!r}")
                continue
            bound = _bind_spec(raw, scope)
            if bound is None:
                continue  # scope 门控关掉
            idx += 1
            try:
                out = renderer.render(bound, ws=ws, sid=str(section.get("id", "?")), idx=idx)
            except Exception as e:  # noqa: BLE001 —— 图表失败不毁节
                fails.append(f"{kind}: {type(e).__name__}: {e}")
                continue
            if out:
                md, cap = out
                blocks.append(md)
                caps.append(cap)
    return "\n\n".join(blocks), caps, fails


def _artifacts_note(caps: list[str]) -> str:
    if not caps:
        return ""
    return "\n" + prompts.render("artifacts_note", captions="；".join(caps))


# ───────────────────────── 产物落盘 ─────────────────────────


def _write_queue(ws: Path, items: list[JudgmentItem], *, merge: bool = False) -> None:
    """判断队列双格式：json（结构化，含 status，供 resolve 流转）+ md（人读视图）。"""
    f = ws / "judgment_queue.json"
    by_id: dict[str, dict] = {}
    if merge and f.exists():
        for d in json.loads(f.read_text(encoding="utf-8")).get("items", []):
            by_id[d["id"]] = d
    for it in items:
        by_id[it.id] = it.model_dump()
    rows = sorted(by_id.values(), key=lambda d: -d.get("leverage", 0))
    f.write_text(json.dumps({"items": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# 判断队列", ""]
    for d in rows:
        mark = "" if d.get("status") == "open" else f"（{d.get('status')}）"
        md.append(
            f"- [{d['type']} L{d['leverage']}] ({d['ref']}) {d['detail']}"
            f" → {d['suggested_action']}{mark}"
        )
    (ws / "judgment_queue.md").write_text("\n".join(md), encoding="utf-8")


def _write_manifest(ws: Path, registry: dict[str, dict], *, merge: bool = False) -> None:
    """证据**全文**快照（审计链：稿子当时依据什么写的，数据库以后变了也可复核）。"""
    f = ws / "evidence" / "manifest.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[str, dict] = {}
    if merge and f.exists():
        merged = json.loads(f.read_text(encoding="utf-8"))
    merged.update(registry)
    f.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def _assemble_and_write(
    ws: Path, plugin: dict, label: str, sections: list[dict], registry: dict[str, dict]
) -> str:
    drafted = [
        {"heading": s["heading"], "text": s["text"]} for s in sections if s["status"] != "skipped"
    ]
    body, refs = assemble(
        drafted,
        lambda nid: f"{registry.get(nid, {}).get('title', nid)}"
        f"（{registry.get(nid, {}).get('source', nid)}）",
        ref_heading="## 数据来源",
    )
    title = plugin["outline"].get("title", "简报")
    manuscript = f"# {title}\n\n_（范围：{label}）_\n\n{body}\n\n{refs}\n"
    # [[图]]/[[表]] 占位 → 图1/表1…（state 里保留占位，重装配/修订时编号始终全局一致）
    manuscript = number_artifacts(manuscript)
    (ws / "manuscript.md").write_text(manuscript, encoding="utf-8")
    return str(ws / "manuscript.md")


# ───────────────────────── 主驱动 ─────────────────────────


def run_brief(
    plugin_dir: str,
    model_spec: str,
    workspace: str,
    *,
    scope: dict | None = None,
    provider_set: ProviderSet | None = None,
    verifier: Any = None,
    on_event: Callable[[str, Any], None] | None = None,
    parallel: int = 4,
) -> dict:
    """plugin + scope dict → 逐节取证据+撰写（并行）→ 装配 → 落 workspace（含状态/快照）。"""
    started = datetime.now().isoformat(timespec="seconds")
    plugin = load_plugin(plugin_dir)
    outline, style = plugin["outline"], plugin["style"]
    lang = outline.get("language", "中文")

    own_pset = provider_set is None
    pset = provider_set or build_provider_set(plugin_dir)
    try:
        problems = lint_plugin(plugin, pset)
        if problems:
            raise ValueError("plugin 配置问题（outline.yaml）：\n" + "\n".join(problems))
        scope = validate_scope(plugin, scope, pset.validators)
        label = scope_label(plugin, scope)

        ws = Path(workspace)
        (ws / "evidence").mkdir(parents=True, exist_ok=True)
        lock = threading.Lock()

        def emit(kind: str, a: dict) -> None:
            if on_event:
                with lock:
                    on_event(kind, a)

        leaves = _leaves(outline)
        if scope["sections"]:
            leaves = [
                s for s in leaves if str(s.get("id", "")).split(".")[0] in scope["sections"]
            ]

        note = prompts.render("scope_note", label=label)

        def work(sec: dict) -> dict:
            sid, title = sec.get("id", "?"), sec.get("title", "")
            heading = f"## {sid} {title}"
            warns: list[str] = []
            try:
                evidence = _gather(sec, pset, scope, warns)
                emit("section", {"id": sid, "title": title, "evidence": len(evidence)})

                if not evidence:
                    if sec.get("optional"):
                        # 可选节（如分区下钻）在该 scope 下无意义/无数据 → 跳过而非标缺口
                        return {"id": sid, "heading": heading, "text": "",
                                "status": "skipped", "items": [], "evidence": [],
                                "warns": warns}
                    gap = sec.get("data_gap") or "；".join(warns) or "本节暂无可用数据证据"
                    return {
                        "id": sid, "heading": heading,
                        "text": prompts.render("gap_note", gap=gap), "status": "gap",
                        "items": [JudgmentItem.make("gap", sid, gap, "补数据源或人工撰写")],
                        "evidence": [], "warns": warns,
                    }

                # 确定性图表（先渲染：把"将附哪些图表"告知撰写，便于「下图/下表」衔接）
                art_md, art_caps, art_fails = _render_artifacts(sec, pset, scope, ws)
                section_dict = {
                    "id": sid, "title": title, "content": note + _artifacts_note(art_caps),
                    "key_question": sec.get("key_question", ""),
                    "word_count": sec.get("target_words") or 0,
                }
                text, items, stats = write_section(
                    section_dict, evidence, model_spec, lang=lang, style=style,
                    verifier=verifier,
                    on_event=lambda t, a, sid=sid: emit(
                        f"W:{t}", {"id": sid, **(a if isinstance(a, dict) else {})}
                    ),
                )
                # 占位 token 只能由 renderer 产生：剥掉模型正文里的杂散 token 再拼接
                text = text.replace(FIG_TOKEN, "图").replace(TAB_TOKEN, "表")
                if art_md:
                    text = f"{text}\n\n{art_md}"
                for fmsg in art_fails:
                    items.append(JudgmentItem.make(
                        "format", sid, f"图表渲染失败：{fmsg}", "检查 outline 图表声明/数据/依赖",
                    ))
                emit("section_done", {"id": sid, "wc": stats.get("word_count"),
                                      "dangling": stats.get("dangling"),
                                      "ungrounded": stats.get("ungrounded_numbers"),
                                      "repairs": stats.get("repair_rounds"),
                                      "artifacts": len(art_caps)})
                return {"id": sid, "heading": heading, "text": text, "status": "ok",
                        "items": items, "evidence": evidence, "warns": warns}
            except Exception as exc:  # noqa: BLE001 —— 单节失败（LLM 限流/网络等）不炸全篇
                emit("section_error", {"id": sid, "error": f"{type(exc).__name__}: {exc}"})
                return {
                    "id": sid, "heading": heading,
                    "text": f"（本节生成失败：{type(exc).__name__}。可对本节单独 revise 重试。）",
                    "status": "error",
                    "items": [JudgmentItem.make(
                        "gap", sid, f"生成失败：{type(exc).__name__}: {exc}",
                        "对该节 revise 重试或排查数据源/模型",
                    )],
                    "evidence": [], "warns": warns,
                }

        if parallel > 1 and len(leaves) > 1:
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                results = list(pool.map(work, leaves))
        else:
            results = [work(s) for s in leaves]

        registry: dict[str, dict] = {}
        all_items: list[JudgmentItem] = []
        for r in results:
            for e in r["evidence"]:
                registry[e["id"]] = e
            all_items.extend(r["items"])

        sections_state = [
            {"id": r["id"], "heading": r["heading"], "text": r["text"], "status": r["status"]}
            for r in results
        ]
        manuscript_path = _assemble_and_write(ws, plugin, label, sections_state, registry)
        _write_manifest(ws, registry)
        _write_queue(ws, all_items)
        (ws / STATE_FILE).write_text(json.dumps({
            "plugin_dir": str(Path(plugin_dir).resolve()),
            "scope": scope_jsonable(scope),
            "label": label,
            "sections": sections_state,
            # 溯源（轻量）：谁、在什么条件下写的——证据快照之外的 provenance 半边
            "run": {
                "model": model_spec,
                "prompts_fingerprint": prompts.fingerprint(),
                "started": started,
                "finished": datetime.now().isoformat(timespec="seconds"),
                "parallel": parallel,
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "manuscript_path": manuscript_path,
            "scope": label,
            "scope_dict": scope,
            "sections": sum(1 for r in results if r["status"] != "skipped"),
            "skipped": [r["id"] for r in results if r["status"] == "skipped"],
            "errors": [r["id"] for r in results if r["status"] == "error"],
            "evidence": len(registry),
            "judgment_items": len(all_items),
            "gaps": [it.detail for it in all_items if it.type == "gap"],
        }
    finally:
        if own_pset:
            pset.close()


# ───────────────────────── 修订回边（单节重做，整篇确定性重装配）─────────────────────────


def revise_section(
    plugin_dir: str,
    workspace: str,
    section_id: str,
    instruction: str,
    model_spec: str,
    *,
    provider_set: ProviderSet | None = None,
    verifier: Any = None,
) -> dict:
    """按指令重写**一节**（重取证据 + grounded 重写 + 数字护栏），不重跑全篇。

    依赖 run_brief 落盘的 brief_state.json；修订后整篇重装配（[N] 重编号保持一致），
    该节此前的 open 判断项自动标 superseded（指向旧文本的条目随修订失效）。
    """
    ws = Path(workspace)
    f = ws / STATE_FILE
    if not f.exists():
        raise ValueError("工作区没有 brief 状态（先 generate，再 revise）")
    state = json.loads(f.read_text(encoding="utf-8"))
    # plugin ↔ state 一致性：稿件状态是哪个 plugin 生成的，就只能用它修订
    state_dir = state.get("plugin_dir", "")
    if state_dir and Path(plugin_dir).resolve() != Path(state_dir).resolve():
        raise ValueError(
            f"当前稿件由 plugin「{Path(state_dir).name}」生成，"
            f"不能用「{Path(plugin_dir).name}」修订"
        )
    plugin = load_plugin(plugin_dir)
    label = state["label"]

    leaf = next(
        (s for s in _leaves(plugin["outline"]) if str(s.get("id")) == str(section_id)), None
    )
    if leaf is None:
        raise ValueError(f"大纲中无此叶子节：{section_id}")
    target = next((s for s in state["sections"] if s["id"] == str(section_id)), None)
    if target is None:
        raise ValueError(f"当前稿件不含节 {section_id}（不在生成时的 scope 内）")

    own_pset = provider_set is None
    pset = provider_set or build_provider_set(plugin_dir)
    try:
        # scope 重建复用同一条校验路径（year_range 等归一在 schema 里，不靠启发式猜）
        scope = validate_scope(plugin, state["scope"], pset.validators)
        warns: list[str] = []
        evidence = _gather(leaf, pset, scope, warns)
        if not evidence:
            why = "；".join(warns) or "数据缺口"
            return {"ok": False, "message": f"该节在当前 scope 下无证据（{why}），无法重写"}

        note = prompts.render("scope_note", label=label)
        art_md, art_caps, art_fails = _render_artifacts(leaf, pset, scope, ws)
        section_dict = {
            "id": leaf.get("id"), "title": leaf.get("title", ""),
            "content": (f"{note}\n" + prompts.render("revise_note", instruction=instruction)
                        + _artifacts_note(art_caps)),
            "key_question": leaf.get("key_question", ""),
            "word_count": leaf.get("target_words") or 0,
        }
        text, items, stats = write_section(
            section_dict, evidence, model_spec,
            lang=plugin["outline"].get("language", "中文"),
            style=plugin["style"], verifier=verifier,
        )
        text = text.replace(FIG_TOKEN, "图").replace(TAB_TOKEN, "表")
        if art_md:
            text = f"{text}\n\n{art_md}"
        for fmsg in art_fails:
            items.append(JudgmentItem.make(
                "format", str(section_id), f"图表渲染失败：{fmsg}",
                "检查 outline 图表声明/数据/依赖",
            ))
        target["text"], target["status"] = text, "ok"

        registry = {e["id"]: e for e in evidence}
        manuscript_path = _assemble_and_write(
            ws, plugin, label, state["sections"], _merged_registry(ws, registry)
        )
        _write_manifest(ws, registry, merge=True)
        # 旧文本的 open 判断项随修订失效（仍指向已不存在的句子）→ superseded；
        # 同一问题若在新文本里复现，新条目同 id 会在 merge 时覆盖回 open。
        _supersede_open_items(ws, str(section_id), keep_ids={it.id for it in items})
        _write_queue(ws, items, merge=True)
        state.setdefault("run", {})["revised"] = datetime.now().isoformat(timespec="seconds")
        f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "manuscript_path": manuscript_path, "section": str(section_id),
                "word_count": stats.get("word_count"),
                "ungrounded_numbers": stats.get("ungrounded_numbers"),
                "judgment_items": len(items),
                # 对话展示用：占位 token 去编号化（全局编号只在装配后的 manuscript 里）
                "text": text.replace(FIG_TOKEN, "图").replace(TAB_TOKEN, "表")}
    finally:
        if own_pset:
            pset.close()


def _merged_registry(ws: Path, new: dict[str, dict]) -> dict[str, dict]:
    f = ws / "evidence" / "manifest.json"
    out: dict[str, dict] = {}
    if f.exists():
        out = json.loads(f.read_text(encoding="utf-8"))
    out.update(new)
    return out


def _supersede_open_items(ws: Path, ref: str, keep_ids: set[str]) -> None:
    """把某节的 open 判断项标 superseded（修订后旧文本的条目失效；keep_ids 留给新条目）。"""
    f = ws / "judgment_queue.json"
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    for d in data.get("items", []):
        if d.get("ref") == ref and d.get("status") == "open" and d.get("id") not in keep_ids:
            d["status"] = "superseded"
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ───────────────────────── 判断队列：消费半边（呈人→处置）─────────────────────────


def load_queue(workspace: str, *, only_open: bool = True) -> list[dict]:
    """读判断队列（按杠杆降序）。only_open=True 只看待裁决项。"""
    f = Path(workspace) / "judgment_queue.json"
    if not f.exists():
        return []
    rows = json.loads(f.read_text(encoding="utf-8")).get("items", [])
    if only_open:
        rows = [d for d in rows if d.get("status") == "open"]
    return rows


def set_judgment_status(workspace: str, item_id: str, status: str, note: str = "") -> dict:
    """处置一条判断项（resolved / dismissed），并重写 md 视图。"""
    if status not in ("resolved", "dismissed", "open"):
        raise ValueError("status 须为 resolved / dismissed / open")
    ws = Path(workspace)
    f = ws / "judgment_queue.json"
    if not f.exists():
        raise ValueError("工作区没有判断队列")
    data = json.loads(f.read_text(encoding="utf-8"))
    hit = next((d for d in data.get("items", []) if d.get("id") == item_id), None)
    if hit is None:
        raise ValueError(f"无此判断项：{item_id}")
    hit["status"] = status
    if note:
        hit.setdefault("meta", {})["resolution_note"] = note
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_queue(ws, [JudgmentItem(**d) for d in data["items"]])
    return hit
