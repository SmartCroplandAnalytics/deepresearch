"""DeepSeek 当前模型与现有工具消息协议兼容。"""

from agentic_studio.infra.llm import resolve_model


def test_deepseek_current_model_and_tool_mode(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-local-placeholder")
    model = resolve_model("deepseek:")
    assert model.model_name == "deepseek-flash"
    assert model.extra_body == {"thinking": {"type": "disabled"}}
    pro = resolve_model("deepseek:deepseek-v4-pro")
    assert pro.model_name == "deepseek-v4-pro"


def test_other_providers_keep_their_resolver():
    assert resolve_model("openai:example-model") == "openai:example-model"
