"""规模测：2568 篇洪水语料上的递归 fan-out（架构 §7）。广任务 → 递归拆（广度均分预算）
→ 并行多 agent 研究 → 确定性合并 → 大共享证据池。看叶子数/池规模/bridge/墙钟。

uv run python scripts/experiments/fanout_scale_test.py
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from agentic_studio.infra.research.fanout import research_fanout  # noqa: E402
from agentic_studio.infra.research.search import CorpusSearcher  # noqa: E402
from agentic_studio.infra.research.state import _IMP_RANK  # noqa: E402
from agentic_studio.infra.research.verify import Verifier  # noqa: E402

CARDS = "E:/WorkSpace/堰塞湖专著/洪水预测篇/index/cards.json"
ABSTRACTS = "E:/WorkSpace/堰塞湖专著/洪水预测篇/index/abstracts.json"
MODEL = "deepseek:deepseek-chat"
TASK = "堰塞湖溃决洪水预测：溃决机理与物理试验、溃口流量过程预测（经验/简化/水沙耦合模型）、溃决洪水沿程演进与实时预报"


def main() -> None:
    load_dotenv()
    print("加载 2568 篇语料 + 矩阵（缓存命中）…")
    searcher = CorpusSearcher(CARDS, ABSTRACTS, embed_cache=".cache/embed/research_corpus.npz")
    verifier = Verifier(MODEL)
    print(f"语料 {len(searcher.ids)} 篇。规模递归 fan-out：{TASK}\n")

    def on_event(k: str, info: dict) -> None:
        print(f"[{k}] {info}")

    t0 = time.time()
    res = research_fanout(
        TASK, searcher, verifier, MODEL,
        max_depth=2, max_width=5, max_leaves=18, concurrency=6, leaf_max_turns=10,
        workspace=".cache/fanout_scale", on_event=on_event,
    )
    dt = time.time() - t0

    pool = res["pool"]
    print("\n===== 规模汇总 =====")
    print(f"叶子(并行研究 agent)={res['leaf_count']}  去重证据={res['evidence_count']}  "
          f"bridge(多scope命中)={res['bridges']}  墙钟={dt:.0f}s")
    imp = Counter(p["importance"] for p in pool.values())
    print(f"证据重要性分布：{dict(imp)}")
    print("\n最中心证据（bridge×scope 数，前 12）：")
    for nid, p in sorted(pool.items(), key=lambda kv: -len(set(kv[1]["scopes"])))[:12]:
        print(f"  {nid} <{p['importance']}> scope×{len(set(p['scopes']))}: {p['title'][:50]}")


if __name__ == "__main__":
    main()
