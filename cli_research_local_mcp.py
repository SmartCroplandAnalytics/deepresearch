#!/usr/bin/env python3
"""
基于MCP的本地文件研究脚本
使用方法: python cli_research_local_mcp.py "研究问题" --docs-path "/path/to/docs"
"""

import os
import argparse
import asyncio
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

async def run_mcp_local_research(question: str, docs_path: str, model: str = "deepseek:deepseek-reasoner"):
    """基于MCP的本地文件研究"""

    # 验证文档路径
    if not os.path.exists(docs_path):
        print(f"错误: 指定的路径不存在: {docs_path}")
        return None

    abs_docs_path = os.path.abspath(docs_path)
    print(f"研究问题: {question}")
    print(f"文档路径: {abs_docs_path}")
    print(f"使用模型: {model}")
    print("=" * 60)

    # 显示可用文件
    print("扫描可用文件...")
    file_count = 0
    for root, dirs, files in os.walk(abs_docs_path):
        for file in files:
            if file.endswith(('.md', '.csv', '.txt', '.py', '.json', '.yaml', '.yml')):
                rel_path = os.path.relpath(os.path.join(root, file), abs_docs_path)
                print(f"  📄 {rel_path}")
                file_count += 1

    print(f"共发现 {file_count} 个可读取文件")
    print("=" * 60)

    # 创建研究图
    builder = StateGraph(
        AgentState,
        input=AgentInputState,
        config_schema=Configuration
    )

    # 添加节点（跳过澄清，专注本地文件研究）
    builder.add_node("write_research_brief", write_research_brief)
    builder.add_node("research_supervisor", supervisor_subgraph)
    builder.add_node("final_report_generation", final_report_generation)

    # 定义边
    builder.add_edge(START, "write_research_brief")
    builder.add_edge("write_research_brief", "research_supervisor")
    builder.add_edge("research_supervisor", "final_report_generation")
    builder.add_edge("final_report_generation", END)

    # 编译图
    graph = builder.compile(checkpointer=MemorySaver())

    # 配置MCP文件系统服务器
    config = {
        "configurable": {
            "thread_id": str(uuid.uuid4()),
            # 基本配置
            "max_structured_output_retries": 3,
            "allow_clarification": False,
            "max_concurrent_research_units": 2,  # 减少并发，专注本地文件
            "search_api": "none",  # 禁用网络搜索，专注本地文件
            "disable_web_search": True,  # 强制禁用所有网络搜索
            "max_researcher_iterations": 4,     # 减少迭代次数
            "max_react_tool_calls": 8,          # 减少工具调用次数

            # 模型配置
            "summarization_model": "deepseek:deepseek-chat",
            "summarization_model_max_tokens": 4096,
            "research_model": model,
            "research_model_max_tokens": 8192,
            "compression_model": "deepseek:deepseek-chat",
            "compression_model_max_tokens": 4096,
            "final_report_model": model,
            "final_report_model_max_tokens": 8192,

            # MCP文件系统配置
            "mcp_config": {
                "url": f"stdio://npx @modelcontextprotocol/server-filesystem {abs_docs_path}",
                "tools": ["read_text_file", "list_directory", "search_files"],
                "auth_required": False
            },
            "mcp_prompt": f"""
🚫 重要：你被配置为仅使用本地文件进行研究，严禁使用任何网络搜索或在线资源！

📁 你现在可以访问 {abs_docs_path} 目录下的所有文件。

🛠️ 可用MCP工具：
- read_text_file: 读取指定文件内容
- list_directory: 查看目录内容
- search_files: 在目录中搜索文件

📋 研究要求：
1. 必须使用read_text_file工具读取本地文件
2. 所有信息必须来源于本地文件
3. 在回答中明确标注信息来源的文件名
4. 如果本地文件信息不足，明确说明而不是猜测

📄 发现的文件类型包括：Markdown文档、CSV数据、文本文件等。

请严格基于本地文件内容进行深度研究分析！
"""
        }
    }

    print("开始本地文件研究...")
    print("=" * 60)

    step_count = 0
    final_result = None

    try:
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

                # 检查是否有MCP工具调用
                if "messages" in node_state:
                    for msg in node_state["messages"]:
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            for tool_call in msg.tool_calls:
                                if tool_call.get('name', '').startswith(('read_', 'list_')):
                                    print(f"🔧 MCP工具调用: {tool_call.get('name', '')} - {tool_call.get('args', {})}")

                # 显示研究计划
                if node_name == "write_research_brief":
                    if "research_brief" in node_state:
                        brief = node_state.get('research_brief', '')
                        print(f"📋 研究计划: {brief}")

                # 显示研究进度
                elif node_name == "research_supervisor":
                    if "notes" in node_state and node_state["notes"]:
                        notes_count = len(node_state["notes"])
                        print(f"📚 已收集 {notes_count} 条研究资料")

                        # 显示最新研究内容预览
                        if notes_count > 0:
                            latest_note = node_state["notes"][-1]
                            preview = latest_note[:200] + "..." if len(latest_note) > 200 else latest_note
                            print(f"📖 最新研究内容: {preview}")

                            # 检查是否包含本地文件引用
                            if "ai_history.md" in latest_note or "ai_timeline.csv" in latest_note:
                                print("✅ 检测到使用了本地文件内容")
                            else:
                                print("⚠️  未明确检测到本地文件使用")

                # 显示最终报告生成
                elif node_name == "final_report_generation":
                    print("📝 正在生成最终报告...")

            final_result = node_state if len(event) == 1 else event

        # 输出最终报告
        if final_result:
            print("\n" + "=" * 60)
            print("📊 研究报告:")
            print("=" * 60)

            report = final_result.get("final_report", "未生成报告")
            if hasattr(report, 'content'):
                report = report.content
            print(report)

            # 保存报告到文件
            timestamp = uuid.uuid4().hex[:8]
            report_filename = f"research_report_{timestamp}.md"
            with open(report_filename, 'w', encoding='utf-8') as f:
                f.write(f"# 研究报告\n\n**研究问题**: {question}\n\n**文档路径**: {abs_docs_path}\n\n**生成时间**: {uuid.uuid4()}\n\n---\n\n{report}")

            print(f"\n📁 报告已保存至: {report_filename}")

        return final_result

    except Exception as e:
        print(f"❌ 研究过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    parser = argparse.ArgumentParser(description="基于MCP的本地文件研究工具")
    parser.add_argument("question", help="研究问题或主题")
    parser.add_argument("--docs-path", required=True, help="要研究的文档目录路径")
    parser.add_argument("--model", default="deepseek:deepseek-reasoner", help="使用的模型")

    args = parser.parse_args()

    # 运行本地文件研究
    result = asyncio.run(run_mcp_local_research(args.question, args.docs_path, args.model))

    if result:
        print("\n✅ 研究完成!")
    else:
        print("\n❌ 研究失败!")

if __name__ == "__main__":
    main()