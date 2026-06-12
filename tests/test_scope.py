"""scope 泛化：schema 校验 / $绑定 / when 门控 / fanout 展开 / 标签 / lint（全确定性）。"""

import pytest

from agentic_studio.infra.data.providers import ProviderSet
from agentic_studio.workflows.grounded_brief import (
    _bind_spec,
    _expand,
    lint_plugin,
    scope_label,
    validate_scope,
)

PLUGIN = {
    "outline": {
        "title": "测试简报",
        "scope": {
            "label": "$regions（$years）",
            "params": {
                "regions": {"type": "list_str", "default": ["甲省"], "check": "region",
                            "desc": "地区"},
                "years": {"type": "year_range", "default": None, "desc": "年份区间"},
                "breakdown": {"type": "bool", "default": True, "desc": "下钻"},
            },
        },
        "sections": [
            {"id": "1", "title": "一", "children": [
                {"id": "1.1", "title": "总体", "evidence": [
                    {"kind": "series", "code": "X", "region": "$regions", "years": "$years"},
                ]},
            ]},
            {"id": "2", "title": "二", "children": [
                {"id": "2.1", "title": "下钻", "optional": True, "evidence": [
                    {"kind": "by_region", "code": "X", "year": 2024,
                     "parent": "$regions", "when": "$breakdown"},
                ]},
            ]},
        ],
    },
    "style": "",
    "dir": ".",
}

VALIDATORS = {"region": lambda v: None if v in ("甲省", "乙市") else "不在地区维表"}


def test_defaults_and_coercion():
    s = validate_scope(PLUGIN, {}, VALIDATORS)
    assert s == {"regions": ["甲省"], "years": None, "breakdown": True, "sections": []}
    s2 = validate_scope(PLUGIN, {"regions": "乙市", "years": [2023, 2020]}, VALIDATORS)
    assert s2["regions"] == ["乙市"]          # str → list_str
    assert s2["years"] == (2020, 2023)        # 乱序归一


def test_unknown_param_rejected():
    with pytest.raises(ValueError, match="未知 scope 参数"):
        validate_scope(PLUGIN, {"quarter": "Q1"}, VALIDATORS)  # 别的领域的维度 → 拒绝


def test_empty_list_falls_back_to_default():
    # 空列表视同"未提供"→ 回退默认（防 [] 静默生成全缺口稿）
    s = validate_scope(PLUGIN, {"regions": []}, VALIDATORS)
    assert s["regions"] == ["甲省"]


def test_check_validator_runs_per_element():
    with pytest.raises(ValueError, match="丙县"):
        validate_scope(PLUGIN, {"regions": ["甲省", "丙县"]}, VALIDATORS)


def test_sections_reserved_key_validated():
    s = validate_scope(PLUGIN, {"sections": ["1"]}, VALIDATORS)
    assert s["sections"] == ["1"]
    with pytest.raises(ValueError, match="未知章节"):
        validate_scope(PLUGIN, {"sections": ["9"]}, VALIDATORS)


def test_bind_substitute_and_gate():
    scope = {"regions": ["甲省", "乙市"], "years": (2020, 2023), "breakdown": False}
    bound = _bind_spec({"kind": "series", "code": "X", "region": "$regions",
                        "years": "$years"}, scope)
    assert bound["region"] == ["甲省", "乙市"] and bound["years"] == (2020, 2023)
    gated = _bind_spec({"kind": "by_region", "code": "X", "year": 2024,
                        "when": "$breakdown"}, scope)
    assert gated is None  # breakdown=False → 整条规格关掉


def test_bind_unknown_ref_raises():
    with pytest.raises(ValueError, match=r"\$nope"):
        _bind_spec({"kind": "series", "region": "$nope"}, {"regions": []})


def test_expand_fanout_on_list_values():
    spec = {"kind": "series", "code": "X", "region": ["甲省", "乙市"]}
    out = _expand(spec, ("region",))
    assert [s["region"] for s in out] == ["甲省", "乙市"]  # 一地区一证据（对比语义）
    assert _expand({"region": "甲省"}, ("region",)) == [{"region": "甲省"}]


def test_scope_label_template_and_sections_suffix():
    label = scope_label(PLUGIN, {"regions": ["乙市"], "years": (2020, 2023),
                                 "breakdown": True, "sections": ["1"]})
    assert label == "乙市（2020—2023），章节 1"
    label2 = scope_label(PLUGIN, {"regions": ["甲省"], "years": None,
                                  "breakdown": True, "sections": []})
    assert label2 == "甲省（全部）"


class _FakeProvider:
    kind = "series"
    fanout_keys = ("region",)

    def gather(self, spec):  # pragma: no cover
        return []

    def lint(self, spec):
        return None if spec.get("code") == "X" else f"指标 code 不在白名单：{spec.get('code')}"


def test_lint_plugin_flags_unknown_kind_and_code():
    pset = ProviderSet(providers={"series": _FakeProvider()})
    problems = lint_plugin(PLUGIN, pset)
    assert any("by_region" in p for p in problems)  # kind 未注册（fake 只给 series）

    bad = {"outline": {"scope": PLUGIN["outline"]["scope"], "sections": [
        {"id": "1", "title": "一", "evidence": [{"kind": "series", "code": "NOPE"}]},
    ]}, "style": "", "dir": "."}
    assert any("NOPE" in p for p in lint_plugin(bad, pset))
