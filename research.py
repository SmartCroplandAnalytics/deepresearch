#!/usr/bin/env python3
"""
统一深度研究脚本 - 支持完整LangGraph工作流
功能特性：
- 可配置模型 (Qwen/DeepSeek全系列)
- 交互式澄清 (遵循LangGraph模式)
- MCP本地文档读取
- 可开关互联网搜索
- 流式进度显示

使用方法: python research.py "你的研究问题"
"""

import asyncio
import argparse
import uuid
import os
import sys
from typing import Optional
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from open_deep_research.deep_researcher import deep_researcher
from open_deep_research.configuration import Configuration

# 加载环境变量
load_dotenv(".env")

class ResearchConfig:
    """研究配置类，统一管理所有配置参数"""

    def __init__(self,
                 model: str,
                 max_tokens: int,
                 search_enabled: bool = True,
                 search_api: str = "tavily",
                 allow_clarification: bool = True,
                 docs_path: Optional[str] = None,
                 max_concurrent_units: int = 8,
                 max_iterations: int = 10):

        self.model = model
        self.max_tokens = max_tokens
        self.search_enabled = search_enabled
        self.search_api = search_api if search_enabled else "none"
        self.allow_clarification = allow_clarification
        self.docs_path = docs_path
        self.max_concurrent_units = max_concurrent_units
        self.max_iterations = max_iterations

    def get_langgraph_config(self) -> dict:
        """获取LangGraph配置"""
        config = {
            "configurable": {
                "thread_id": str(uuid.uuid4()),

                # 基础配置
                "max_structured_output_retries": 3,
                "allow_clarification": self.allow_clarification,
                "max_concurrent_research_units": self.max_concurrent_units,
                "search_api": self.search_api,
                "max_researcher_iterations": self.max_iterations,
                "max_react_tool_calls": 20,

                # 模型配置 - 统一使用指定的模型和tokens
                "summarization_model": self.model,
                "summarization_model_max_tokens": self.max_tokens,
                "research_model": self.model,
                "research_model_max_tokens": self.max_tokens,
                "compression_model": self.model,
                "compression_model_max_tokens": self.max_tokens,
                # 使用 qwen-plus 生成最终报告以获得更长更详细的输出
                "final_report_model": "qwen-plus",
                "final_report_model_max_tokens": self.max_tokens,  # 使用用户传入的max_tokens
            }
        }

        # 配置MCP本地文档支持（有本地文档时自动启用）
        if self.docs_path and os.path.exists(self.docs_path):
            from pathlib import Path
            mcp_server_path = Path(__file__).parent / "mcp_runtime" / "node_modules" / "@modelcontextprotocol" / "server-filesystem" / "dist" / "index.js"

            # Windows路径兼容：将反斜杠转换为正斜杠（Node.js兼容格式）
            abs_mcp_path = str(mcp_server_path.absolute()).replace('\\', '/')
            abs_docs_path = str(Path(self.docs_path).absolute()).replace('\\', '/')

            config["configurable"]["mcp_config"] = {
                "transport": "stdio",
                "command": "node",
                "args": [abs_mcp_path, abs_docs_path],
                "tools": ["read_text_file", "list_directory", "read_file"],
                "auth_required": False
            }
            config["configurable"]["mcp_prompt"] = (
                f"你可以使用以下MCP工具访问本地文档：\n"
                f"- read_text_file: 读取文本文件内容\n"
                f"- list_directory: 列出目录内容\n"
                f"- read_file: 读取任意文件\n"
                f"目录路径: {self.docs_path}\n"
                f"请优先使用本地文档信息，减少幻觉，提供准确的研究结果。"
            )

        return config

    def validate(self) -> bool:
        """验证配置的有效性"""
        # 验证模型格式 - 使用横杠格式
        valid_models = [
            "qwen-flash", "qwen-plus", "deepseek-chat", "deepseek-reasoner"
        ]
        if self.model not in valid_models:
            print(f"❌ 无效的模型名称: {self.model}")
            print(f"✅ 支持的模型: {', '.join(valid_models)}")
            return False

        # 验证文档路径
        if self.docs_path and not os.path.exists(self.docs_path):
            print(f"❌ 文档路径不存在: {self.docs_path}")
            return False

        # 验证搜索API配置
        if self.search_enabled and self.search_api == "tavily":
            if not os.getenv("TAVILY_API_KEY"):
                print("⚠️  警告: 启用了Tavily搜索但未设置TAVILY_API_KEY")

        return True

    def print_summary(self):
        """打印配置摘要"""
        print("🔧 研究配置:")
        print(f"   模型: {self.model}")
        print(f"   最大Tokens: {self.max_tokens}")
        print(f"   互联网搜索: {'✅ 开启' if self.search_enabled else '❌ 关闭'}")
        if self.search_enabled:
            print(f"   搜索引擎: {self.search_api}")
        print(f"   交互澄清: {'✅ 开启' if self.allow_clarification else '❌ 关闭'}")
        if self.docs_path:
            print(f"   本地文档: {self.docs_path}")
        print(f"   并发数量: {self.max_concurrent_units}")
        print(f"   最大轮次: {self.max_iterations}")
        print("-" * 50)


