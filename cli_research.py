#!/usr/bin/env python3
"""
简单的命令行深度研究脚本
使用方法: python cli_research.py "你的研究问题"
"""

import asyncio
import argparse
import uuid
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from open_deep_research.deep_researcher import deep_researcher_builder

# 加载环境变量
load_dotenv(".env")

async def run_research(question: str, model: str = "deepseek:deepseek-reasoner", search_api: str = "tavily", allow_clarification: bool = True, docs_path: str = None):
    """运行深度研究并返回结果"""

    # 编译研究图
    graph = deep_researcher_builder.compile(checkpointer=MemorySaver())

    # 配置参数
    config = {
        "configurable": {
            "thread_id": str(uuid.uuid4()),
            # 基本配置
            "max_structured_output_retries": 3,
            "allow_clarification": allow_clarification,  # 支持澄清
            "max_concurrent_research_units": 5,  # 并发研究单元数
            "search_api": search_api,
            "max_researcher_iterations": 6,
            "max_react_tool_calls": 10,
            # 模型配置 - 动态设置，DeepSeek max_tokens限制为8192
            "summarization_model": "deepseek:deepseek-chat",  # 总结用普通模型节省成本
            "summarization_model_max_tokens": 4096,
            "research_model": model,  # 使用用户指定的模型
            "research_model_max_tokens": 8192,
            "compression_model": "deepseek:deepseek-chat",  # 压缩用普通模型
            "compression_model_max_tokens": 4096,
            "final_report_model": model,  # 最终报告用用户指定的模型
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
        # 执行研究，使用流式输出
        print("正在处理研究请求...")

        # 执行研究流程，显示进度
        print("开始研究流程...")

        final_state = None
        step_count = 0

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
                if node_name == "write_research_brief" and "research_brief" in node_state:
                    brief = node_state.get('research_brief', '')
                    print(f"研究计划: {brief[:200]}...")

                # 显示研究进度
                elif node_name == "research_supervisor":
                    if "notes" in node_state and node_state["notes"]:
                        notes_count = len(node_state["notes"])
                        print(f"已收集 {notes_count} 条研究资料")

                # 显示最终报告生成
                elif node_name == "final_report_generation":
                    print("正在生成最终报告...")

            final_state = node_state if len(event) == 1 else event

        # 获取最终结果
        final_result = final_state

        print("\n" + "=" * 50)
        print("研究报告:")
        print("=" * 50)
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
    parser = argparse.ArgumentParser(description="命令行深度研究工具")
    parser.add_argument("question", help="研究问题或主题")
    parser.add_argument("--model", default="deepseek:deepseek-reasoner", help="使用的模型 (默认: deepseek:deepseek-reasoner)")
    parser.add_argument("--search", default="tavily", help="搜索API (默认: tavily)")
    parser.add_argument("--no-clarify", action="store_true", help="跳过澄清步骤，直接开始研究")
    parser.add_argument("--docs-path", help="指定要研究的本地文档路径")

    args = parser.parse_args()

    # 运行异步研究
    allow_clarification = not args.no_clarify
    result = asyncio.run(run_research(args.question, args.model, args.search, allow_clarification, args.docs_path))

    if result:
        print("\n研究完成!")
    else:
        print("\n研究失败!")

if __name__ == "__main__":
    main()