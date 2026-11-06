"""模型输出 JSON 抽取（情绪分析 / 长期记忆共用）。

此前在 `services/emotion.py` 与 `services/long_memory.py` 各写了一份逐字相同的
`_extract_json`：模型输出格式一变就要改两处，漏一处会导致该链路静默失效
（fail-safe 设计下不报错、只是「本轮不写」）。本模块收敛为单一来源。
"""
from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", flags=re.S)


def extract_json(raw: str) -> dict | None:
    """从模型输出中提取 JSON 对象（容忍 markdown 代码块与前后杂质）。

    顺序：去 ```json 围栏 → 整体解析 → 截取首个 `{` 到末个 `}` 再解析。
    任何一步解析出的非对象值（列表/标量）与解析失败一律返回 None。
    """
    text = (raw or "").strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None
    return None
