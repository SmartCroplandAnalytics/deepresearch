"""grounded-write v0 端到端测（架构 §6）：2 节 → 研究→写作→assemble → 带 [N] 引用的成稿。"""

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

from agentic_studio.infra.research.search import CorpusSearcher  # noqa: E402
from agentic_studio.infra.research.verify import Verifier  # noqa: E402
from agentic_studio.workflows.grounded_write import generate_v0  # noqa: E402

CARDS = "E:/WorkSpace/堰塞湖专著/洪水预测篇/index/cards.json"
ABSTRACTS = "E:/WorkSpace/堰塞湖专著/洪水预测篇/index/abstracts.json"
MODEL = "deepseek:deepseek-chat"
WS = ".cache/gw_v0_test"

SECTIONS = [
    {"id": "3.2", "title": "堰塞体溃决机理物理试验",
     "content": "从库容、背水面坡度、筑坝材料级配等参数阐述其对溃口流量过程与溃决历时的影响",
     "key_question": "库容、坡度、级配如何影响溃口峰值流量与溃决历时？", "word_count": 600},
    {"id": "3.3", "title": "人工干预下堰塞湖溃决过程与效果",
     "content": "开挖引流槽断面与纵剖面型式、石笼串与防护网等防护措施对溃决过程与峰值流量的影响",
     "key_question": "引流槽与防护措施如何改变溃决过程与峰值流量？", "word_count": 600},
]

MILESTONES = {"research_start", "R:end_search", "write_start", "W:expand", "W:verify", "W:done", "section_done"}


def main() -> None:
    load_dotenv()
    print("加载语料 + 矩阵…")
    searcher = CorpusSearcher(CARDS, ABSTRACTS, embed_cache=".cache/embed/research_corpus.npz")
    verifier = Verifier(MODEL)
    print(f"语料 {len(searcher.ids)} 节点。生成 v0（{len(SECTIONS)} 节）。\n")

    def on_event(kind: str, info: dict) -> None:
        if kind in MILESTONES:
            print(f"[{kind}] {info}")

    res = generate_v0(SECTIONS, searcher, verifier, MODEL, WS, on_event=on_event)

    print("\n========== 成稿 manuscript.md ==========\n")
    print(Path(res["manuscript_path"]).read_text(encoding="utf-8"))
    print("\n========== 判断队列 ==========\n")
    print((Path(WS) / "judgment_queue.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
