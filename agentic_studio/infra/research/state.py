"""研究子环的外置状态 —— WorkingMemory（架构 §14.1，参照 harness-1 ultra_core.py）。

两层记忆：
- 内层（进上下文）：紧凑文本 = 精选集 + 候选池 snippet + 检索史。
- 外层（doc_store）：节点全文，`review()` 零成本重读，不再打语料。

精选集（curated）= 喂写作闭环的证据：带上限 + 重要性标签 + 减法淘汰。
node_id = 检索单位（论文 = doc_id；大文档的节 = doc_id#sec，§13.1，MVP 先用 doc_id）。

纯 Python（无 torch/mirage 依赖），便于独立测与序列化。
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_CURATED = 30
SNIPPET_CHARS = 160
POOL_DISPLAY = 40  # to_text 里展示的未精选节上限（最近优先）

IMPORTANCE = ("very_high", "high", "fair", "low")
_IMP_RANK = {"very_high": 0, "high": 1, "fair": 2, "low": 3}


@dataclass
class Node:
    """一个检索到的节点（论文 / 大文档的一节）。"""

    node_id: str
    title: str = ""
    full_text: str = ""
    source: str = ""  # 来源标记：doc_id / url / db:table ...
    meta: dict = field(default_factory=dict)

    @property
    def snippet(self) -> str:
        return self.full_text[:SNIPPET_CHARS].replace("\n", " ").strip()


class WorkingMemory:
    """研究子 agent 的可恢复状态（harness 持有，policy 只做语义决策）。"""

    def __init__(self, scope: str, max_curated: int = MAX_CURATED) -> None:
        self.scope = scope  # 本研究节点的问题 / 范围
        self.max_curated = max_curated
        self.turn = 0
        self.doc_store: dict[str, Node] = {}          # node_id → Node（外层全文）
        self.pool_ids: list[str] = []                  # 候选池（按发现顺序）
        self.curated_ids: list[str] = []               # 精选集（喂写作的证据）
        self.curated_importance: dict[str, str] = {}
        self.curated_notes: dict[str, str] = {}        # node_id → 它支撑什么 / 为何选
        self.search_history: list[str] = []
        self.verified: dict[str, dict] = {}            # node_id → {claim, verdict, reason}

    # ── 池（pool）────────────────────────────────────────────────
    def add_to_pool(self, nodes: list[Node]) -> int:
        """加入候选池 + 全文外存。返回新增数。"""
        added = 0
        for n in nodes:
            if n.node_id not in self.doc_store:
                self.doc_store[n.node_id] = n
            if n.node_id not in self.pool_ids:
                self.pool_ids.append(n.node_id)
                added += 1
        return added

    def review(self, node_ids: list[str], limit: int = 5) -> str:
        """从外层取全文重读（零成本，不打语料）。"""
        parts = []
        for nid in node_ids[:limit]:
            n = self.doc_store.get(nid)
            parts.append(
                f"# {nid} — {n.title}\n{n.full_text}" if n else f"# {nid}\n(不在记忆中)"
            )
        return "\n\n".join(parts) if parts else "记忆中无匹配节点。"

    # ── 精选集（curate）─────────────────────────────────────────
    def curate(
        self,
        add: list[str],
        remove: list[str] | None = None,
        importance: dict[str, str] | None = None,
        notes: dict[str, str] | None = None,
    ) -> str:
        """更新精选集；满了按最低重要性减法淘汰。返回状态串（带容量反馈）。"""
        remove = remove or []
        importance = {k: (v if v in IMPORTANCE else "fair") for k, v in (importance or {}).items()}
        notes = notes or {}

        for rid in remove:
            if rid in self.curated_ids:
                self.curated_ids.remove(rid)
                self.curated_importance.pop(rid, None)
                self.curated_notes.pop(rid, None)

        evicted: list[str] = []
        dropped: list[str] = []
        for nid in add:
            if nid in self.curated_ids:
                if nid in importance:
                    self.curated_importance[nid] = importance[nid]
                if nid in notes:
                    self.curated_notes[nid] = notes[nid]
                continue
            tag = importance.get(nid, "fair")
            if len(self.curated_ids) < self.max_curated:
                self._add_curated(nid, tag, notes.get(nid, ""))
                continue
            # 满了：找最低重要性的，若比新来的低则淘汰
            worst = max(self.curated_ids, key=lambda c: _IMP_RANK.get(self.curated_importance.get(c, "fair"), 2))
            if _IMP_RANK.get(self.curated_importance.get(worst, "fair"), 2) > _IMP_RANK.get(tag, 2):
                self.curated_ids.remove(worst)
                self.curated_importance.pop(worst, None)
                self.curated_notes.pop(worst, None)
                evicted.append(worst)
                self._add_curated(nid, tag, notes.get(nid, ""))
            else:
                dropped.append(nid)

        msg = f"精选集 {len(self.curated_ids)}/{self.max_curated}"
        if evicted:
            msg += f"；淘汰低重要性 {len(evicted)}：{', '.join(evicted[:5])}"
        if dropped:
            msg += f"；已满且无可淘汰，{len(dropped)} 个未加入：{', '.join(dropped[:5])}"
        return msg

    def _add_curated(self, nid: str, tag: str, note: str) -> None:
        self.curated_ids.append(nid)
        self.curated_importance[nid] = tag
        if note:
            self.curated_notes[nid] = note

    def record_verify(self, node_id: str, claim: str, verdict: str, reason: str = "") -> None:
        self.verified[node_id] = {"claim": claim, "verdict": verdict, "reason": reason}

    def add_search_record(self, tool: str, query: str, n_results: int, n_new: int) -> None:
        self.search_history.append(f"T{self.turn}: {tool}({query}) → {n_results} 命中, {n_new} 新")

    def advance(self) -> None:
        self.turn += 1

    # ── 两层记忆的内层渲染 ───────────────────────────────────────
    def to_text(self) -> str:
        lines = [f'== 工作记忆 (turn 0-{self.turn}) ==', f'研究范围: "{self.scope}"', ""]
        lines.append(f"精选集 ({len(self.curated_ids)}/{self.max_curated})：")
        if self.curated_ids:
            for nid in sorted(self.curated_ids, key=lambda c: _IMP_RANK.get(self.curated_importance.get(c, "fair"), 2)):
                tag = self.curated_importance.get(nid, "fair")
                note = self.curated_notes.get(nid, "")
                vd = self.verified.get(nid, {}).get("verdict")
                vtag = f" [verify:{vd}]" if vd else ""
                note_s = f" — {note}" if note else ""
                lines.append(f"  [*] {nid} <{tag}>{vtag}: {self.doc_store.get(nid, Node(nid)).snippet}{note_s}")
        else:
            lines.append("  (空 — 用 curate 加入相关节点)")
        lines.append("")

        uncurated = [p for p in self.pool_ids if p not in set(self.curated_ids)]
        lines.append(f"候选池：共 {len(self.pool_ids)}，未精选 {len(uncurated)}")
        for nid in reversed(uncurated[-POOL_DISPLAY:]):
            lines.append(f"  [ ] {nid}: {self.doc_store.get(nid, Node(nid)).snippet}")
        if len(uncurated) > POOL_DISPLAY:
            lines.append(f"  …更早未精选 {len(uncurated) - POOL_DISPLAY} 个（用 review 重读）")
        lines.append("")

        if self.search_history:
            lines.append("检索史：")
            lines += [f"  {e}" for e in self.search_history[-12:]]
        return "\n".join(lines)

    # ── 导出为证据（喂写作闭环；落 evidence/<scope>.md）──────────
    def export_evidence(self) -> str:
        """精选集 → 带 [node_id] 引用的证据 markdown（§11 evidence/<scope>.md）。"""
        out = [f"# 证据 · {self.scope}", ""]
        order = sorted(self.curated_ids, key=lambda c: _IMP_RANK.get(self.curated_importance.get(c, "fair"), 2))
        for nid in order:
            n = self.doc_store.get(nid, Node(nid))
            tag = self.curated_importance.get(nid, "fair")
            note = self.curated_notes.get(nid, "")
            vd = self.verified.get(nid, {})
            out.append(f"## [{nid}] {n.title}  <{tag}>")
            if note:
                out.append(f"- 支撑：{note}")
            if vd:
                out.append(f"- 保真：{vd.get('verdict')}（{vd.get('claim','')}）")
            if n.source:
                out.append(f"- 来源：{n.source}")
            out.append("")
        return "\n".join(out)

    def evidence_doc_ids(self) -> list[str]:
        """精选证据涉及的 doc_id（供 assemble 引用重编号 / manifest）。"""
        return list(self.curated_ids)
