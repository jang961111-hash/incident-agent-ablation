"""모의 지연 LLM — 동시성 '메커니즘' 검증용 (실제 API 지연 측정이 아니다).

원본 openai_llm 은 async 노드 안에서 동기 httpx.post 를 부른다. 그 동안 이벤트 루프 전체가 멈춘다.
이 모듈은 fake LLM 의 각 호출에 time.sleep(지연)을 넣어 같은 '동기 블로킹 I/O'를 결정적으로 재현한다.
backend: fake_slow 로 쓰고, 지연은 cfg["fake_latency_s"] (기본 0.5초)로 정한다.

쓰는 곳: eval/concurrency_bench.py --backend fake_slow → src/adapter.py _build_deps.
일부러 asyncio.sleep 이 아니라 time.sleep 을 쓴다. 그래야 runtime.async_io=false 에서는 루프가 막혀
동시 요청이 줄을 서고, async_io=true(스레드로 빼기)에서는 겹쳐 도는 차이가 API 없이 재현된다.
답 내용은 원본 fake_llm 그대로라 품질은 재지 않는다.
"""
from __future__ import annotations

import time

from agent.fake_llm import FastLLM, QualityLLM

from .judge import FakeJudge


class SlowFastLLM(FastLLM):
    """원본 FastLLM 의 route, plan, analyze, chat 앞에 동기 지연을 넣은 것."""

    def __init__(self, name, usd_per_1k_tokens, delay: float):
        """원본 생성자에 더해 호출마다 넣을 지연(초)을 받는다."""
        super().__init__(name, usd_per_1k_tokens)
        self.delay = delay

    def route(self, query):
        """delay 초 동안 동기로 멈춘 뒤 원본 route 를 부른다."""
        time.sleep(self.delay)
        return super().route(query)

    def plan(self, query, procedure_prompt):
        """delay 초 동안 동기로 멈춘 뒤 원본 plan 을 부른다."""
        time.sleep(self.delay)
        return super().plan(query, procedure_prompt)

    def analyze(self, collected):
        """delay 초 동안 동기로 멈춘 뒤 원본 analyze 를 부른다."""
        time.sleep(self.delay)
        return super().analyze(collected)

    async def chat(self, query, history, on_token=None):
        """async 함수지만 time.sleep 으로 이벤트 루프를 막은 뒤 원본 chat 을 부른다."""
        time.sleep(self.delay)   # 원본처럼 async 함수 안의 동기 블로킹
        return await super().chat(query, history, on_token=on_token)


class SlowQualityLLM(QualityLLM):
    """원본 QualityLLM 의 write 앞에 동기 지연(2배)을 넣은 것. 캐스케이드 저가 writer 로도 쓴다."""

    def __init__(self, name, usd_per_1k_tokens, delay: float):
        """원본 생성자에 더해 기준 지연(초)을 받는다. write 는 이 값의 2배를 쓴다."""
        super().__init__(name, usd_per_1k_tokens)
        self.delay = delay

    async def write(self, query, collected, attempt, feedback, on_token=None):
        """async 함수지만 time.sleep(delay x 2)로 이벤트 루프를 막은 뒤 원본 write 를 부른다."""
        time.sleep(self.delay * 2)   # 작성은 다른 단계보다 오래 걸린다고 가정
        return await super().write(query, collected, attempt, feedback, on_token=on_token)


class SlowJudge(FakeJudge):
    """FakeJudge(원본 규칙과 같은 판정) 앞에 동기 지연을 넣은 것."""

    def __init__(self, delay: float):
        """호출마다 넣을 지연(초)을 저장한다. FakeJudge 에는 생성자가 없어 부모 생성자를 부르지 않는다."""
        self.delay = delay

    def evaluate(self, query, context, answer):
        """delay 초 동안 동기로 멈춘 뒤 FakeJudge 와 같은 판정을 돌려준다."""
        time.sleep(self.delay)
        return super().evaluate(query, context, answer)
