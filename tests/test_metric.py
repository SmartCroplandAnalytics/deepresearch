"""MetricStore 纯函数件：确定性派生摘要 / 稳定 slug / 配置标识符防线（不连库）。"""

import pytest

from agentic_studio.infra.data.metric_store import (
    MetricSeries,
    MetricSourceConfig,
    _slug,
    _summarize,
)


def test_summarize_derived_quantities():
    s = MetricSeries(code="X", name="耕地面积", unit="万亩", region="乙市",
                     points=[(2020, 486.47), (2023, 499.60)])
    t = _summarize(s)
    assert "期初2020年486.47万亩" in t and "期末2023年499.60万亩" in t
    assert "累计增加13.13万亩" in t
    assert "变化率+2.70%" in t
    assert "年均+4.38万亩" in t


def test_summarize_single_point_empty():
    s = MetricSeries(code="X", name="n", unit="u", region="r", points=[(2020, 1.0)])
    assert _summarize(s) == ""


def test_slug_stable_and_id_safe():
    assert _slug("成都市") == _slug("成都市")  # crc32：跨进程恒定
    assert _slug("成都市") != _slug("绵阳市")
    assert all(c in "0123456789abcdef" for c in _slug("成都市"))


def test_config_rejects_bad_identifier():
    with pytest.raises(ValueError, match="非法 SQL 标识符"):
        MetricSourceConfig(region_table="region; drop table x")


def test_config_from_dict_defaults():
    cfg = MetricSourceConfig.from_dict({
        "dsn_env": "FOO_DSN", "default_region": "甲省",
        "views": {"raw": "v_raw"}, "source_name": "demo",
    })
    assert cfg.raw_view == "v_raw"
    assert cfg.derived_view == "vw_region_time_indicator_derived"  # 未给 → 默认
    assert cfg.default_region == "甲省" and cfg.dsn_env == "FOO_DSN"
