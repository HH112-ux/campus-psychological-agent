"""边界守卫：LangChain 只允许出现在模型调用层（`app/llm/`）。

迁移范围是「只替换传输层」。一旦业务、危机判定、合规过滤或路由模块直接
import LangChain，抽象就会泄漏，确定性链路也可能被逐步改写。本测试用静态
扫描把这条边界固定下来。
"""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def test_langchain_imports_are_confined_to_llm_package():
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(APP_DIR)
        if rel.parts[0] == "llm":
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("import langchain", "from langchain")):
                offenders.append(f"{rel.as_posix()}:{line_no} {stripped}")
    assert offenders == [], "app/llm 之外出现 LangChain 直接依赖：" + "；".join(offenders)
