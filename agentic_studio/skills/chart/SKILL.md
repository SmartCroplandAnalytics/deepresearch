---
name: chart
description: 绘图能力——正常对话里用 Plotly 真的画出交互式图（折线/柱状/散点/饼图等），对话中可缩放·悬停·导出 PNG。隔离子进程沙箱渲染，figure 落工作区直接在对话里显示。用户说"画个图/折线图/柱状图"时用本能力。
version: 0.2
kind: capability
---

# chart 能力（沙箱 Plotly 交互绘图）

让对话 agent 在普通对话里**真的画出交互式图**（而不是把代码丢给用户本地跑）。绘图代码在
**隔离子进程**里执行：环境白名单剥离了所有密钥与 DSN、禁止文件/网络/系统访问、用本环境
venv 的 python、30s 超时——安全地产出一个 **Plotly figure JSON** 落到工作区 `figures/`，
前端用 plotly.js **交互式**渲染（缩放/悬停/图例），**PNG 由图上工具栏或暂存区按钮客户端导出**。

## 工具

- `render_chart(code)`：跑一段 **Plotly** 绘图代码，返回图表相对路径（`figures/xxx.plotly.json`）。
  - 数据**内联写进代码**（如 `years=[2019,2020,...]`、`values=[85.98,86.45,...]`）。
  - 用 `import plotly.graph_objects as go` 或 `import plotly.express as px` 构图，
    **把最终图赋值给变量 `fig`**（如 `fig = go.Figure(...)`、`fig = px.line(...)`）。
  - **中文标签照常写**；**不要** `fig.show()`、不要自己存盘（工具自动保存 fig）。
  - **禁止**：读写文件（`open`）、联网（requests/urllib）、子进程、访问环境变量/系统——命中即被拒。

## 执行纪律

1. 数据先用查库工具（如 `db_series`）拿到真值，再把这些数值**内联**进绘图代码，**不要编造**。
2. 调 `render_chart(code)`；成功后**务必**在回复里用 `![标题](figures/xxx.plotly.json)`
   （路径见返回值）把图展示出来——前端会渲染成可交互图表。
3. 失败（返回里有报错）就按报错**改代码重试**，不要把原始代码丢给用户让其本地运行。
