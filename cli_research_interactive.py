#!/usr/bin/env python3
"""
交互式研究脚本 - 支持澄清输入
使用方法: python cli_research_interactive.py "你的研究问题"
"""

import asyncio
import argparse
import uuid
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from open_deep_research.deep_researcher import (
    clarify_with_user,
    write_research_brief,
    supervisor_subgraph,
    final_report_generation
)
from open_deep_research.state import AgentState, AgentInputState
from open_deep_research.configuration import Configuration
from langchain_core.messages import HumanMessage

# 加载环境变量
load_dotenv(".env")

async def run_interactive_research(question: str, model: str = "deepseek:deepseek-reasoner", search_api: str = "tavily"):
    """运行交互式深度研究"""

    # 编译研究图
    from open_deep_research.deep_researcher import deep_researcher_builder
    graph = deep_researcher_builder.compile(checkpointer=MemorySaver())

    # 配置参数
    config = {
        "configurable": {
            "thread_id": str(uuid.uuid4()),
            # 基本配置
            "max_structured_output_retries": 3,
            "allow_clarification": True,  # 启用澄清
            "max_concurrent_research_units": 5,
            "search_api": search_api,
            "max_researcher_iterations": 6,
            "max_react_tool_calls": 10,
            # 模型配置
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

    print(f"开始研究: {question}")
    print(f"使用模型: {model}")
    print(f"搜索引擎: {search_api}")
    print("=" * 50)

    try:
        # 第一步：检查是否需要澄清
        print("检查是否需要澄清...")

        # 执行第一步澄清
        first_result = None
        step_count = 0

        async for event in graph.astream(
            {"messages": [{"role": "user", "content": question}]},
            config,
            stream_mode="updates"
        ):
            step_count += 1

            for node_name, node_state in event.items():
                print(f"\n[{step_count}] 执行节点: {node_name}")

                if node_name == "clarify_with_user":
                    if "messages" in node_state and node_state["messages"]:
                        latest_message = node_state["messages"][-1]
                        if hasattr(latest_message, 'content'):
                            message_content = latest_message.content
                            print(f"\n系统消息: {message_content}")

                            # 检查是否真的需要澄清（通过消息长度和内容判断）
                            if len(message_content) > 100 and ("澄清" in message_content or "?" in message_content):
                                print("\n" + "="*50)
                                print("系统建议澄清以下问题:")
                                print(message_content)
                                print("="*50)

                                # 等待用户输入
                                user_clarification = input("\n请提供更详细的信息（或直接回车跳过澄清继续研究）: ").strip()

                                if user_clarification:
                                    # 用户提供了澄清信息，重新开始研究
                                    enhanced_question = f"{question}\n\n补充信息: {user_clarification}"
                                    print(f"\n更新后的研究问题: {enhanced_question}")
                                    print("=" * 50)
                                    return await run_direct_research(enhanced_question, model, search_api)
                                else:
                                    # 用户选择直接继续，使用原问题
                                    print("\n跳过澄清，继续使用原问题进行研究...")
                                    print("=" * 50)
                                    return await run_direct_research(question, model, search_api)
                            else:
                                # 不需要澄清，继续研究
                                print("无需澄清，继续研究...")
                                return await run_direct_research(question, model, search_api)

            first_result = event
            # 只执行第一步澄清检查
            break

        # 如果澄清步骤没有返回澄清问题，直接进行研究
        print("无需澄清，直接开始研究...")
        return await run_direct_research(question, model, search_api)

    except Exception as e:
        print(f"研究过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        return None

async def run_direct_research(question: str, model: str, search_api: str):
    """执行直接研究（跳过澄清）"""

    # 创建简化的研究图
    direct_builder = StateGraph(
        AgentState,
        input=AgentInputState,
        config_schema=Configuration
    )

    # 添加节点（跳过澄清）
    direct_builder.add_node("write_research_brief", write_research_brief)
    direct_builder.add_node("research_supervisor", supervisor_subgraph)
    direct_builder.add_node("final_report_generation", final_report_generation)

    # 定义边
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
            "max_structured_output_retries": 3,
            "allow_clarification": False,
            "max_concurrent_research_units": 5,
            "search_api": search_api,
            "max_researcher_iterations": 6,
            "max_react_tool_calls": 10,
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

    print(f"\n开始执行研究流程...")
    print("=" * 50)

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
                    # 显示最新研究内容预览
                    if notes_count > 0:
                        latest_note = node_state["notes"][-1]
                        preview = latest_note[:300] + "..." if len(latest_note) > 300 else latest_note
                        print(f"最新研究内容: {preview}")

            # 显示最终报告生成
            elif node_name == "final_report_generation":
                print("正在生成最终报告...")

        final_result = node_state if len(event) == 1 else event

    # 输出最终报告
    if final_result:
        print("\n" + "=" * 50)
        print("研究报告:")
        print("=" * 50)

        report = final_result.get("final_report", "未生成报告")
        if hasattr(report, 'content'):
            report = report.content
        print(report)

    return final_result

def main():
    parser = argparse.ArgumentParser(description="交互式命令行深度研究工具")
    parser.add_argument("question", help="研究问题或主题")
    parser.add_argument("--model", default="deepseek:deepseek-reasoner", help="使用的模型")
    parser.add_argument("--search", default="none", help="搜索API (tavily需要API密钥)")

    args = parser.parse_args()

    # 运行交互式研究
    result = asyncio.run(run_interactive_research(args.question, args.model, args.search))

    if result:
        print("\n研究完成!")
    else:
        print("\n研究失败!")

if __name__ == "__main__":
    main()