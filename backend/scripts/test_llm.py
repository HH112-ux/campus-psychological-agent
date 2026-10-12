"""智谱最简调用验证脚本（P0 验收：后端能打印一次大模型返回）。

用法（.env 中配置 ZHIPU_API_KEY 后）：
    .venv/bin/python -m scripts.test_llm
"""
from __future__ import annotations

import asyncio

from app.llm.zhipu import ZhipuProvider


async def main() -> None:
    provider = ZhipuProvider()
    if not provider.api_key:
        print("[SKIP] 未配置 ZHIPU_API_KEY，跳过真实调用（.env 中填写后重试）")
        return
    reply = await provider.generate(
        [{"role": "system", "content": "你是「小屿」，一个温暖不评判的倾听者。"},
         {"role": "user", "content": "最近有点焦虑，考试临近。"}],
        temperature=0.7,
    )
    print("[OK] 智谱返回：", reply)


if __name__ == "__main__":
    asyncio.run(main())
