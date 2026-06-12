"""语料三粒度工具（架构 §9，push-pull）：
- semantic_search：bge-m3 跨语言召回（发现哪些文档相关）。
- keyword_search：卡片精确 FTS（作者/术语/DOI；按 IF·引用排序）。
- read_doc：content_path→Docling 全文（缓存）+ 文内 grep（读原文、定位段落/引文）。

懒加载：embedder / 矩阵 / Docling 仅在首次用到时拉起。仅 infra 可 import langchain/docling。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from agentic_studio.infra.corpus.loader import CorpusIndex

logger = logging.getLogger(__name__)

_MAX_READ_CHARS = 20_000
_GREP_CONTEXT = 2


def make_corpus_tools(
    corpus: CorpusIndex,
    *,
    embed_cache: str | Path,
    text_cache_dir: str | Path,
    model_name: str = "BAAI/bge-m3",
) -> list[Any]:
    """构造 [semantic_search, keyword_search, read_doc]。"""
    from langchain_core.tools import tool

    state: dict[str, Any] = {"embedder": None, "ids": None, "mat": None}

    def _ensure_embed() -> None:
        if state["mat"] is None:
            from agentic_studio.infra.corpus.embed import Embedder, build_or_load_matrix

            state["embedder"] = Embedder(model_name)
            state["ids"], state["mat"] = build_or_load_matrix(
                corpus, state["embedder"], embed_cache
            )

    @tool
    def semantic_search(query: str, top_k: int = 8) -> str:
        """跨语言语义检索：发现与 query 相关的文档（中文查询可召回英文论文）。

        返回 top_k 条 `[分数] id — 标题 …` + 摘要片段。拿到 doc_id 后用 read_doc 读原文再下论断。
        """
        from agentic_studio.infra.corpus.embed import cosine_topk

        try:
            _ensure_embed()
            qv = state["embedder"].encode([query])[0]
        except Exception as exc:  # noqa: BLE001
            return f"语义检索不可用（{type(exc).__name__}）：{exc}"
        hits = cosine_topk(qv, state["mat"], int(top_k))
        out: list[str] = []
        for i, score in hits:
            e = corpus.entries[state["ids"][i]]
            out.append(f"[{score:.3f}] {e.row()}")
            if e.abstract:
                out.append("   " + e.abstract[:240].replace("\n", " "))
        return "\n".join(out) if out else f"无结果：{query}"

    @tool
    def keyword_search(query: str, top_k: int = 10) -> str:
        """精确关键词检索（FTS over 题目/关键词/作者/摘要），按命中数→IF→引用排序。

        适合作者名 / 专有术语 / 已知短语的精确命中；语义模糊检索用 semantic_search。
        """
        terms = [t for t in re.split(r"\s+", query.strip().lower()) if t]
        if not terms:
            return "错误：query 为空。"
        scored: list[tuple[int, float, int, Any]] = []
        for e in corpus.all():
            hay = " ".join(
                [e.title, " ".join(e.keywords), " ".join(e.authors), e.abstract]
            ).lower()
            matches = sum(1 for t in terms if t in hay)
            if matches:
                scored.append((matches, e.impact_factor or 0.0, e.cited or 0, e))
        if not scored:
            return f"无命中：{query}（试试 semantic_search 做语义召回）"
        scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        return "\n".join(e.row() for *_rest, e in scored[: int(top_k)])

    @tool
    def read_doc(doc_id: str, grep: str | None = None) -> str:
        """读一篇文档的原文（content_path→Docling 全文，缓存）。grep 给定时只返回匹配行+上下文。

        archive-first：读到的内容是你下论断的依据；每条 claim 必须能追溯到这里读过的文档。
        """
        e = corpus.get(doc_id)
        if e is None:
            return f"未找到 doc_id={doc_id}。先用 semantic_search/keyword_search 拿到正确 id。"
        if not e.content_path:
            return f"{e.doc_id} 无内容路径（仅有摘要）。可引用其摘要，但读不到全文。"
        if not corpus.content_root:
            return "content_root 未配置（content_path 是相对路径），暂不能读原文；先用摘要。"

        text = _load_text(e, corpus.content_root, text_cache_dir)
        if text is None:
            return f"读取失败：{e.doc_id}（{e.content_path}）。"
        if grep:
            text = _grep(text, grep)
            if not text:
                return f"在 {e.doc_id} 全文里没找到 /{grep}/。"
        if len(text) > _MAX_READ_CHARS:
            text = text[:_MAX_READ_CHARS] + "\n…(已截断；用 grep 定位具体段落)"
        return text

    return [semantic_search, keyword_search, read_doc]


def _load_text(entry: Any, content_root: str, text_cache_dir: str | Path) -> str | None:
    """content_path → 文本（PDF 走 Docling，md/txt 直读）。按 doc_id 缓存解析结果。"""
    cache = Path(text_cache_dir) / f"{entry.doc_id}.md"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")

    src = Path(content_root) / entry.content_path
    if not src.exists():
        logger.warning("原文不存在：%s", src)
        return None

    try:
        if src.suffix.lower() in {".md", ".markdown", ".txt"}:
            text = src.read_text(encoding="utf-8", errors="replace")
        else:  # pdf / docx / … → Docling
            from docling.document_converter import DocumentConverter

            result = DocumentConverter().convert(str(src))
            text = result.document.export_to_markdown()
    except Exception as exc:  # noqa: BLE001
        logger.warning("解析失败 %s：%s", src, exc)
        return None

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


def _grep(text: str, pattern: str) -> str:
    """返回匹配行 + 上下文（regex，忽略大小写）。"""
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error:
        rx = re.compile(re.escape(pattern), re.IGNORECASE)
    lines = text.splitlines()
    keep: set[int] = set()
    for i, line in enumerate(lines):
        if rx.search(line):
            for j in range(max(0, i - _GREP_CONTEXT), min(len(lines), i + _GREP_CONTEXT + 1)):
                keep.add(j)
    if not keep:
        return ""
    out: list[str] = []
    prev = -1
    for i in sorted(keep):
        if prev != -1 and i > prev + 1:
            out.append("…")
        out.append(lines[i])
        prev = i
    return "\n".join(out)
