"""提示词 registry —— 提示词与框架代码解耦（工程规范 §7）。

所有跨轮使用的系统提示放本目录 .md 文件，代码经 `load(name)` / `render(name, **vars)` 取用：
- 模板用 `string.Template` 语法（`$var`）——对提示里的 JSON 花括号天然安全。
- 纯 stdlib（core 同级的轻包），任何层都可 import。

改提示 = 改 .md，不动代码。
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from string import Template

_DIR = Path(__file__).parent


@cache
def load(name: str) -> str:
    """读取模板原文（不替换变量）。name 不带扩展名，如 'compose_sys'。"""
    f = _DIR / f"{name}.md"
    if not f.is_file():
        raise KeyError(f"未知提示模板：{name}（{f} 不存在）")
    return f.read_text(encoding="utf-8").strip()


def render(name: str, **vars: object) -> str:
    """加载并替换 $var。缺变量直接 KeyError（提示模板是契约，不静默放过）。"""
    return Template(load(name)).substitute(**{k: str(v) for k, v in vars.items()})


def fingerprint() -> str:
    """全部提示模板的内容指纹（crc32，8 位 hex）——进产物溯源元数据，提示一变指纹即变。"""
    import zlib

    crc = 0
    for f in sorted(_DIR.glob("*.md")):
        crc = zlib.crc32(f.name.encode() + f.read_bytes(), crc)
    return f"{crc:08x}"
