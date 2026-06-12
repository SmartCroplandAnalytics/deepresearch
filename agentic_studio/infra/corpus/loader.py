"""消费用户已有索引（cards.json + abstracts.json）→ CorpusIndex（不重建）。

- cards.json：list，每条含 id/title/authors/year/venue/keywords/IF/cited/doi/issn/pdf_path 等。
- abstracts.json：dict，id → 摘要。
- entity_index：keywords[] 聚合的关键词倒排（纯 keyword、零 embedding，跨跳用）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agentic_studio.core.index import IndexEntry


@dataclass
class CorpusIndex:
    """一份已加载的语料索引（条目 + 关键词倒排 + 内容根）。"""

    entries: dict[str, IndexEntry]
    order: list[str]                              # 保留原始顺序
    entity_index: dict[str, list[str]] = field(default_factory=dict)  # keyword(lower)→[doc_id]
    content_root: str | None = None              # content_path 相对的根（可后配）

    def get(self, doc_id: str) -> IndexEntry | None:
        if doc_id in self.entries:
            return self.entries[doc_id]
        for did in self.entries:                 # 前缀容错
            if did.startswith(doc_id) or doc_id.startswith(did):
                return self.entries[did]
        return None

    def all(self) -> list[IndexEntry]:
        return [self.entries[d] for d in self.order]


def build_entity_index(entries: dict[str, IndexEntry]) -> dict[str, list[str]]:
    """keyword(小写) → [doc_id]，按出现顺序去重。"""
    idx: dict[str, list[str]] = {}
    for did, e in entries.items():
        for kw in e.keywords:
            k = (kw or "").strip().lower()
            if not k:
                continue
            bucket = idx.setdefault(k, [])
            if did not in bucket:
                bucket.append(did)
    return idx


def load_card_index(
    cards_path: str | Path,
    abstracts_path: str | Path | None = None,
    content_root: str | None = None,
) -> CorpusIndex:
    """读用户的 cards.json(+abstracts.json) → CorpusIndex。"""
    cards = json.loads(Path(cards_path).read_text(encoding="utf-8"))
    abstracts: dict[str, str] = {}
    if abstracts_path and Path(abstracts_path).exists():
        abstracts = json.loads(Path(abstracts_path).read_text(encoding="utf-8"))

    entries: dict[str, IndexEntry] = {}
    order: list[str] = []
    known = {
        "id", "title", "authors", "year", "venue", "keywords",
        "impact_factor", "cited_oa", "cited_crossref", "doi", "issn", "pdf_path", "abstract",
    }
    for c in cards:
        did = str(c.get("id") or "").strip()
        if not did:
            continue
        pdf = c.get("pdf_path")
        entries[did] = IndexEntry(
            doc_id=did,
            title=c.get("title") or "",
            authors=list(c.get("authors") or []),
            year=c.get("year"),
            abstract=abstracts.get(did) or c.get("abstract") or "",
            venue=c.get("venue"),
            keywords=list(c.get("keywords") or []),
            doi=c.get("doi"),
            issn=list(c.get("issn") or []),
            impact_factor=c.get("impact_factor"),
            cited=c.get("cited_oa") if c.get("cited_oa") is not None else c.get("cited_crossref"),
            content_path=pdf,
            content_kind="pdf" if pdf else None,
            extra={k: v for k, v in c.items() if k not in known},
        )
        order.append(did)

    return CorpusIndex(
        entries=entries,
        order=order,
        entity_index=build_entity_index(entries),
        content_root=content_root,
    )


def dump_index_files(corpus: CorpusIndex, out_dir: str | Path) -> dict[str, Path]:
    """把语料落成两份 grep 友好产物（挂 VFS 给 agent 用，§9 Corpus2Skill 导航）：
    - INDEX.md：每行一条目（行三角定位）
    - entity_index.json：keyword→[doc_id]（跨跳）
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [f"# Corpus index ({len(corpus.order)} docs)", ""]
    rows += [f"- {e.row()}" for e in corpus.all()]
    index_md = out / "INDEX.md"
    index_md.write_text("\n".join(rows), encoding="utf-8")

    entity_json = out / "entity_index.json"
    entity_json.write_text(
        json.dumps(corpus.entity_index, ensure_ascii=False, indent=0), encoding="utf-8"
    )
    return {"index_md": index_md, "entity_index": entity_json}
