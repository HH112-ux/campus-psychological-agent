"""P5 压测脚本：/health 并发（框架承载）+ 对话接口延迟（真实链路，低频采样）。

只做小规模、克制的测量：并发打 /health 不产生外部副作用；
对话延迟采样用隔离用户、非流式，单轮真实调用。
"""
import asyncio
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


async def hit_health(sem: asyncio.Semaphore, times: list[float], n: int):
    async with sem:
        t0 = time.perf_counter()
        await asyncio.to_thread(
            urllib.request.urlopen, f"{BASE}/health", timeout=5
        )
        times.append(time.perf_counter() - t0)


async def main() -> None:
    # 1) /health 并发：50 并发 × 200 请求（框架/连接池承载）
    sem = asyncio.Semaphore(50)
    times: list[float] = []
    t0 = time.perf_counter()
    await asyncio.gather(*(hit_health(sem, times, i) for i in range(200)))
    total = time.perf_counter() - t0
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    print(f"/health 200 req @50并发: total={total:.2f}s 吞吐={200 / total:.0f} req/s "
          f"P50={times[len(times)//2]*1000:.1f}ms P95={p95*1000:.1f}ms")

    # 2) 对话接口延迟：真实链路 1 次（非流式，含 LLM）
    # 用户创建在脚本外（调用方传入 token）
    print("对话延迟采样见调用方脚本（真实 LLM 链路，单轮）")


if __name__ == "__main__":
    asyncio.run(main())
