"""编排级测试：run_brief / revise / 修复环 / 韧性 / 溯源（假 provider+假模型，零网络）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentic_studio.core.judgment import JudgmentItem
from agentic_studio.infra.data.providers import ProviderSet
from agentic_studio.infra.writing import compose as compose_mod
from agentic_studio.workflows import grounded_brief as gb

EV_TEXT = "甲省X指标（万亩）历年：2020年 486.47万亩；2023年 499.60万亩。"


class FSeries:
    kind = "fseries"
    fanout_keys = ("region",)

    def gather(self, spec):
        return [{"id": "E1", "title": f"{spec.get('region')}X指标", "text": EV_TEXT,
                 "importance": "very_high", "source": "fake:X"}]

    def lint(self, spec):
        return None


class FEmpty(FSeries):
    kind = "fempty"

    def gather(self, spec):
        return []


class FBoom(FSeries):
    kind = "fboom"

    def gather(self, spec):
        raise RuntimeError("db down")


class FTab:
    kind = "ftab"

    def render(self, spec, *, ws, sid, idx):
        from agentic_studio.infra.writing.artifacts import TAB_TOKEN, md_table

        return f"**{TAB_TOKEN}：假表**\n\n" + md_table(["a"], [["1"]]), "假表"

    def lint(self, spec):
        return None


class FFig:
    kind = "ffig"

    def render(self, spec, *, ws, sid, idx):
        from agentic_studio.infra.writing.artifacts import FIG_TOKEN

        return f"![假图](figures/x.png)\n\n*{FIG_TOKEN}：假图*", "假图"

    def lint(self, spec):
        return None


def _pset() -> ProviderSet:
    return ProviderSet(
        providers={"fseries": FSeries(), "fempty": FEmpty(), "fboom": FBoom()},
        renderers={"ftab": FTab(), "ffig": FFig()},
        validators={"region": lambda v: None if v in ("甲省", "乙市") else "未知地区"},
    )


class GroundedModel:
    """内容感知假模型：从提示里取证据 id 和数字写一句有据正文（恒过确定性检查）。"""

    def invoke(self, msgs):
        user = msgs[-1][1]
        nid = re.search(r"\[(\w+)\]<", user).group(1)
        num = re.search(r"(\d+\.\d+)", user).group(1)
        return SimpleNamespace(content=f"期初2020年为{num}万亩 [{nid}]。")


class ScriptedModel:
    """脚本化假模型：依次返回预置输出（测修复环等多轮交互）。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)

    def invoke(self, msgs):
        return SimpleNamespace(content=self.outputs.pop(0))


class BoomModel:
    def invoke(self, msgs):
        raise RuntimeError("llm down")


OUTLINE = """\
title: 测试简报
language: 中文
scope:
  label: "$regions"
  params:
    regions: {type: list_str, default: ["甲省"], check: region, desc: 地区}
sections:
  - id: "1"
    title: 主体
    children:
      - id: "1.1"
        title: 总体
        key_question: 怎么变？
        evidence:
          - {kind: fseries, code: X, region: $regions}
        figures:
          - {kind: ffig}
        tables:
          - {kind: ftab}
  - id: "2"
    title: 边角
    children:
      - id: "2.1"
        title: 缺口
        data_gap: 缺人口数据
        evidence: []
      - id: "2.2"
        title: 可选下钻
        optional: true
        evidence:
          - {kind: fempty, code: X}
      - id: "2.3"
        title: 故障源
        evidence:
          - {kind: fboom, code: X}
"""


@pytest.fixture
def plugin_dir(tmp_path: Path) -> str:
    d = tmp_path / "test-plugin"
    d.mkdir()
    (d / "outline.yaml").write_text(OUTLINE, encoding="utf-8")
    return str(d)


