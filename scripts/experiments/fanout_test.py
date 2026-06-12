"""递归 fan-out 测（架构 §7）：广任务 → 递归拆（fanout 的 fanout，深度封顶）→ 并行叶子研究
→ 分层确定性 merge → 共享证据池。看结构、并发、bridge（多 scope 命中）、耗时。

uv run python scripts/experiments/fanout_test.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from agentic_studio.infra.research.fanout import research_fanout  # noqa: E402
from agentic_studio.infra.research.md_corpus import MdNodeSearcher  # noqa: E402
from agentic_studio.infra.research.state import _IMP_RANK  # noqa: E402
from agentic_studio.infra.research.verify import Verifier  # noqa: E402

DOCS = "E:/Project/Tsaiyber/Agent Cutting-Edge R&D/agentic-research/test"
MODEL = "deepseek:deepseek-chat"
TASK = "三峡库区水文化资源的构成、代表性遗产、价值与保护利用现状"


def main() -> None:
    load_dotenv()
    print("加载三峡 md 书（embed 缓存命中）…")
    searcher = MdNodeSearcher(DOCS, tag="sanxia")
    verifier = Verifier(MODEL)
    print(f"节点 {len(searcher.ids)}。递归 fan-out 任务：{TASK}\n")

    def on_event(k: str, info: dict) -> None:
        print(f"[{k}] {info}")

    t0 = time.time()
    res = research_fanout(
        TASK, searcher, verifier, MODEL,
        max_depth=2, max_width=4, max_leaves=8, concurrency=3, leaf_max_turns=10,
        on_event=on_event,
    )
    dt = time.time() - t0

    pool = res["pool"]
    print(f"\n===== 汇总 =====")
    print(f"叶子数={res['leaf_count']}  证据节点={res['evidence_count']}  bridge(多scope命中)={res['bridges']}  耗时={dt:.0f}s")
    print("\n证据池（按重要性，前 15）：")
    for nid, p in sorted(pool.items(), key=lambda kv: (_IMP_RANK.get(kv[1]["importance"], 2), kv[0]))[:15]:
        ns = len(set(p["scopes"]))
        print(f"  {nid} <{p['importance']}> scope×{ns}: {p['title'][:60]}")


if __name__ == "__main__":
    main()
