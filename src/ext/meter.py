"""토큰 계측 + 질의 캐시.

원본 OpenAIFastLLM / OpenAIQualityLLM 을 상속해 `_chat` 만 바꾼다. 요청 payload(모델·
메시지·temperature·JSON 모드)는 원본과 같고, 응답의 usage 를 prompt/completion 으로
나눠 Meter 에 적는 것과 429/5xx 재시도만 더했다. 원본은 total_tokens 하나에 가상 단가를
곱해 비용을 내서, 입력·출력 단가가 다른 실제 비용을 계산할 수 없다.

캐시는 cost.cache=true 일 때만 켜진다. 질의를 정규화한 키로 route / plan 결과만
저장한다. 모니터링 값은 호출마다 바뀌므로 research 와 write 결과는 캐시하지 않는다.
"""
from __future__ import annotations

import contextvars
import copy
import re
import time
from contextlib import contextmanager

import httpx

from agent.openai_llm import OPENAI_URL, OpenAIFastLLM, OpenAIQualityLLM

# USD / 1K tokens (입력, 출력). OpenAI 공개 단가 기준이며 보고서에는 '추정'으로 표기한다.
PRICE = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "text-embedding-3-small": (0.00002, 0.0),
}


class Meter:
    """질의 1건 동안의 LLM 호출 기록."""

    def __init__(self):
        self.by_model: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.cache_lookups = 0
        self.cache_hits = 0
        self.retries = 0   # 429·5xx·타임아웃 재시도 횟수 — 지연 해석용

    def add(self, model: str, prompt: int, completion: int, stage: str):
        m = self.by_model.setdefault(model, {"prompt": 0, "completion": 0, "calls": 0})
        m["prompt"] += prompt
        m["completion"] += completion
        m["calls"] += 1
        self.calls.append({"model": model, "stage": stage,
                           "prompt": prompt, "completion": completion})

    def tokens(self) -> dict:
        return {"prompt": sum(m["prompt"] for m in self.by_model.values()),
                "completion": sum(m["completion"] for m in self.by_model.values())}

    def cost_usd(self) -> float:
        total = 0.0
        for model, m in self.by_model.items():
            p_in, p_out = PRICE.get(model, (float("nan"), float("nan")))
            total += m["prompt"] / 1000 * p_in + m["completion"] / 1000 * p_out
        return total


_meter: contextvars.ContextVar[Meter | None] = contextvars.ContextVar("meter", default=None)
_stage: contextvars.ContextVar[str] = contextvars.ContextVar("stage", default="-")


def start_meter() -> Meter:
    m = Meter()
    _meter.set(m)
    return m


def current_meter() -> Meter | None:
    return _meter.get()


@contextmanager
def stage(name: str):
    token = _stage.set(name)
    try:
        yield
    finally:
        _stage.reset(token)


RETRY_LOG: list[dict] = []   # 재시도 발생 기록 — 지연 p95 해석용


def _wait_s(resp, attempt: int) -> float:
    """429 는 서버가 준 Retry-After 를 따르고, 없으면 2·4·8…초 (최대 60초) + 지터."""
    import random
    ra = resp.headers.get("retry-after") if resp is not None else None
    try:
        base = float(ra) if ra else 2 ** (attempt + 1)
    except ValueError:
        base = 2 ** (attempt + 1)
    return min(base, 60.0) + random.uniform(0, 1)


def post_with_retry(url: str, payload: dict, api_key: str, tries: int = 7) -> dict:
    """429/5xx·타임아웃·연결 오류만 재시도. 4xx 등은 바로 올린다.
    공용 수업 키라 다른 사용자 부하로 429 가 잦다 — 오류 행이 생기면 구성 간 비교가 깨지므로 넉넉히 기다린다."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for i in range(tries):
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=60.0)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            if i == tries - 1:
                raise
            RETRY_LOG.append({"reason": type(e).__name__, "try": i + 1})
            if (m := current_meter()) is not None:
                m.retries += 1
            time.sleep(_wait_s(None, i))
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and i < tries - 1:
            RETRY_LOG.append({"reason": resp.status_code, "try": i + 1})
            if (m := current_meter()) is not None:
                m.retries += 1
            time.sleep(_wait_s(resp, i))
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("unreachable")


class MeteredChatMixin:
    """원본 OpenAILLM._chat 과 같은 요청을 보내고 usage 를 나눠 기록한다."""

    def _chat(self, system: str, user: str, json_mode: bool = False) -> tuple[str, dict]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다 — scripts/set_keys.sh 로 입력하세요.")
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = post_with_retry(OPENAI_URL, payload, self.api_key)
        content = data["choices"][0]["message"]["content"]
        u = data.get("usage", {})
        meter = current_meter()
        if meter is not None:
            meter.add(self.model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0),
                      _stage.get())
        tokens = u.get("total_tokens", 0)
        return content, {"model": self.name, "tokens": tokens,
                         "usd": round(tokens / 1000 * self.usd_per_1k, 6)}


# --- 질의 캐시 -------------------------------------------------------------

def normalize(query: str) -> str:
    """대소문자·공백·문장부호 차이만 흡수한다. 의미가 같은 다른 문장은 같은 키가 아니다."""
    q = query.lower()
    q = re.sub(r"[\s.,!?~·…]+", " ", q)
    return q.strip()


class QueryCache:
    """프로세스 수명 동안 유지되는 TTL 캐시. 런북이 바뀌어도 TTL 동안은 옛 결과를 쓴다."""

    def __init__(self, ttl_seconds: float = 600.0):
        self.ttl = ttl_seconds
        self._store: dict[tuple, tuple[float, object]] = {}

    def get(self, kind: str, query: str):
        meter = current_meter()
        if meter is not None:
            meter.cache_lookups += 1
        hit = self._store.get((kind, normalize(query)))
        if hit is None or time.monotonic() - hit[0] > self.ttl:
            return None
        if meter is not None:
            meter.cache_hits += 1
        return copy.deepcopy(hit[1])

    def put(self, kind: str, query: str, value) -> None:
        self._store[(kind, normalize(query))] = (time.monotonic(), copy.deepcopy(value))


_ZERO = {"tokens": 0, "usd": 0.0}


class MeteredFastLLM(MeteredChatMixin, OpenAIFastLLM):
    def __init__(self, model: str, usd_per_1k_tokens: float, cache: QueryCache | None = None):
        super().__init__(model, usd_per_1k_tokens)
        self.cache = cache

    def route(self, query):
        if self.cache and (hit := self.cache.get("route", query)) is not None:
            return hit, {"model": self.name, **_ZERO}
        with stage("route"):
            result, usage = super().route(query)
        if self.cache:
            self.cache.put("route", query, result)
        return result, usage

    def plan(self, query, procedure_prompt):
        if self.cache and (hit := self.cache.get("plan", query)) is not None:
            return hit, {"model": self.name, **_ZERO}
        with stage("plan"):
            result, usage = super().plan(query, procedure_prompt)
        if self.cache:
            self.cache.put("plan", query, result)
        return result, usage

    def analyze(self, collected):
        with stage("analyze"):
            return super().analyze(collected)

    async def chat(self, query, history, on_token=None):
        with stage("chat"):
            return await super().chat(query, history, on_token=on_token)


class MeteredQualityLLM(MeteredChatMixin, OpenAIQualityLLM):
    async def write(self, query, collected, attempt, feedback, on_token=None):
        with stage(f"write#{attempt}"):
            return await super().write(query, collected, attempt, feedback, on_token=on_token)
