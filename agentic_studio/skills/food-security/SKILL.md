---
name: food-security
description: 粮食安全效应智能分析报告领域 plugin，配合 grounded-writing 分析耕地分布、投入与产出。
version: 0.1
kind: grounded-write-plugin
---

# 粮食安全效应智能分析报告

使用与耕地时空演变一致的 grounded-writing、metric-query、chart 能力。按 outline.yaml 收集指标证据并生成带引用的智能分析报告、Plotly 图表、数据表和判断队列。

资源：大纲及图表定义见 outline.yaml；取数绑定见 datasource.yaml；文风见 style.md。

scope：regions（省或市州，默认四川省）；years（起止年份，默认 2019—2024）；breakdown（是否下钻市州）；sections（1 耕地分布、2 耕地投入、3 耕地产出）。

指标使用 FS_ 或 FOOD_ 前缀，来自“粮食效应数据统计（最终版0830）”，保留表中单位。FS_ 是源表数据，FOOD_ 是经平台指标计算后的值。与耕地时空演变表中同名字段不可混用。

只有 2019、2024 两期，不补造中间年份、不描述连续逐年趋势。播种结构比例与复种指数保留原表比值；粮食单产的单位为吨/亩，不以百分比解读。人口、总播种面积等中间量未单列，不逆推为已有原始数据。先核实覆盖范围，再引用工具提供的确定性变化量；相关变化不等于因果关系。
