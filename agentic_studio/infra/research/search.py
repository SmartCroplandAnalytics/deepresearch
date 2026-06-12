"""语料检索 → Node —— 研究子环的"搜集"侧（架构 §14）。

复用 corpus 原语（CorpusIndex + bge-m3 矩阵 + cosine）。MVP：content_root 未配时
用摘要作节点全文（与保真探针一致）；配了 content_root 后 full_text 走 read_doc 全文。
"""

from __future__ import annotations

from pathlib import Path

from agentic_studio.infra.corpus.embed import (
    DEFAULT_MODEL,
    Embedder,
    build_or_load_matrix,
    cosine_topk,
    mmr_topk,
)
from agentic_studio.infra.corpus.loader import load_card_index
from agentic_studio.infra.research.state import Node


class CorpusSearcher:
    """节点级检索器：semantic（bge-m3 召回）+ keyword（字面）+ full_text（取全文）。"""

    def __init__(
        self,
        cards_path: str,
        abstracts_path: str | None = None,
        content_root: str | None = None,
        embed_cache: str | None = None,
        model_name: str = DEFAULT_MODEL,
    ) -> None:
        self.corpus = load_card_index(cards_path, abstracts_path, content_root)
        self.embedder = Embedder(model_name)
        cache = embed_cache or str(Path(".cache/embed/research_corpus.npz"))
        self.ids, self.matrix = build_or_load_matrix(self.corpus, self.embedder, cache)
        self._row = {i: r for r, i in enumerate(self.ids)}

    def _node(self, doc_id: str) -> Node | None:
        e = self.corpus.get(doc_id)
        if e is None:
            return None
        return Node(
            node_id=doc_id,
            title=e.title,
            full_text=self.full_text(doc_id),
            source=doc_id,
            meta={"year": e.year, "authors": e.authors[:3]},
        )

    def semantic(self, query: str, k: int = 8) -> list[Node]:
        qv = self.embedder.encode([query])[0]
        nodes: list[Node] = []
        for row, score in cosine_topk(qv, self.matrix, k):
            n = self._node(self.ids[row])
            if n:
                n.meta["score"] = round(float(score), 3)
                nodes.append(n)
        return nodes

    def survey(self, scope: str, k: int = 14) -> list[str]:
        """发散式语料普查：MMR 选多样代表的标题（给 planner 看广度，§7.1）。"""
        qv = self.embedder.encode([scope])[0]
        out: list[str] = []
        for row, _s in mmr_topk(qv, self.matrix, k):
            e = self.corpus.get(self.ids[row])
            if e and e.title:
                out.append(e.title)
        return out

    def keyword(self, keywords: list[str], k: int = 8) -> list[Node]:
        kws = [w.lower() for w in keywords if w.strip()]
        if not kws:
            return []
        out: list[Node] = []
        for e in self.corpus.all():
            row = e.row().lower()
            if all(w in row for w in kws):
                n = self._node(e.doc_id)
                if n:
                    out.append(n)
                if len(out) >= k:
                    break
        return out

    def full_text(self, node_id: str) -> str:
        """取节点全文。MVP：摘要；content_root 配了则可扩展为 read_doc 全文（§14）。"""
        e = self.corpus.get(node_id)
        if e is None:
            return ""
        # TODO(§13.1/§14): content_root + content_path → Docling 全文 / 节级；现用摘要
        return e.abstract or ""
