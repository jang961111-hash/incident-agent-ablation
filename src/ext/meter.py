"""토큰 계측 + 질의 캐시.

원본 OpenAIFastLLM / OpenAIQualityLLM 을 상속해 `_chat` 만 바꾼다. 요청 payload(모델,
메시지, temperature, JSON 모드)는 원본과 같고, 응답의 usage 를 prompt/completion 으로
나눠 Meter 에 적는 것과 429/5xx 재시도만 더했다. 원본은 total_tokens 하나에 가상 단가를
곱해 비용을 내서, 입력, 출력 단가가 다른 실제 비용을 계산할 수 없다.

캐시는 cost.cache=true 일 때만 켜진다. 질의를 정규화한 키로 route / plan 결과만
저장한다. 모니터링 값은 호출마다 바뀌므로 research 와 write 결과는 캐시하지 않는다.
(질의 임베딩도 같은 캐시에 kind="embed" 로 넣는다 — src/ext/rag.py RunbookRetriever.rank)

쓰는 곳: src/adapter.py 가 질의마다 start_meter() 로 새 Meter 를 열고, 끝나면 tokens, cost_usd,
llm_calls, cache, api_retries 를 결과 행에 옮긴다. 비용 = 실측 토큰 x PRICE(공개 단가) 이며 추정치다.
Meter 는 ContextVar 에 둔다. 질의들이 스레드(run_ablation workers), 태스크(concurrency_bench)로
동시에 돌아도 각자의 Meter 에만 기록되고, asyncio.to_thread 는 컨텍스트를 복사하므로
스레드로 뺀 LLM 호출도 같은 질의의 Meter 에 적힌다.
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
# 여기에 없는 모델은 비용이 NaN 이 된다 (로컬 Ollama 데모는 실행 중에 (0, 0)을 더한다).
PRICE = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "text-embedding-3-small": (0.00002, 0.0),
}


class Meter:
    """질의 1건 동안의 LLM 호출 기록."""

    def __init__(self):
        """모델별 누적 토큰(by_model), 호출 목록(calls), 캐시 조회와 적중 수, 재시도 수를 0 으로 시작한다."""
        self.by_model: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.cache_lookups = 0
        self.cache_hits = 0
        self.retries = 0   # 429, 5xx, 타임아웃 재시도 횟수 — 지연 해석용

    def add(self, model: str, prompt: int, completion: int, stage: str):
        """API 호출 1회의 입력, 출력 토큰을 모델별 합계와 호출 목록(단계 이름 포함)에 더한다."""
        m = self.by_model.setdefault(model, {"prompt": 0, "completion": 0, "calls": 0})
        m["prompt"] += prompt
        m["completion"] += completion
        m["calls"] += 1
        self.calls.append({"model": model, "stage": stage,
                           "prompt": prompt, "completion": completion})

    def tokens(self) -> dict:
        """모든 모델의 입력, 출력 토큰 합."""
        return {"prompt": sum(m["prompt"] for m in self.by_model.values()),
                "completion": sum(m["completion"] for m in self.by_model.values())}

    def cost_usd(self) -> float:
        """모델별 입력, 출력 토큰 x PRICE 단가의 합. 단가를 모르는 모델이 있으면 NaN (조용히 0 으로 두지 않음)."""
        total = 0.0
        for model, m in self.by_model.items():
            p_in, p_out = PRICE.get(model, (float("nan"), float("nan")))
            total += m["prompt"] / 1000 * p_in + m["completion"] / 1000 * p_out
        return total


_meter: contextvars.ContextVar[Meter | None] = contextvars.ContextVar("meter", default=None)
_stage: contextvars.ContextVar[str] = contextvars.ContextVar("stage", default="-")


def start_meter() -> Meter:
    """현재 컨텍스트(질의 1건)에 새 Meter 를 건다. 질의 시작마다 부른다."""
    m = Meter()
    _meter.set(m)
    return m


def current_meter() -> Meter | None:
    """현재 컨텍스트의 Meter 를 돌려준다. start_meter 를 부르기 전이면 None 이다."""
    return _meter.get()


@contextmanager
def stage(name: str):
    """이 블록 안의 LLM 호출을 name 단계(route, plan, write#1, judge, embed…)로 기록한다.

    단계 이름은 Meter.calls 에 남아, 캐시 대상 비용 비중(deck/data.py), Judge 호출 수(run_ablation) 계산에 쓰인다.
    """
    token = _stage.set(name)
    try:
        yield
    finally:
        _stage.reset(token)


RETRY_LOG: list[dict] = []   # 재시도 발생 기록 — 지연 p95 해석용


def _wait_s(resp, attempt: int) -> float:
    """429 는 서버가 준 Retry-After 를 따르고, 없으면 2, 4, 8…초 (최대 60초) + 지터.

    지터(0~1초)는 여러 워커가 같은 순간에 한도에 걸렸을 때 같은 순간에 다시 몰리지 않게 한다.
    """
    import random
    ra = resp.headers.get("retry-after") if resp is not None else None
    try:
        base = float(ra) if ra else 2 ** (attempt + 1)
    except ValueError:
        base = 2 ** (attempt + 1)
    return min(base, 60.0) + random.uniform(0, 1)


def post_with_retry(url: str, payload: dict, api_key: str, tries: int = 7) -> dict:
    """429/5xx, 타임아웃, 연결 오류만 재시도. 4xx 등은 바로 올린다.
    429(요청 한도, 지출 한도)가 나면 — 오류 행이 생기면 구성 간 비교가 깨지므로 넉넉히 기다린다.

    tries=7 → 최초 1회 + 재시도 최대 6회. 요청당 타임아웃 60초. 재시도 횟수는 Meter.retries 와
    RETRY_LOG 에 남겨, 지연 p95 가 튀었을 때 API 재시도 때문인지 가려 볼 수 있게 한다.
    마지막 시도의 429/5xx 는 raise_for_status 로, 마지막 시도의 타임아웃은 그대로 올라간다.
    """
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
        """Returns: (응답 본문, 원본과 같은 형식의 usage {model, tokens, usd}).

        두 번째 값은 원본 노드의 cost_usd 상태값 계산(가상 단가 x total_tokens)과 호환하려고 그대로 둔다.
        보고서 비용은 이 값이 아니라 Meter(입력, 출력 단가 분리)를 쓴다.
        """
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
    """대소문자, 공백, 문장부호 차이만 흡수한다. 의미가 같은 다른 문장은 같은 키가 아니다."""
    q = query.lower()
    # 공백, 문장부호 연속을 공백 하나로: "DB 다운!!" 과 "db 다운" 은 같은 키, "DB가 죽었다" 는 다른 키
    q = re.sub(r"[\s.,!?~·…]+", " ", q)
    return q.strip()


class QueryCache:
    """프로세스 수명 동안 유지되는 TTL 캐시. 런북이 바뀌어도 TTL 동안은 옛 결과를 쓴다."""

    def __init__(self, ttl_seconds: float = 600.0):
        """ttl_seconds 가 지난 항목은 get 에서 없는 것으로 본다. 저장소 키는 (kind, 정규화 질의)다."""
        self.ttl = ttl_seconds
        self._store: dict[tuple, tuple[float, object]] = {}

    def get(self, kind: str, query: str):
        """(kind, 정규화 질의) 로 찾는다. 없거나 TTL 이 지났으면 None. 조회, 적중 수는 Meter 에 센다."""
        meter = current_meter()
        if meter is not None:
            meter.cache_lookups += 1
        hit = self._store.get((kind, normalize(query)))
        if hit is None or time.monotonic() - hit[0] > self.ttl:
            return None
        if meter is not None:
            meter.cache_hits += 1
        return copy.deepcopy(hit[1])   # 노드가 결과(tasks 등)를 고쳐 써도 캐시 원본은 그대로 두려고 복사

    def put(self, kind: str, query: str, value) -> None:
        """(kind, 정규화 질의) 키로 값을 저장한다.

        저장할 때도 깊은 복사를 한다. 호출한 쪽이 넘긴 객체를 나중에 고쳐도 캐시 값이 바뀌지 않게 하려는 것이다.
        """
        self._store[(kind, normalize(query))] = (time.monotonic(), copy.deepcopy(value))


_ZERO = {"tokens": 0, "usd": 0.0}


class MeteredFastLLM(MeteredChatMixin, OpenAIFastLLM):
    """route, plan, analyze, chat 담당 저가 모델. cache 가 있으면 route, plan 결과를 질의 단위로 재사용한다.

    캐시 적중 시 usage 는 토큰 0 으로 돌려준다 (실제 API 호출이 없으므로 Meter 에도 안 적힌다).
    plan 은 같은 질의라도 procedure_prompt 가 다를 수 있지만 키에 넣지 않는다 — MCP 프롬프트가
    질의에서 결정적으로 만들어지기 때문이다 (원본 plan_node: 시스템 이름, 증상 = 질의).
    """

    def __init__(self, model: str, usd_per_1k_tokens: float, cache: QueryCache | None = None):
        """원본 생성자에 더해 캐시를 받는다. cache 가 None 이면 캐시 없이 원본과 같게 동작한다."""
        super().__init__(model, usd_per_1k_tokens)
        self.cache = cache

    def route(self, query):
        """캐시에 있으면 토큰 0 으로 돌려주고, 없으면 원본 route 를 "route" 단계로 계측해 부른 뒤 저장한다."""
        if self.cache and (hit := self.cache.get("route", query)) is not None:
            return hit, {"model": self.name, **_ZERO}
        with stage("route"):
            result, usage = super().route(query)
        if self.cache:
            self.cache.put("route", query, result)
        return result, usage

    def plan(self, query, procedure_prompt):
        """캐시에 있으면 토큰 0 으로 돌려주고, 없으면 원본 plan 을 "plan" 단계로 계측해 부른 뒤 저장한다.

        캐시 키에 procedure_prompt 가 빠진 이유는 클래스 설명에 있다.
        """
        if self.cache and (hit := self.cache.get("plan", query)) is not None:
            return hit, {"model": self.name, **_ZERO}
        with stage("plan"):
            result, usage = super().plan(query, procedure_prompt)
        if self.cache:
            self.cache.put("plan", query, result)
        return result, usage

    def analyze(self, collected):
        """원본 analyze 를 "analyze" 단계로 계측한다. 수집 데이터가 매번 달라 캐시하지 않는다."""
        with stage("analyze"):
            return super().analyze(collected)

    async def chat(self, query, history, on_token=None):
        """원본 chat 을 "chat" 단계로 계측한다. 캐시하지 않는다."""
        with stage("chat"):
            return await super().chat(query, history, on_token=on_token)


class MeteredQualityLLM(MeteredChatMixin, OpenAIQualityLLM):
    """write 담당 모델. 캐시하지 않고, 몇 번째 초안인지(write#1, write#2…)를 단계 이름에 남긴다."""

    async def write(self, query, collected, attempt, feedback, on_token=None):
        """원본 write 를 "write#시도번호" 단계로 계측해 부른다. 재작성 비용을 시도별로 나눠 보기 위함이다."""
        with stage(f"write#{attempt}"):
            return await super().write(query, collected, attempt, feedback, on_token=on_token)
