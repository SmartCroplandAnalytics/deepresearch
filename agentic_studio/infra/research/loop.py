"""研究子环驱动 —— 状态外置 harness + policy（架构 §5.1/§14.1，参照 harness-1 agent.py）。

policy（LLM）每轮看「系统提示 + 工作记忆(WM.to_text) + 最近观察」，输出**一个**工具调用(JSON)；
harness 执行该工具、改 WM、回观察；直到 end_search 或耗尽轮次。WM 即可恢复状态。

MVP：单工具/轮、JSON 解析（不依赖各家原生 tool-calling，跨 provider 稳）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from agentic_studio import prompts
from agentic_studio.infra.llm import get_chat_model
from agentic_studio.infra.research.search import CorpusSearcher
from agentic_studio.infra.research.state import WorkingMemory
from agentic_studio.infra.research.verify import Verifier

MAX_TURNS = 14
SEARCH_K = 8
READ_CHARS = 1500


def _system(scope: str) -> str:
    return prompts.render("research_loop_sys", scope=scope)


def _parse_call(text: str) -> dict | None:
    t = (text or "").strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(t[i : j + 1])
        if isinstance(obj, dict) and "tool" in obj:
            return obj
    except Exception:
        # 容错：找第一个含 "tool" 的 JSON 子串
        depth = 0
        start = -1
        for k, ch in enumerate(t):
            if ch == "{":
                if depth == 0:
                    start = k
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        o = json.loads(t[start : k + 1])
                        if isinstance(o, dict) and "tool" in o:
                            return o
                    except Exception:
                        pass
    return None


def _dispatch(
    tool: str, args: dict, wm: WorkingMemory, s: CorpusSearcher, v: Verifier, read_seen: set[str]
) -> str:
    if tool == "semantic_search":
        q = str(args.get("query", "")).strip()
        nodes = s.semantic(q, SEARCH_K)
        new = wm.add_to_pool(nodes)
        wm.add_search_record("semantic", q, len(nodes), new)
        return "命中：\n" + "\n".join(
            f"  {n.node_id} <{n.meta.get('score')}>: {n.title} — {n.snippet}" for n in nodes
        )
    if tool == "keyword_search":
        kws = list(args.get("keywords", []))
        nodes = s.keyword(kws, SEARCH_K)
        new = wm.add_to_pool(nodes)
        wm.add_search_record("keyword", ",".join(kws), len(nodes), new)
        return "命中：\n" + "\n".join(f"  {n.node_id}: {n.title} — {n.snippet}" for n in nodes) if nodes else "无字面命中。"
    if tool == "read":
        ids = list(args.get("node_ids", []))
        fresh = [i for i in ids if i not in read_seen]
        if not fresh:  # 全已读 → 短路，别再喂全文（仿 harness-1 already-read）
            return f"这些节点都已读过（{', '.join(ids[:5])}）。别再 read——请 curate、verify 或换查询。"
        read_seen.update(fresh)
        return wm.review(fresh)[: READ_CHARS * len(fresh[:5]) or READ_CHARS]
    if tool == "curate":
        return wm.curate(
            add=list(args.get("add", [])),
            remove=list(args.get("remove", [])),
            importance=dict(args.get("importance", {})),
            notes=dict(args.get("notes", {})),
        )
    if tool == "verify":
        ids = list(args.get("node_ids", []))[:5]
        claim = str(args.get("claim", ""))
        out = []
        for nid in ids:
            node = wm.doc_store.get(nid)
            src = node.full_text if node else s.full_text(nid)
            verdict, reason = v.verify(claim, src)
            wm.record_verify(nid, claim, verdict, reason)
            out.append(f"  {nid}: {verdict} ({reason})")
        return f"verify「{claim}」:\n" + "\n".join(out)
    return f"未知工具 {tool}。"


def run_research_scope(
    scope: str,
    searcher: CorpusSearcher,
    verifier: Verifier,
    model_spec: str,
    *,
    max_turns: int = MAX_TURNS,
    on_event: Callable[[str, Any], None] | None = None,
) -> WorkingMemory:
    """跑一个研究范围 → WorkingMemory（curated = 证据，export_evidence 落 evidence/）。"""
    wm = WorkingMemory(scope)
    policy = get_chat_model(model_spec, temperature=0.3)
    recent = "（还没有行动）"
    read_seen: set[str] = set()
    last_sig: str | None = None
    repeats = 0
    for turn in range(max_turns):
        wm.advance()
        near_budget = turn >= max_turns - 2
        budget_note = "\n（预算将尽：把可信候选 curate 进精选集，然后 end_search）" if near_budget else ""
        msgs = [
            ("system", _system(scope)),
            ("human", f"{wm.to_text()}\n\n最近观察：\n{recent}{budget_note}\n\n输出下一步的一个工具调用(JSON)。"),
        ]
        try:
            resp = policy.invoke(msgs)
            content = getattr(resp, "content", str(resp))
        except Exception as e:  # noqa: BLE001
            recent = f"模型调用出错：{e}"
            continue
        call = _parse_call(content)
        if call is None:
            recent = '上次输出无法解析。只输出一个 JSON：{"tool":"..","args":{..}}'
            continue
        tool = str(call.get("tool", ""))
        args = call.get("args", {}) if isinstance(call.get("args"), dict) else {}
        if on_event:
            on_event(tool, args)
        if tool == "end_search":
            wm.search_history.append(f"end: {args.get('reasoning', '')}")
            break

        # 确定性护栏：连续相同调用 → 拦截（policy 自纠不可靠，harness 兜底，§16）
        sig = tool + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False)
        if sig == last_sig:
            repeats += 1
        else:
            last_sig, repeats = sig, 0
        if repeats >= 2:  # 第三次完全相同 → 强制收尾
            wm.search_history.append("end: 重复调用过多，harness 强制收尾")
            break
        if repeats >= 1:  # 第二次完全相同 → 不执行，硬 nudge
            recent = (
                f"你刚做过完全相同的调用 `{tool}`，没有进展。换一个动作：把候选 curate 进精选集 / "
                "换一个完全不同的查询 / 或 end_search。不要重复。"
            )
            continue
        recent = _dispatch(tool, args, wm, searcher, verifier, read_seen)
    return wm
