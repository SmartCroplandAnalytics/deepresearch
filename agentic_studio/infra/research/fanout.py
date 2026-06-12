"""研究 fan-out 编排 —— 真·递归 map-reduce（架构 §7）。

每个节点：planner 决定 → 若可再拆且未到 max_depth，则 **fan-out 子节点**（子节点可再 fan-out，
即 fanout 的 fanout）；否则作**叶子**跑已验证的 research loop。每个内部节点在子节点齐了之后做
一道 **确定性 merge（reduce）**，逐层冒泡到根 → 共享证据池。

封顶变量：max_depth（层数）/ max_width（每层分支）/ max_leaves（总叶子）/ leaf_max_turns。
并发：叶子（research loop）由 Semaphore(concurrency) 限流（多 agent 并行）；内部节点用线程
等子节点（廉价、只阻塞+merge），避免嵌套线程池死锁。embed 用锁串行化（query 编码很快）。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agentic_studio import prompts
from agentic_studio.infra.llm import get_chat_model
from agentic_studio.infra.research.loop import run_research_scope
from agentic_studio.infra.research.state import _IMP_RANK

_BUMP = {"low": "fair", "fair": "high", "high": "very_high", "very_high": "very_high"}


def _decompose(scope: str, planner: Any, k: int, searcher: Any) -> list[str]:
    """语料感知拆解（A）：先 semantic 粗扫，按"语料确有什么"来拆——修盲拆漂移/空支。"""
    survey = ""
    try:
        titles = searcher.survey(scope, 14)  # MMR 多样代表（发散，§7.1）
        survey = "\n".join(f"- {t}" for t in titles)
    except Exception:  # noqa: BLE001
        try:
            survey = "\n".join(f"- {getattr(h, 'title', '')}" for h in searcher.semantic(scope, 12))
        except Exception:  # noqa: BLE001
            pass
    user = f"【范围】{scope}\n\n【语料代表文献（拆解须以此为据）】\n{survey or '（粗扫无结果）'}"
    try:
        resp = planner.invoke([("system", prompts.render("research_plan_sys", k=k)), ("human", user)])
        t = getattr(resp, "content", "")
        i, j = t.find("["), t.rfind("]")
        arr = json.loads(t[i : j + 1]) if i >= 0 and j > i else []
        return [str(x).strip() for x in arr if str(x).strip()][:k]
    except Exception:  # noqa: BLE001
        return []


def _wm_to_pool(scope_id: str, wm: Any) -> dict[str, dict]:
    pool: dict[str, dict] = {}
    if wm is None:
        return pool
    for nid in wm.curated_ids:
        node = wm.doc_store.get(nid)
        pool[nid] = {
            "title": node.title if node else nid,
            "text": node.full_text if node else "",
            "importance": wm.curated_importance.get(nid, "fair"),
            "scopes": [scope_id],
            "notes": [wm.curated_notes[nid]] if wm.curated_notes.get(nid) else [],
        }
    return pool


def merge_pools(pools: list[dict[str, dict]]) -> dict[str, dict]:
    """确定性 merge（reduce）：去重 by node_id、取最高重要性、累计 scopes/notes、bridge 提档。"""
    out: dict[str, dict] = {}
    for pool in pools:
        for nid, p in pool.items():
            if nid not in out:
                out[nid] = {**p, "scopes": list(p["scopes"]), "notes": list(p["notes"])}
            else:
                o = out[nid]
                if _IMP_RANK.get(p["importance"], 2) < _IMP_RANK.get(o["importance"], 2):
                    o["importance"] = p["importance"]
                o["scopes"].extend(p["scopes"])
                o["notes"].extend(p["notes"])
    for o in out.values():  # bridge：≥2 scope 命中 → 提一档
        if len(set(o["scopes"])) >= 2:
            o["importance"] = _BUMP[o["importance"]]
    return dict(sorted(out.items()))


def research_fanout(
    task: str,
    searcher: Any,
    verifier: Any,
    model_spec: str,
    *,
    max_depth: int = 2,
    max_width: int = 5,
    max_leaves: int = 16,
    concurrency: int = 4,
    leaf_max_turns: int = 12,
    workspace: str | None = None,
    on_event: Callable[[str, Any], None] | None = None,
) -> dict:
    """递归 fan-out（fanout 的 fanout，深度封顶）→ 共享证据池。返回 {pool, leaf_count, bridges}。

    workspace 给定时落盘 evidence/manifest.json + pool.md（workspace-as-state，可恢复/审计）。
    """
    planner = get_chat_model(model_spec, temperature=0.2)
    sem = threading.Semaphore(concurrency)
    emb_lock = threading.Lock()
    sid_counter = {"n": 0}
    sid_lock = threading.Lock()

    orig_semantic = searcher.semantic
    orig_survey = searcher.survey

    def _safe_semantic(q: str, k: int = 8):  # noqa: ANN001
        with emb_lock:
            return orig_semantic(q, k)

    def _safe_survey(scope: str, k: int = 14):  # noqa: ANN001
        with emb_lock:
            return orig_survey(scope, k)

    searcher.semantic = _safe_semantic  # type: ignore[attr-defined]
    searcher.survey = _safe_survey  # type: ignore[attr-defined]

    def _next_sid() -> str:
        with sid_lock:
            sid_counter["n"] += 1
            return f"L{sid_counter['n']}"

    def _node(scope: str, depth: int, budget: int) -> dict[str, dict]:
        """budget = 本子树可用叶子数（自顶向下广度均分，防早分支饿死晚分支）。"""
        if budget <= 0:
            return {}
        children: list[str] = []
        if depth < max_depth and budget > 1:
            children = _decompose(scope, planner, min(max_width, budget), searcher)
        if not children:  # ── 叶子（消耗 1 预算）──
            sid = _next_sid()
            if on_event:
                on_event("leaf_start", {"id": sid, "depth": depth, "scope": scope[:50]})
            with sem:  # 限流：并发叶子 ≤ concurrency（多 agent）
                wm = run_research_scope(scope, searcher, verifier, model_spec, max_turns=leaf_max_turns)
            if on_event:
                on_event("leaf_done", {"id": sid, "curated": len(wm.curated_ids)})
            return _wm_to_pool(sid, wm)

        # ── 内部节点：把 budget 在子节点间**广度均分**，并行 fan-out，merge ──
        n = len(children)
        if budget < n:                       # 预算不够每支 → 只取前 budget 支、各 1
            children, n = children[:budget], budget
            allocs = [1] * n
        else:
            base, rem = divmod(budget, n)
            allocs = [base + (1 if i < rem else 0) for i in range(n)]
        if on_event:
            on_event("fanout", {"depth": depth, "scope": scope[:40], "children": n, "allocs": allocs})
        results: list[dict] = [{} for _ in children]
        threads = []
        for i, (c, a) in enumerate(zip(children, allocs)):
            t = threading.Thread(target=lambda i=i, c=c, a=a: results.__setitem__(i, _node(c, depth + 1, a)))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        return merge_pools(results)

    try:
        pool = _node(task, 0, max_leaves)
    finally:
        searcher.semantic = orig_semantic  # type: ignore[attr-defined]
        searcher.survey = orig_survey  # type: ignore[attr-defined]

    bridges = sum(1 for p in pool.values() if len(set(p["scopes"])) >= 2)
    leaves = sid_counter["n"]

    if workspace:  # C：落盘（轻量 manifest 存元信息；全文经 node_id 回取，§14）
        ev = Path(workspace) / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        manifest = {
            nid: {"title": p["title"], "importance": p["importance"],
                  "scopes": sorted(set(p["scopes"])), "notes": p["notes"]}
            for nid, p in pool.items()
        }
        (ev / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = [f"# 证据池（{len(pool)} 节点，{bridges} bridge，{leaves} 叶子）", ""]
        for nid, p in sorted(pool.items(), key=lambda kv: -len(set(kv[1]["scopes"]))):
            rows.append(f"- [{nid}] <{p['importance']}> scope×{len(set(p['scopes']))} {p['title']}")
        (ev / "pool.md").write_text("\n".join(rows), encoding="utf-8")

    if on_event:
        on_event("merged", {"leaves": leaves, "evidence": len(pool), "bridges": bridges})
    return {"pool": pool, "leaf_count": leaves, "bridges": bridges, "evidence_count": len(pool)}
