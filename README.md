# deepresearch — 耕地时空演变对话研究引擎（agentic-studio engineering）

SmartCroplandAnalytics 的研究 Agent 子项目。本分支（`engineering`）采用
[agentic-studio] 的三层架构：**runtime（对话会话）/ 能力（grounded-writing）/ plugin（领域）**，
首个领域 plugin 为 **耕地时空演变简报**（`agentic_studio/skills/cropland-spatiotemporal/`），
数据取自本项目 backend 的 PostgreSQL 指标库（只读安全中介，agent 不写 SQL）。

旧的 open_deep_research 实现保留在 `main` 分支。

## 快速开始

```bash
uv sync --extra agent --extra vfs --extra pg --extra viz --extra dev

# .env：至少 DEEPSEEK_API_KEY + CROPLAND_DSN（见 CLAUDE.md「环境」）

# 对话（会话可续跑：同 -s 即接着上次）
uv run agentic-studio write "写一份成都市2020到2023年的耕地数量与结构变化简报" -s demo

# 一次性出简报（不经对话）
uv run agentic-studio brief cropland-spatiotemporal --scope '{"regions":["成都市"],"years":[2020,2023]}'

# 列举持久会话 / 跑测试
uv run agentic-studio sessions
uv run pytest -q
```

## 核心特性

- **Session 管理**：一会话一 workspace，线程态 SqliteSaver 持久化，跨进程续跑。
- **Grounded 写作**：正文全部数字必须命中证据（确定性 number_check + 修复环），
  图表由数据直出（不经 LLM），疑点入判断队列待人裁决。
- **安全取数**：MetricStore 只读连接 + 指标/地区白名单 + 参数化查询；会话禁命令执行。

## 文档

- `docs/engineering.md` — 工程/整合规范（怎么搭）
- `docs/architecture.md` — 架构设计原理（为什么）
- `CLAUDE.md` — 开发约束与常用命令

[agentic-studio]: https://github.com/Tsaiyber/agentic-studio
