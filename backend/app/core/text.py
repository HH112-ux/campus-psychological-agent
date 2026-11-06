"""文本归一化：小写 + 仅保留小写字母/数字/CJK，剔除空白、标点、符号与 emoji。

危机词库匹配（`services/crisis.py`）与长期记忆去重键（`services/long_memory.py`）
共用同一「哪些字符算有效内容」的决策，此前两处各写一份正则。
"""
from __future__ import annotations

import re

KEEP_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]")


def normalize(text: str) -> str:
    """归一化：小写 + 剔除空白与所有标点符号，使「不 想.活了」等同「不想活了」。"""
    return "".join(ch for ch in text.lower() if KEEP_RE.match(ch))
