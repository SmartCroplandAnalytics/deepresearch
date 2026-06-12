"""网络搜索 / 读取工具 —— 可换 provider，联网可开关（架构 §9 / §5.5）。

provider 选择：显式参数 > env `AS_WEB_PROVIDER` > 默认 `"jina"`。
- **jina（默认，免费无 key）**：`s.jina.ai` 搜索 + `r.jina.ai` 读取。
  `JINA_API_KEY` 可选（仅提升限速）。
- **tavily（需 `TAVILY_API_KEY`）**：`TavilySearch` + `TavilyExtract`。缺 key 自动退回 jina。
- **none / off / disabled**：返回空表（关闭联网）。

"联网开关"在两处：① 本文件 provider=none；② 上层 `build_session(enable_web=...)`
（CLI `--web/--no-web`）。仅 infra 可 import langchain / 发网络请求。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "jina"
_JINA_SEARCH = "https://s.jina.ai/"
_JINA_READ = "https://r.jina.ai/"
_MAX_READ_CHARS = 20_000
_OFF = {"", "none", "off", "disabled", "false", "0"}


def resolve_provider(provider: str | None = None) -> str:
    """显式参数 > env AS_WEB_PROVIDER > 'jina'；tavily 缺 key 时退回 jina。"""
    p = (provider or os.environ.get("AS_WEB_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if p in _OFF:
        return "none"
    if p == "tavily" and not os.environ.get("TAVILY_API_KEY"):
        logger.warning("web provider=tavily 但 TAVILY_API_KEY 未设置 → 退回免费 jina。")
        return "jina"
    return p


def make_web_tools(provider: str | None = None, *, max_results: int = 5) -> list[Any]:
    """返回 web 工具（[web_search, web_read] 或 Tavily 等价物）。none / 失败 → 空表。"""
    p = resolve_provider(provider)
    if p == "none":
        return []
    if p == "tavily":
        return _tavily_tools(max_results)
    if p != "jina":
        logger.warning("未知 web provider '%s' → 退回 jina。", p)
    return _jina_tools(max_results)


def _jina_headers(*, json_accept: bool) -> dict[str, str]:
    h: dict[str, str] = {}
    if json_accept:
        h["Accept"] = "application/json"
    key = os.environ.get("JINA_API_KEY")
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def _jina_tools(max_results: int) -> list[Any]:
    try:
        import httpx
        from langchain_core.tools import tool
    except Exception as exc:  # noqa: BLE001
        logger.warning("jina web 工具不可用（缺 httpx / langchain_core）：%s", exc)
        return []

    @tool
    def web_search(query: str, top_k: int = max_results) -> str:
        """互联网搜索（Jina s.jina.ai，免费）。返回前若干结果（标题 / URL / 摘要）。

        query 要短而具体（1–4 个关键短语）。拿到 URL 后用 web_read 抓全文再存档。
        """
        try:
            resp = httpx.get(
                _JINA_SEARCH,
                params={"q": query},
                headers={**_jina_headers(json_accept=True), "X-Respond-With": "no-content"},
                timeout=httpx.Timeout(30.0),
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
        except Exception as exc:  # noqa: BLE001
            return f"搜索失败（{type(exc).__name__}）：{exc}"
        if not data:
            return f"无结果：{query}"
        out: list[str] = []
        for i, item in enumerate(data[: int(top_k)], 1):
            title = item.get("title") or ""
            url = item.get("url") or ""
            snippet = (item.get("description") or item.get("content") or "")[:300]
            out.append(f"[{i}] {title}\n{url}\n{snippet}".rstrip())
        return "\n\n".join(out)

    @tool
    def web_read(url: str) -> str:
        """抓取一个 URL 的正文（Jina r.jina.ai，免费），返回 markdown。

        archive-first：把返回内容用 write_file 存到 knowledge_base/sources/<slug>.md 后再做笔记。
        """
        try:
            resp = httpx.get(
                _JINA_READ + url,
                headers=_jina_headers(json_accept=False),
                timeout=httpx.Timeout(60.0),
                follow_redirects=True,
            )
            resp.raise_for_status()
            text = resp.text
        except Exception as exc:  # noqa: BLE001
            return f"读取失败 {url}（{type(exc).__name__}）：{exc}"
        if len(text) > _MAX_READ_CHARS:
            text = text[:_MAX_READ_CHARS] + "\n…(已截断；如需更多，读更具体的子页)"
        return text

    return [web_search, web_read]


def _tavily_tools(max_results: int) -> list[Any]:
    tools: list[Any] = []
    try:
        from langchain_tavily import TavilySearch

        tools.append(TavilySearch(max_results=max_results))
    except Exception as exc:  # noqa: BLE001
        logger.warning("TavilySearch 构造失败（%s）→ 退回 jina。", exc)
        return _jina_tools(max_results)
    try:
        from langchain_tavily import TavilyExtract

        tools.append(TavilyExtract())
    except Exception:  # extract 可选
        pass
    return tools
