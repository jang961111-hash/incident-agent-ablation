"""모의 지연 LLM — 동시성 '메커니즘' 검증용 (실제 API 지연 측정이 아니다).

원본 openai_llm 은 async 노드 안에서 동기 httpx.post 를 부른다. 그 동안 이벤트 루프 전체가 멈춘다.
이 모듈은 fake LLM 의 각 호출에 time.sleep(지연)을 넣어 같은 '동기 블로킹 I/O'를 결정적으로 재현한다.
backend: fake_slow 로 쓰고, 지연은 cfg["fake_latency_s"] (기본 0.5초)로 정한다.
"""
from __future__ import annotations

import time

from agent.fake_llm import FastLLM, QualityLLM

from .judge import FakeJudge


class SlowFastLLM(FastLLM):
    def __init__(self, name, usd_per_1k_tokens, delay: float):
        super().__init__(name, usd_per_1k_tokens)
        self.delay = delay

    def route(self, query):
        time.sleep(self.delay)
        return super().route(query)

    def plan(self, query, procedure_prompt):
        time.sleep(self.delay)
        return super().plan(query, procedure_prompt)

    def analyze(self, collected):
        time.sleep(self.delay)
        return super().analyze(collected)

    async def chat(self, query, history, on_token=None):
        time.sleep(self.delay)   # 원본처럼 async 함수 안의 동기 블로킹
        return await super().chat(query, history, on_token=on_token)


class SlowQualityLLM(QualityLLM):
    def __init__(self, name, usd_per_1k_tokens, delay: float):
        super().__init__(name, usd_per_1k_tokens)
        self.delay = delay

    async def write(self, query, collected, attempt, feedback, on_token=None):
        time.sleep(self.delay * 2)   # 작성은 다른 단계보다 오래 걸린다고 가정
        return await super().write(query, collected, attempt, feedback, on_token=on_token)


class SlowJudge(FakeJudge):
    def __init__(self, delay: float):
        self.delay = delay

    def evaluate(self, query, context, answer):
        time.sleep(self.delay)
        return super().evaluate(query, context, answer)
