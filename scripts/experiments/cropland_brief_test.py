"""端到端：耕地时空演变 plugin → grounded-write 简报（大纲 + scope schema + 安全取数）。

跑法（需 DEEPSEEK_API_KEY、可达的 smart_cropland_analytics 库；DSN 经 env CROPLAND_DSN；
plugin 声明了图表 → 需要 viz extra）：
  PYTHONUTF8=1 uv run --extra pg --extra viz python scripts/experiments/cropland_brief_test.py [scope_json]

例：只写第4章、限定成都 2020-2023：
  ... cropland_brief_test.py '{"regions":["成都市"],"years":[2020,2023],"sections":["4"]}'
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv  # noqa: E402

from agentic_studio.infra.research.verify import Verifier  # noqa: E402
from agentic_studio.workflows.grounded_brief import run_brief  # noqa: E402

PLUGIN = "agentic_studio/skills/cropland-spatiotemporal"
WORKSPACE = ".cache/cropland_brief"
MODEL = "deepseek:deepseek-chat"


def main() -> None:
    load_dotenv(".env")
    scope = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    verifier = Verifier(MODEL)  # in-loop 保真：核对正文论断是否真被 DB 证据支持

    def on_event(kind: str, a: dict) -> None:
        if kind == "section":
            print(f"[节] {a['id']} {a['title']}  证据×{a['evidence']}")
        elif kind == "section_done":
            print(f"   ✓ {a['id']}  {a.get('wc')}字  悬空={a.get('dangling')}  "
                  f"未着地数字={a.get('ungrounded')}")
        elif kind == "W:verify":
            print(f"     verify[{a.get('verdict')}] {a.get('claim', '')}")

    res = run_brief(PLUGIN, MODEL, WORKSPACE, scope=scope, verifier=verifier, on_event=on_event)
    print("\n===== 完成 =====")
    print({k: v for k, v in res.items() if k != "scope_dict"})
    mp = Path(res["manuscript_path"])
    print(f"\n----- {mp}（前 60 行）-----")
    print("\n".join(mp.read_text(encoding="utf-8").splitlines()[:60]))


if __name__ == "__main__":
    main()
