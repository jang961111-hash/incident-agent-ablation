"""장애 주입 — MCP 도구 호출 일부를 일부러 실패시켜 부분 실패 복구를 측정한다.

    cfg["fault_injection"] = {"tool": "get_monitoring_status", "rate": 0.3, "seed": 7}

같은 (seed, 질의, 대상 시스템) 이면 같은 결과가 나오도록 결정적으로 고른다. 그래서 base 와
개선판이 같은 호출에서 실패를 맞는다. 원본 with_retry 는 TimeoutError 만 재시도하므로
여기서 던지는 ConnectionError 는 재시도되지 않는 영구 실패다.

켜는 곳: 구성 yaml 이 아니라 eval/fault_bench.py 가 cfg 에 fault_injection 을 넣고,
src/adapter.py 가 MCP 클라이언트를 이 클래스로 감싼다. 본 Ablation 실행에는 쓰지 않는다.
비교 대상: 원본 research_node(한 태스크 실패 → 질의 전체 예외) vs
runtime.tolerant_research=true 의 research_tolerant_node(실패 태스크만 '조회 실패'로 남김).
"""
from __future__ import annotations

import hashlib


class FaultyMCP:
    """MCP 클라이언트 래퍼. 대상 도구(tool) 호출만 rate 확률로 실패시키고 나머지는 그대로 넘긴다.

    Args:
        inner: 실제 MCPClient.
        tool: 실패시킬 도구 이름 (기본 사용처는 get_monitoring_status).
        rate: 0~1 실패 비율.
        seed: 실패 위치를 바꾸는 값. 같은 seed 면 모든 구성에서 같은 호출이 실패한다.
        query: 질의 문장. 해시 키에 넣어 질의마다 다른 호출이 실패하게 한다.
    """

    def __init__(self, inner, tool: str, rate: float, seed: int, query: str):
        self._inner = inner
        self.tool, self.rate, self.seed, self.query = tool, rate, seed, query
        self.injected = 0

    def __getattr__(self, item):   # call_tool 외의 메서드(read_resource 등)는 그대로 위임
        return getattr(self._inner, item)

    def _hit(self, arguments: dict) -> bool:
        """결정적 추첨: sha1(seed|질의|인자) 를 0~9999 로 접어 rate*10000 미만이면 실패.

        random 을 쓰지 않는 것은 실행 순서, 스레드와 무관하게 base 와 개선판이 '같은 호출'에서
        실패를 맞아야 비교가 공정하기 때문이다. 인자를 정렬해 dict 순서 차이도 없앤다.
        """
        key = f"{self.seed}|{self.query}|{sorted(arguments.items())}".encode()
        return int(hashlib.sha1(key).hexdigest(), 16) % 10_000 < self.rate * 10_000

    async def call_tool(self, name: str, arguments: dict, server: str = "ops") -> dict:
        if name == self.tool and self._hit(arguments):
            self.injected += 1   # adapter 가 faults_injected 로 결과 행에 남긴다
            raise ConnectionError(f"injected fault: {name}({arguments})")
        return await self._inner.call_tool(name, arguments, server=server)