def select_documents_interactive() -> Optional[str]:
    """交互式选择文档路径"""
    print("\n📁 选择要研究的文档:")
    print("=" * 50)

    # 提供预设选项
    options = [
        ("./test_docs", "测试文档目录"),
        ("./src", "源代码目录"),
        ("./", "项目根目录"),
        ("custom", "自定义路径"),
        ("none", "不使用本地文档")
    ]

    for i, (path, desc) in enumerate(options, 1):
        status = ""
        if path != "custom" and path != "none" and os.path.exists(path):
            status = " ✅"
        elif path != "custom" and path != "none":
            status = " ❌"
        print(f"{i}. {desc} ({path}){status}")

    while True:
        try:
            choice = input("\n请选择 (1-5): ").strip()

            if choice == "1" and os.path.exists("./test_docs"):
                return os.path.abspath("./test_docs")
            elif choice == "2" and os.path.exists("./src"):
                return os.path.abspath("./src")
            elif choice == "3":
                return os.path.abspath("./")
            elif choice == "4":
                custom_path = input("请输入自定义路径: ").strip()
                if os.path.exists(custom_path):
                    return os.path.abspath(custom_path)
                else:
                    print(f"❌ 路径不存在: {custom_path}")
                    continue
            elif choice == "5":
                return None
            else:
                print("❌ 无效选择，请重新输入")
                continue

        except KeyboardInterrupt:
            print("\n👋 用户取消操作")
            return None

    return None


async def run_research(question: str, config: ResearchConfig) -> Optional[dict]:
    """运行深度研究流程"""

    # 验证配置
    if not config.validate():
        return None

    # 打印配置摘要
    config.print_summary()

    print(f"🔍 开始研究: {question}")
    print("=" * 50)

    try:
        # 初始化LangGraph工作流 - deep_researcher 已经是编译好的图
        graph = deep_researcher

        # 获取配置
        langgraph_config = config.get_langgraph_config()

        # 执行研究流程，支持流式输出
        step_count = 0
        final_result = None
        current_stage = "初始化"

        async for event in graph.astream(
            {"messages": [{"role": "user", "content": question}]},
            langgraph_config,
            stream_mode="updates"
        ):
            step_count += 1

            for node_name, node_state in event.items():
                # 安全检查：确保 node_state 不为 None
                if node_state is None:
                    continue

                # 更新阶段显示
                stage_map = {
                    "clarify_with_user": "💬 澄清阶段",
                    "write_research_brief": "📝 计划阶段",
                    "research_supervisor": "🔬 研究阶段",
                    "final_report_generation": "📄 报告阶段"
                }
                current_stage = stage_map.get(node_name, node_name)

                print(f"\n[{step_count}] {current_stage}")

                # 澄清阶段处理
                if node_name == "clarify_with_user":
                    if isinstance(node_state, dict) and "messages" in node_state and node_state["messages"]:
                        latest_message = node_state["messages"][-1]
                        if hasattr(latest_message, 'content'):
                            message_content = latest_message.content

                            # 检查是否需要用户澄清
                            if len(message_content) > 50 and ("?" in message_content or "澄清" in message_content):
                                print(f"\n🤔 系统询问: {message_content}")
                                # 这里LangGraph会自动等待用户输入并继续流程

                # 研究计划阶段
                elif node_name == "write_research_brief":
                    if isinstance(node_state, dict) and "research_brief" in node_state:
                        brief = node_state.get('research_brief', '')[:200] + "..."
                        print(f"📋 研究计划: {brief}")

                # 研究执行阶段
                elif node_name == "research_supervisor":
                    if isinstance(node_state, dict) and "notes" in node_state and node_state["notes"]:
                        notes_count = len(node_state["notes"])
                        print(f"📚 已收集 {notes_count} 条研究资料")

                        # 显示最新研究内容预览
                        if notes_count > 0:
                            latest_note = node_state["notes"][-1]
                            preview = latest_note[:150] + "..." if len(latest_note) > 150 else latest_note
                            print(f"🔍 最新发现: {preview}")

                # 报告生成阶段
                elif node_name == "final_report_generation":
                    print("✍️  正在生成最终研究报告...")
                    if isinstance(node_state, dict) and "final_report" in node_state:
                        print("✅ 报告生成完成!")

            final_result = node_state if len(event) == 1 else event

        # 输出最终报告
        if final_result:
            print("\n" + "=" * 60)
            print("📊 深度研究报告")
            print("=" * 60)

            # 处理不同类型的 final_result
            if isinstance(final_result, dict):
                # 如果是字典，尝试获取 final_report
                report = final_result.get("final_report", "❌ 报告生成失败")
            else:
                # 如果不是字典，可能是事件字典
                report = "❌ 无法解析报告格式"
                # 尝试从event中解析
                for node_name, node_state in final_result.items():
                    if node_name == "final_report_generation" and isinstance(node_state, dict):
                        report = node_state.get("final_report", "❌ 报告生成失败")
                        break

            # 处理不同的报告格式
            if hasattr(report, 'content'):
                report_text = report.content
            elif isinstance(report, str):
                report_text = report
            else:
                report_text = str(report)

            print(report_text)
            print("\n" + "=" * 60)

        return final_result

    except Exception as e:
        error_msg = str(e) if str(e) else f"{type(e).__name__} (无错误消息)"
        print(f"❌ 研究过程出错: {error_msg}")
        import traceback
        print("\n详细错误信息:")
        traceback.print_exc()
        return None


