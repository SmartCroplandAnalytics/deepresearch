"""infra/corpus —— 已索引本地语料的检索层（架构 §8/§9）。

适配用户已有索引（不重建）：load_card_index 消费 cards.json + abstracts.json → CorpusIndex。
检索三粒度（§9）：semantic_search（bge-m3 跨语言召回）/ keyword_search（精确 FTS）/
read_doc（content_path→Docling 全文 + 文内 grep）。bge-m3 / Docling 是重依赖，故落 infra。
"""

from agentic_studio.infra.corpus.loader import (
    CorpusIndex,
    build_entity_index,
    dump_index_files,
    load_card_index,
)
from agentic_studio.infra.corpus.tools import make_corpus_tools

__all__ = [
    "CorpusIndex",
    "load_card_index",
    "build_entity_index",
    "dump_index_files",
    "make_corpus_tools",
]
