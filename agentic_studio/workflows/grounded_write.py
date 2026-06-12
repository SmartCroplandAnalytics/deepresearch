"""grounded-write · v0 自动一遍（架构 §6 生命周期的"研究+写作 v0"段）。

按 outline 逐节：研究子环产证据 → 写作微环成稿 → assemble（[node_id]→[N] 重编号 + 参考文献）。
GATE②交互注入循环、core 收敛、CLI 命令后续接（本模块只做自动段，建在已验证的两半身上）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agentic_studio.infra.corpus.embed import cosine_topk
from agentic_studio.infra.research.loop import run_research_scope
from agentic_studio.infra.research.search import CorpusSearcher
from agentic_studio.infra.research.verify import Verifier
from agentic_studio.infra.writing import write_section
from agentic_studio.infra.writing.assemble import assemble as _assemble

_CITE = re.compile(r"\[([0-9A-Za-z_]+)\]")


class PoolSelector:
    """共享证据池的"按节选材"器（research-once → write-many，架构 §7.1→写作）。

    把 fanout 产出的池节点一次性 embed，之后每节在**池内**做语义召回——写作不再逐节
    重跑研究，而是从同一份去重池里各取所需（含 bridge 提档后的重要性）。
    """

    def __init__(self, pool: dict[str, dict], searcher: Any) -> None:
        self.pool = pool
        self.searcher = searcher
        self.ids = [nid for nid, p in pool.items() if (p.get("text") or "").strip()]
        if self.ids:
            texts = [f"{pool[nid]['title']}\n{pool[nid]['text']}" for nid in self.ids]
            self.matrix = searcher.embedder.encode(texts)
        else:
            self.matrix = None

    def select(self, scope: str, k: int = 8) -> list[dict]:
        """返回该 scope 在池内最相关的 k 条证据（write_section 入参格式）。"""
        if not self.ids or self.matrix is None:
            return []
        qv = self.searcher.embedder.encode([scope])[0]
        out: list[dict] = []
        for row, score in cosine_topk(qv, self.matrix, min(k, len(self.ids))):
            nid = self.ids[row]
            p = self.pool[nid]
            out.append({
                "id": nid, "title": p["title"], "text": p["text"],
                "importance": p.get("importance", "fair"), "score": round(float(score), 3),
            })
        return out


def _references(node_ids: list[str], corpus: Any) -> dict[str, str]:
    """node_id → 参考文献条目（从 IndexEntry：作者/年/题/期刊/DOI，缺则跳过）。"""
    out: dict[str, str] = {}
    for nid in node_ids:
        e = corpus.get(nid)
        if e is None:
            out[nid] = nid
            continue
        authors = "、".join(e.authors[:3]) + ("等" if len(e.authors) > 3 else "")
        parts = [p for p in [authors, f"（{e.year}）" if e.year else "", e.title, e.venue, e.doi] if p]
        out[nid] = ". ".join(parts) if parts else (e.title or nid)
    return out


def assemble(drafted: list[dict], corpus: Any) -> tuple[str, str]:
    """drafted=[{section, text}] → (正文带[N], 参考文献md)。重编号在 writing.assemble（共享）。"""
    items = [
        {
            "heading": f"## {d['section'].get('id', '')} {d['section'].get('title', '')}",
            "text": d["text"],
        }
        for d in drafted
    ]
    cited = {nid for d in drafted for nid in _CITE.findall(d["text"])}
    refs = _references(sorted(cited), corpus)
    return _assemble(items, lambda nid: refs.get(nid, nid))


def generate_v0(
    sections: list[dict],
    searcher: CorpusSearcher,
    verifier: Verifier,
    model_spec: str,
    workspace: str,
    *,
    on_event: Callable[[str, Any], None] | None = None,
) -> dict:
    """逐节 研究→写作 → assemble → 落 workspace。返回路径与判断队列。"""
    ws = Path(workspace)
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    drafted: list[dict] = []
    all_items: list = []

    for sec in sections:
        sid = sec.get("id", "?")
        scope = f"{sec.get('title','')}：{sec.get('content','')}（key_question: {sec.get('key_question','')}）"
        if on_event:
            on_event("research_start", {"section": sid, "scope": sec.get("title", "")})
        wm = run_research_scope(scope, searcher, verifier, model_spec,
                                on_event=lambda t, a, sid=sid: on_event and on_event(f"R:{t}", {"section": sid, **(a if isinstance(a, dict) else {})}))
        (ws / "evidence" / f"{sid}.md").write_text(wm.export_evidence(), encoding="utf-8")
        evidence = [
            {
                "id": nid,
                "title": wm.doc_store[nid].title,
                "text": wm.doc_store[nid].full_text,
                "importance": wm.curated_importance.get(nid, "fair"),
            }
            for nid in wm.curated_ids if nid in wm.doc_store and wm.doc_store[nid].full_text
        ]
        if on_event:
            on_event("write_start", {"section": sid, "evidence": len(evidence)})
        text, items, stats = write_section(
            sec, evidence, model_spec, verifier=verifier,
            on_event=lambda t, a: on_event and on_event(f"W:{t}", a),
        )
        drafted.append({"section": sec, "text": text})
        all_items.extend(items)
        if on_event:
            on_event("section_done", {"section": sid, "wc": stats.get("word_count"), "dangling": stats.get("dangling")})

    body, ref_md = assemble(drafted, searcher.corpus)
    manuscript = body + "\n\n" + ref_md
    (ws / "manuscript.md").write_text(manuscript, encoding="utf-8")
    queue = "# 判断队列\n\n" + "\n".join(
        f"- [{it.type} L{it.leverage}] ({it.ref}) {it.detail} → {it.suggested_action}" for it in
        sorted(all_items, key=lambda x: -x.leverage)
    )
    (ws / "judgment_queue.md").write_text(queue, encoding="utf-8")
    return {
        "manuscript_path": str(ws / "manuscript.md"),
        "judgment_items": all_items,
        "sections": len(sections),
    }
