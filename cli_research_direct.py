#!/usr/bin/env python3
"""
直接研究脚本 - 跳过澄清步骤
使用方法: python cli_research_direct.py "你的研究问题"
"""

import asyncio
import argparse
import uuid
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from open_deep_research.deep_researcher import (
    write_research_brief,
    supervisor_subgraph,
    final_report_generation
)
from open_deep_research.state import AgentState, AgentInputState
from open_deep_research.configuration import Configuration

# 加载环境变量
load_dotenv(".env")

async def run_research_direct(question: str, model: str = "deepseek:deepseek-reasoner", search_api: str = "tavily", docs_path: str = None):
    """直接运行深度研究，跳过澄清步骤"""

    # 创建简化的研究图（跳过澄清）
    direct_builder = StateGraph(
        AgentState,
        input=AgentInputState,
        config_schema=Configuration
    )

    # 添加节点（跳过澄清）
    direct_builder.add_node("write_research_brief", write_research_brief)
    direct_builder.add_node("research_supervisor", supervisor_subgraph)
    direct_builder.add_node("final_report_generation", final_report_generation)

    # 定义边（直接从研究计划开始）
    direct_builder.add_edge(START, "write_research_brief")
    direct_builder.add_edge("write_research_brief", "research_supervisor")
    direct_builder.add_edge("research_supervisor", "final_report_generation")
    direct_builder.add_edge("final_report_generation", END)

    # 编译图
    graph = direct_builder.compile(checkpointer=MemorySaver())

    # 配置参数
    config = {
        "configurable": {
            "thread_id": str(uuid.uuid4()),
            # 基本配置
            "max_structured_output_retries": 3,
            "allow_clarification": False,
            "max_concurrent_research_units": 5,
            "search_api": search_api,
            "max_researcher_iterations": 6,
            "max_react_tool_calls": 10,
            # 模型配置 - DeepSeek限制
            "summarization_model": "deepseek:deepseek-chat",
            "summarization_model_max_tokens": 4096,
            "research_model": model,
            "research_model_max_tokens": 8192,
            "compression_model": "deepseek:deepseek-chat",
            "compression_model_max_tokens": 4096,
            "final_report_model": model,
            "final_report_model_max_tokens": 8192,
        }
    }

    # 如果提供了文档路径，添加MCP配置
    if docs_path:
        import os
        if os.path.exists(docs_path):
            print(f"使用文档路径: {docs_path}")
            config["configurable"]["mcp_config"] = {
                "transport": "stdio",
                "command": "npx",
                "args": ["@modelcontextprotocol/server-filesystem", os.path.abspath(docs_path)],
                "tools": ["read_text_file", "list_directory"],
                "auth_required": False
            }
            config["configurable"]["mcp_prompt"] = f"你可以使用read_text_file工具读取{docs_path}目录下的文件，list_directory工具查看目录内容。优先使用本地文件中的信息进行研究，减少AI幻觉。"
        else:
            print(f"警告: 指定的文档路径不存在: {docs_path}")

    print(f"开始研究: {question}")
    print(f"使用模型: {model}")
    print(f"搜索引擎: {search_api}")
    print("=" * 50)

    try:
        print("执行研究流程...")

        step_count = 0
        final_result = None

        # 流式显示研究进展
        async for event in graph.astream(
            {"messages": [{"role": "user", "content": question}]},
            config,
            stream_mode="updates"
        ):
            step_count += 1

            # 显示当前节点信息
            for node_name, node_state in event.items():
                print(f"\n[{step_count}] 执行节点: {node_name}")

                # 显示研究计划
                if node_name == "write_research_brief":
                    if "research_brief" in node_state:
                        brief = node_state.get('research_brief', '')
                        print(f"研究计划: {brief}")

                # 显示研究进度
                elif node_name == "research_supervisor":
                    if "notes" in node_state and node_state["notes"]:
                        notes_count = len(node_state["notes"])
                        print(f"已收集 {notes_count} 条研究资料")
                        # 显示部分研究内容
                        for i, note in enumerate(node_state["notes"][-2:]):  # 显示最新2条
                            preview = note[:200] + "..." if len(note) > 200 else note
                            print(f"  研究{i+1}: {preview}")

                # 显示最终报告生成
                elif node_name == "final_report_generation":
                    print("正在生成最终报告...")
                    if "final_report" in node_state:
                        print("报告生成完成!")

            final_result = node_state if len(event) == 1 else event

        # 输出最终报告
        if final_result:
            print("\n" + "=" * 50)
            print("研究报告:")
            print("=" * 50)

            # 获取最终报告内容
            report = final_result.get("final_report", "未生成报告")
            if hasattr(report, 'content'):
                report = report.content
            print(report)

        return final_result

    except Exception as e:
        print(f"研究过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    parser = argparse.ArgumentParser(description="直接命令行深度研究工具（跳过澄清）")
    parser.add_argument("question", help="研究问题或主题")
    parser.add_argument("--model", default="deepseek:deepseek-reasoner", help="使用的模型")
    parser.add_argument("--search", default="tavily", help="搜索API")
    parser.add_argument("--docs-path", help="指定要研究的本地文档路径")

    args = parser.parse_args()

    # 运行研究
    result = asyncio.run(run_research_direct(args.question, args.model, args.search, args.docs_path))

    if result:
        print("\n研究完成!")
    else:
        print("\n研究失败!")

if __name__ == "__main__":
    main()