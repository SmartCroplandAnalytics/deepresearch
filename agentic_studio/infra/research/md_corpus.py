"""节点级 md 语料检索器（架构 §13.1：大文档=子语料）。

把 md 书按标题切成"节"叶节点（超长按窗切），**节全文** embed + 检索；node.full_text 是
真实节文本（不是摘要）——让 verify 拿到全文源、保真精准（§8/§14）。

接口与 research.search.CorpusSearcher 一致（semantic/keyword/full_text），可直接喂 run_research_scope。
洞 A（脏 OCR 结构）暂不处理：假设标题基本可用，仅丢 <MIN_SEC 字的垃圾节。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agentic_studio.infra.corpus.embed import DEFAULT_MODEL, Embedder, cosine_topk, mmr_topk
from agentic_studio.infra.research.state import Node

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
MAX_CHARS = 2400   # 叶节点上限（embed 限 + 保持聚焦）
OVERLAP = 200
MIN_SEC = 80       # 丢弃太短的节（空标题 / OCR 垃圾）


def split_book(text: str, book_tag: str, book_name: str) -> list[Node]:
    """一本书 → 节点级叶节点列表（标题切 + 超长窗切 + 面包屑作 title）。"""
    lines = text.split("\n")
    stack: list[tuple[int, str]] = []
    cur: list[str] = []
    crumb = book_name
    secs: list[tuple[str, str]] = []  # (crumb, body)

    def flush() -> None:
        body = "\n".join(cur).strip()
        if body:
            secs.append((crumb, body))

    for ln in lines:
        m = _HEADING.match(ln)
        if m:
            flush()
            cur = []
            lvl, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, title))
            crumb = book_name + " > " + " > ".join(t for _, t in stack)
            cur = [ln]
        else:
            cur.append(ln)
    flush()
    if not secs:
        secs = [(book_name, text.strip())]

    nodes: list[Node] = []
    idx = 0
    for crumb_i, body in secs:
        chunks = [body] if len(body) <= MAX_CHARS else [
            body[i : i + MAX_CHARS] for i in range(0, len(body), MAX_CHARS - OVERLAP)
        ]
        for ch in chunks:
            if len(ch.strip()) < MIN_SEC:
                continue
            nodes.append(Node(node_id=f"{book_tag}_{idx:04d}", title=crumb_i, full_text=ch, source=book_name))
            idx += 1
    return nodes


def _embed_cached(embedder: Embedder, texts: list[str], tag: str):
    import numpy as np

    fp = hashlib.sha256(("||".join(texts) + tag).encode("utf-8")).hexdigest()[:16]
    cache = Path(".cache/embed") / f"md_{tag}_{fp}.npz"
    if cache.exists():
        return np.load(cache)["m"]
    m = embedder.encode(texts, batch_size=64)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, m=m)
    return m


class MdNodeSearcher:
    """节点级 md 检索器（接口同 CorpusSearcher，供 run_research_scope）。"""

    def __init__(self, docs_dir: str, *, tag: str = "md", model_name: str = DEFAULT_MODEL) -> None:
        files = sorted(Path(docs_dir).rglob("*.md"))
        self.nodes: list[Node] = []
        for bi, f in enumerate(files):
            self.nodes += split_book(f.read_text(encoding="utf-8", errors="ignore"), f"B{bi}", f.stem)
        self.by_id = {n.node_id: n for n in self.nodes}
        self.ids = [n.node_id for n in self.nodes]
        self.embedder = Embedder(model_name)
        self.matrix = _embed_cached(self.embedder, [f"{n.title}\n{n.full_text}" for n in self.nodes], tag)

    # corpus 兼容垫片：研究/写作环对 .corpus.get(id) 取参考文献用
    @property
    def corpus(self) -> "MdNodeSearcher":
        return self

    def get(self, node_id: str):
        n = self.by_id.get(node_id)
        if n is None:
            return None
        # 仿 IndexEntry 的最小面：title/authors/year/venue/doi（书节只有 title=面包屑、venue=书名）
        return type("E", (), {"title": n.title, "authors": [], "year": None, "venue": n.source, "doi": None})()

    def semantic(self, query: str, k: int = 8) -> list[Node]:
        qv = self.embedder.encode([query])[0]
        out: list[Node] = []
        for row, score in cosine_topk(qv, self.matrix, k):
            n = self.by_id[self.ids[row]]
            n.meta["score"] = round(float(score), 3)
            out.append(n)
        return out

    def survey(self, scope: str, k: int = 14) -> list[str]:
        """发散式普查：MMR 选多样代表节的面包屑（给 planner 看广度，§7.1）。"""
        qv = self.embedder.encode([scope])[0]
        return [self.by_id[self.ids[row]].title for row, _s in mmr_topk(qv, self.matrix, k)]

    def keyword(self, keywords: list[str], k: int = 8) -> list[Node]:
        kws = [w.lower() for w in keywords if w.strip()]
        if not kws:
            return []
        out: list[Node] = []
        for n in self.nodes:
            hay = (n.title + n.full_text).lower()
            if all(w in hay for w in kws):
                out.append(n)
                if len(out) >= k:
                    break
        return out

    def full_text(self, node_id: str) -> str:
        n = self.by_id.get(node_id)
        return n.full_text if n else ""
