"""P2：评估回归门缺少 secret 时必须显式失败，不得静默跳过。"""
from __future__ import annotations

import asyncio
import sys

from app.config import get_settings


def test_eval_gates_fail_without_secret_when_required(monkeypatch, capsys):
    from scripts import eval_emotion_p5 as emotion_gate
    from scripts import eval_long_memory as memory_gate

    monkeypatch.setitem(get_settings().__dict__, "zhipu_api_key", "")

    for script, argv in (
        (emotion_gate, ["eval_emotion_p5.py", "--gate", "--require-key"]),
        (memory_gate, ["eval_long_memory.py", "--gate", "--require-key"]),
    ):
        monkeypatch.setattr(sys, "argv", argv)
        assert asyncio.run(script.main()) == 1
        assert "FAIL" in capsys.readouterr().err

    # 不带 --require-key 时保持本地可跑：SKIP + 退出 0
    monkeypatch.setattr(sys, "argv", ["eval_emotion_p5.py", "--gate"])
    assert asyncio.run(emotion_gate.main()) == 0
