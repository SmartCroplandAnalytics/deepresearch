"""保真验证 verifier —— evidence↔源比对（架构 §8，探针验过：单 temp=0 优于重采样 ensemble）。

给 (claim, source) 判 supported / contradicted / not_mentioned；compute-only，不打语料。
"""

from __future__ import annotations

import json

from agentic_studio import prompts
from agentic_studio.infra.llm import get_chat_model

LABELS = ("supported", "contradicted", "not_mentioned")

VERIFY_SYS = prompts.load("verify_sys")


def _parse(text: str) -> tuple[str, str]:
    t = (text or "").strip().strip("`")
    if t.startswith("json"):
        t = t[4:]
    try:
        obj = json.loads(t[t.find("{") : t.rfind("}") + 1])
        lab = str(obj.get("label", "")).strip().lower()
        if lab in LABELS:
            return lab, str(obj.get("reason", ""))[:40]
    except Exception:
        pass
    low = (text or "").lower()
    for lab in LABELS:
        if lab in low:
            return lab, ""
    return "not_mentioned", "parse_failed"


class Verifier:
    """单 verifier（temp=0）。需要多裁判时另配视角多样的 verifier（§8，不是重采样）。"""

    def __init__(self, model_spec: str) -> None:
        self.model = get_chat_model(model_spec, temperature=0.0)

    def verify(self, claim: str, source: str) -> tuple[str, str]:
        user = f"【来源】\n{source}\n\n【论断】\n{claim}"
        try:
            resp = self.model.invoke([("system", VERIFY_SYS), ("human", user)])
            return _parse(getattr(resp, "content", str(resp)))
        except Exception as e:  # noqa: BLE001
            return "not_mentioned", f"error:{e}"[:40]
