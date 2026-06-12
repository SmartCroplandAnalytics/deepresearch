"""infra/ —— 适配层。

第三方 agent / VFS / 文档库（deepagents, langgraph, langchain, mirage, docling）
**只允许在本目录下导入**（架构 §2.5 支线 E）。对外只暴露 Protocol（session.py），
让 core/tools/skills/session 依赖抽象而非具体实现，保住 B1b 退路并隔离 LangChain churn。
"""