def test_run_brief_end_to_end(plugin_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(compose_mod, "get_chat_model", lambda *a, **k: GroundedModel())
    ws = str(tmp_path / "ws")
    res = gb.run_brief(plugin_dir, "fake:model", ws,
                       scope={"regions": ["乙市"]}, provider_set=_pset(), parallel=1)

    assert res["scope"] == "乙市"
    assert res["skipped"] == ["2.2"]          # optional + 无证据 → 跳过
    assert res["errors"] == []
    assert res["sections"] == 3               # 1.1 ok + 2.1 gap + 2.3 gap(取数失败)
    m = Path(res["manuscript_path"]).read_text(encoding="utf-8")
    assert "486.47万亩 [1]" in m              # 重编号 + 有据数字
    assert "缺人口数据" in m                  # 声明的 data_gap
    assert "取数失败 RuntimeError" in str(res["gaps"])  # 数据源故障降级为缺口，不炸全篇
    # 确定性图表：入稿 + 装配时全局编号（图在前表在后）
    assert "*图1：假图*" in m and "**表1：假表**" in m

    # 证据全文快照 + 溯源元数据
    manifest = json.loads((Path(ws) / "evidence" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["E1"]["text"] == EV_TEXT
    state = json.loads((Path(ws) / gb.STATE_FILE).read_text(encoding="utf-8"))
    run = state["run"]
    assert run["model"] == "fake:model"
    assert re.fullmatch(r"[0-9a-f]{8}", run["prompts_fingerprint"])
    assert run["started"] <= run["finished"]
    assert state["scope"] == {"regions": ["乙市"], "sections": []}
    # state 保留编号占位 token（重装配/修订时全局编号始终一致）
    sec11 = next(s for s in state["sections"] if s["id"] == "1.1")
    assert "[[图]]" in sec11["text"] and "[[表]]" in sec11["text"]


def test_run_brief_section_llm_failure_degrades(plugin_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(compose_mod, "get_chat_model", lambda *a, **k: BoomModel())
    ws = str(tmp_path / "ws2")
    res = gb.run_brief(plugin_dir, "fake:model", ws,
                       scope={"regions": ["甲省"]}, provider_set=_pset(), parallel=1)
    assert res["errors"] == ["1.1"]           # LLM 故障：单节降级，不炸全篇
    m = Path(res["manuscript_path"]).read_text(encoding="utf-8")
    assert "本节生成失败" in m


def test_revise_section_supersedes_old_items(plugin_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(compose_mod, "get_chat_model", lambda *a, **k: GroundedModel())
    ws = str(tmp_path / "ws3")
    gb.run_brief(plugin_dir, "fake:model", ws,
                 scope={"regions": ["甲省"]}, provider_set=_pset(), parallel=1)
    # 种一条旧 open 判断项（指向 1.1 旧文本）
    gb._write_queue(Path(ws), [JudgmentItem.make("contradiction", "1.1", "旧文本的问题")],
                    merge=True)

    monkeypatch.setattr(
        compose_mod, "get_chat_model",
        lambda *a, **k: ScriptedModel(["修订后：期末2023年为499.60万亩 [E1]。"]),
    )
    res = gb.revise_section(plugin_dir, ws, "1.1", "改成期末口径", "fake:model",
                            provider_set=_pset())
    assert res["ok"] and res["ungrounded_numbers"] == 0
    assert "499.60" in Path(res["manuscript_path"]).read_text(encoding="utf-8")
    # 旧 open 项 → superseded；状态盖了修订时间戳
    all_items = gb.load_queue(ws, only_open=False)
    old = next(d for d in all_items if d["detail"] == "旧文本的问题")
    assert old["status"] == "superseded"
    state = json.loads((Path(ws) / gb.STATE_FILE).read_text(encoding="utf-8"))
    assert "revised" in state["run"]


def test_revise_rejects_wrong_plugin(plugin_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(compose_mod, "get_chat_model", lambda *a, **k: GroundedModel())
    ws = str(tmp_path / "ws4")
    gb.run_brief(plugin_dir, "fake:model", ws,
                 scope={"regions": ["甲省"]}, provider_set=_pset(), parallel=1)
    other = tmp_path / "other-plugin"
    other.mkdir()
    (other / "outline.yaml").write_text(OUTLINE, encoding="utf-8")
    with pytest.raises(ValueError, match="不能用"):
        gb.revise_section(str(other), ws, "1.1", "x", "fake:model", provider_set=_pset())


EVID = [{"id": "E1", "title": "甲省X", "text": EV_TEXT, "importance": "very_high",
         "source": "fake:X"}]
_SEC = {"id": "t", "title": "测", "content": "", "key_question": "", "word_count": 0}


def test_write_section_repair_loop_fixes_violation(monkeypatch):
    fake = ScriptedModel(["高达999.99万亩 [E1]。",          # compose：编造数字
                          "期初2020年为486.47万亩 [E1]。"])  # repair：改回证据数字
    monkeypatch.setattr(compose_mod, "get_chat_model", lambda *a, **k: fake)
    text, items, stats = compose_mod.write_section(_SEC, EVID, "fake")
    assert stats["repair_rounds"] == 1
    assert stats["ungrounded_numbers"] == 0
    assert not [i for i in items if i.type == "ungrounded_number"]  # 修好 → 不入队
    assert "486.47" in text and "999.99" not in text


def test_write_section_unrepaired_violation_escalates(monkeypatch):
    fake = ScriptedModel(["高达999.99万亩 [E1]。", "仍是999.99万亩 [E1]。"])  # 修复失败
    monkeypatch.setattr(compose_mod, "get_chat_model", lambda *a, **k: fake)
    _text, items, stats = compose_mod.write_section(_SEC, EVID, "fake")
    assert stats["repair_rounds"] == 1
    assert stats["ungrounded_numbers"] == 1   # 复检仍违例 → 升级入队呈人
    assert [i for i in items if i.type == "ungrounded_number"]
