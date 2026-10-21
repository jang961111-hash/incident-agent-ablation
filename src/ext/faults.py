"""장애 주입 — MCP 도구 호출 일부를 일부러 실패시켜 부분 실패 복구를 측정한다.

    cfg["fault_injection"] = {"tool": "get_monitoring_status", "rate": 0.3, "seed": 7}

같은 (seed, 질의, 대상 시스템) 이면 같은 결과가 나오도록 결정적으로 고른다. 그래서 base 와
개선판이 같은 호출에서 실패를 맞는다. 원본 with_retry 는 TimeoutError 만 재시도하므로
여기서 던지는 ConnectionError 는 재시도되지 않는 영구 실패다.
"""
from __future__ import annotations

import hashlib


class FaultyMCP:
    def __init__(self, inner, tool: str, rate: float, seed: int, query: str):
        self._inner = inner
        self.tool, self.rate, self.seed, self.query = tool, rate, seed, query
        self.injected = 0

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def _hit(self, arguments: dict) -> bool:
        key = f"{self.seed}|{self.query}|{sorted(arguments.items())}".encode()
        return int(hashlib.sha1(key).hexdigest(), 16) % 10_000 < self.rate * 10_000

    async def call_tool(self, name: str, arguments: dict, server: str = "ops") -> dict:
        if name == self.tool and self._hit(arguments):
            self.injected += 1
            raise ConnectionError(f"injected fault: {name}({arguments})")
        return await self._inner.call_tool(name, arguments, server=server)
