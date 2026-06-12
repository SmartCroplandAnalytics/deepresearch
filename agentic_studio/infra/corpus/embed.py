"""bge-m3 语义检索 —— 文档级 Hop-0 召回（架构 §9）。

跨语言（中↔英）：中文查询召回英文论文。一次性 embed 摘要、落盘缓存(.npz)；查询
encode + cosine（normalize 后 = 点积），flat 矩阵、不需向量 DB（2568×1024 ≈ 10MB / 亚秒）。
bge-m3 经 sentence-transformers（torch），重依赖 → [embed] extra。
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentic_studio.infra.corpus.loader import CorpusIndex

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-m3"


class Embedder:
    """bge-m3 编码器（normalize 输出，cosine = 点积）。"""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        if device is None:  # 自动选 GPU；CUDA 不可用退 CPU
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:  # noqa: BLE001
                device = "cpu"
        self.model_name = model_name
        self.device = device
        logger.info("bge-m3 加载于 %s", device)
        self._model = SentenceTransformer(model_name, device=device)

    def encode(self, texts: list[str], batch_size: int = 32) -> Any:
        import numpy as np

        vecs = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 64,
        )
        return np.asarray(vecs, dtype="float32")


def _fingerprint(ids: list[str], model_name: str) -> str:
    h = hashlib.sha256(("\n".join(ids) + "::" + model_name).encode("utf-8")).hexdigest()
    return h[:16]


def build_or_load_matrix(
    corpus: CorpusIndex, embedder: Embedder, cache_path: str | Path
) -> tuple[list[str], Any]:
    """返回 (ids, matrix[N,d] normalized)。命中缓存(同 ids+模型)直接 load，否则 embed 并存。"""
    import numpy as np

    ids = [e.doc_id for e in corpus.all() if e.embed_text().strip()]
    fp = _fingerprint(ids, embedder.model_name)
    cache = Path(cache_path)

    if cache.exists():
        try:
            data = np.load(cache, allow_pickle=True)
            if str(data["fp"]) == fp:
                logger.info("embedding 缓存命中：%s", cache)
                return list(data["ids"]), data["vectors"]
            logger.info("embedding 缓存失效（ids/模型变了），重算")
        except Exception as exc:  # noqa: BLE001
            logger.warning("读 embedding 缓存失败（%s），重算", exc)

    texts = [corpus.entries[i].embed_text() for i in ids]
    logger.info("embedding %d 条摘要（bge-m3）…", len(texts))
    mat = embedder.encode(texts)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, ids=np.array(ids, dtype=object), vectors=mat, fp=np.array(fp))
    return ids, mat


def cosine_topk(qvec: Any, matrix: Any, k: int) -> list[tuple[int, float]]:
    """matrix 与 qvec 均已 normalize → 点积即 cosine。返回 [(行号, 分数)]。"""
    import numpy as np

    scores = matrix @ qvec
    idx = np.argsort(-scores)[: max(1, k)]
    return [(int(i), float(scores[i])) for i in idx]


def mmr_topk(
    qvec: Any, matrix: Any, k: int, *, pool: int = 40, lam: float = 0.5
) -> list[tuple[int, float]]:
    """MMR：在相似度前 pool 个候选里贪心选 k 个，最大化 (lam·相关 − (1−lam)·与已选最大冗余)。
    用于"发散"——给 planner 看语料的**广度代表**，而非塌向中心的 top-K（§7.1）。
    """
    import numpy as np

    scores = matrix @ qvec
    cand = list(np.argsort(-scores)[: max(k, pool)])
    selected: list[int] = []
    while cand and len(selected) < k:
        if not selected:
            best = cand[0]  # 候选已按 score 降序 → 先取最相关
        else:
            sel = matrix[selected]  # [s, d]
            best, best_val = cand[0], -1e9
            for r in cand:
                red = float(np.max(sel @ matrix[r]))  # 与已选的最大相似（冗余）
                val = lam * float(scores[r]) - (1.0 - lam) * red
                if val > best_val:
                    best_val, best = val, r
        selected.append(int(best))
        cand.remove(best)
    return [(int(r), float(scores[r])) for r in selected]