def main():
    """主函数 - 处理命令行参数和用户交互"""
    parser = argparse.ArgumentParser(
        description="统一深度研究工具 - 支持完整LangGraph工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
支持的模型:
  qwen-flash         - Qwen Flash (快速)
  qwen-plus          - Qwen Plus (均衡)
  deepseek-chat      - DeepSeek Chat (对话)
  deepseek-reasoner  - DeepSeek Reasoning (推理)

使用示例:
  python research.py "AI的发展历程" --model deepseek-reasoner --max-tokens 8192
  python research.py "机器学习算法比较" --model qwen-plus --max-tokens 4096
  python research.py "本地项目分析" --docs-path ./src --no-search --model deepseek-chat --max-tokens 8192
  python research.py "快速查询" --no-clarify --model qwen-flash --max-tokens 2048
        """
    )

    parser.add_argument("question", help="研究问题或主题")
    parser.add_argument("--model", required=True,
                       help="使用的模型 (必需参数)")
    parser.add_argument("--no-search", action="store_true",
                       help="禁用互联网搜索，仅使用本地文档")
    parser.add_argument("--search-api", default="tavily", choices=["tavily", "none"],
                       help="搜索引擎选择 (默认: tavily)")
    parser.add_argument("--no-clarify", action="store_true",
                       help="跳过交互式澄清，直接开始研究")
    parser.add_argument("--docs-path",
                       help="指定本地文档路径")
    parser.add_argument("--interactive-docs", action="store_true",
                       help="交互式选择文档路径")
    parser.add_argument("--max-concurrent", type=int, default=8,
                       help="最大并发研究单元数 (默认: 8，用于深度研究)")
    parser.add_argument("--max-iterations", type=int, default=10,
                       help="最大研究轮次 (默认: 10，用于深度研究)")
    parser.add_argument("--max-tokens", type=int, required=True,
                       help="模型最大token数 (必需参数)")

    args = parser.parse_args()

    # 交互式选择文档路径
    docs_path = args.docs_path
    if args.interactive_docs:
        docs_path = select_documents_interactive()

    # 创建研究配置
    config = ResearchConfig(
        model=args.model,
        max_tokens=args.max_tokens,
        search_enabled=not args.no_search,
        search_api=args.search_api,
        allow_clarification=not args.no_clarify,
        docs_path=docs_path,
        max_concurrent_units=args.max_concurrent,
        max_iterations=args.max_iterations
    )

    # 运行研究
    print("🚀 启动深度研究系统...")
    result = asyncio.run(run_research(args.question, config))

    if result:
        print("\n✅ 研究完成!")
        return 0
    else:
        print("\n❌ 研究失败!")
        return 1


if __name__ == "__main__":
    sys.exit(main())