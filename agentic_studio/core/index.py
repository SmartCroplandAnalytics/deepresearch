"""IndexEntry —— 已索引语料的一条目（架构 §8 索引层 / §9 检索层的运行期对象）。

替代早期叫法 "Card"：这是**最简、语料无关**的索引条目——核心只有
题目 / 作者 / 年份 / 摘要；学术论文再带可选元数据（venue/keywords/IF/DOI…）。
`content_path` 由索引给出（相对 content_root，root 单独配置）。

注：很长的文档（书）仅文档级条目可能不够，需篇内细粒度索引——留待未来。
Corpus2Skill 风格的富 doc-card / 聚类树是另一个（更重）概念，见 core.card 与 §14.4。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IndexEntry(BaseModel):
    """语料索引里的一条文档条目。"""

    doc_id: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str = ""

    # —— 学术/富元数据（通用语料可空）——
    venue: str | None = None
    keywords: list[str] = Field(default_factory=list)
    doi: str | None = None
    issn: list[str] = Field(default_factory=list)
    impact_factor: float | None = None
    cited: int | None = None

    # —— 定位原文（路径由索引给出；相对 content_root）——
    content_path: str | None = None
    content_kind: str | None = None  # "pdf" / "md" / "txt" …

    extra: dict[str, Any] = Field(default_factory=dict)  # 源索引里其余字段，原样保留

    def embed_text(self) -> str:
        """用于 embedding 的文本：题目 + 摘要（缺摘要退到题目）。"""
        parts = [self.title.strip(), self.abstract.strip()]
        return "\n".join(p for p in parts if p) or self.title or self.doc_id

    def row(self) -> str:
        """grep 友好的一行（行三角定位用）。"""
        meta = []
        if self.year:
            meta.append(str(self.year))
        if self.venue:
            meta.append(self.venue)
        if self.impact_factor is not None:
            meta.append(f"IF={self.impact_factor}")
        if self.cited is not None:
            meta.append(f"cited={self.cited}")
        kw = "; ".join(self.keywords[:8])
        author = ", ".join(self.authors[:3]) + ("…" if len(self.authors) > 3 else "")
        head = f"`{self.doc_id}` — {self.title}"
        tail = " — ".join(x for x in [author, " ".join(meta), f"[{kw}]" if kw else ""] if x)
        return f"{head} — {tail}" if tail else head
