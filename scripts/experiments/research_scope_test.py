"""研究子环单 scope 端到端测（架构 §14.1）：给一个研究范围，跑 search→curate→verify→end，
看产出的精选证据是否相关、带 [node_id] 引用。验证 harness-1 式研究 agent 在真实语料上跑通。

uv run python scripts/experiments/research_scope_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from agentic_studio.infra.research.loop import run_research_scope  # noqa: E402
from agentic_studio.infra.research.search import CorpusSearcher  # noqa: E402
from agentic_studio.infra.research.verify import Verifier  # noqa: E402

CARDS = "E:/WorkSpace/堰塞湖专著/洪水预测篇/index/cards.json"
ABSTRACTS = "E:/WorkSpace/堰塞湖专著/洪水预测篇/index/abstracts.json"
SCOPE = "堰塞体溃决机理物理试验：上游来流量、库容、坝高、密实度、下游坡度、筑坝材料级配对溃口水位/流量/溃口宽度过程的影响"
MODEL = "deepseek:deepseek-chat"


def main() -> None:
    load_dotenv()
    print("加载语料 + bge-m3 矩阵（首次会 embed，~90s）…")
    searcher = CorpusSearcher(CARDS, ABSTRACTS, embed_cache=".cache/embed/research_corpus.npz")
    verifier = Verifier(MODEL)
    print(f"语料 {len(searcher.ids)} 节点。开跑研究循环。\n范围：{SCOPE}\n")

    def on_event(tool: str, args: dict) -> None:
        a = {k: (v if not isinstance(v, str) or len(v) < 60 else v[:60] + "…") for k, v in args.items()}
        print(f"[T] {tool} {a}")

    wm = run_research_scope(SCOPE, searcher, verifier, MODEL, max_turns=14, on_event=on_event)

    print("\n===== 最终工作记忆 =====")
    print(wm.to_text())
    print("\n===== 导出证据 =====")
    print(wm.export_evidence())
    print(f"\n精选证据 doc_ids（{len(wm.evidence_doc_ids())}）：{wm.evidence_doc_ids()}")


if __name__ == "__main__":
    main()
