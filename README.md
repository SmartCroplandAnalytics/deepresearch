# deepresearch — 耕地时空演变与粮食安全效应对话研究引擎

SmartCroplandAnalytics 的研究 Agent 子项目。本分支（`octpre`）沿用 junePre 的
[agentic-studio] 的三层架构：**runtime（对话会话）/ 能力（grounded-writing）/ plugin（领域）**，
领域 plugin 包括 **耕地时空演变**（`cropland-spatiotemporal`）与
**粮食安全效应**（`food-security`），二者共用写作、问数及图表能力，
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

## DeepSeek 模型配置（2026-10-08 核对）

当前默认模型为 `deepseek:deepseek-flash`（V4.1 Flash），也可使用
`deepseek:deepseek-v4-pro`；OpenAI 兼容地址仍为 `https://api.deepseek.com`。
官方文档及本次鉴权 `/models` 返回均确认上述两个模型名。
配置密钥使用本地 `.env` 或平台研究页设置，不提交密钥。

本实现显式关闭思考模式，沿用原 LangChain 会话、工具调用和报告生成链。
官方思考模式要求在工具对话中回传 `reasoning_content`；当前消息持久化不保留该字段，
因此不能仅换模型名就默认开启思考模式。

参考：[首次调用 API](https://api-docs.deepseek.com/zh-cn/)、
[思考模式与工具调用](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)。

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
