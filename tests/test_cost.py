"""비용 계측, 재시도, 질의 캐시, 캐스케이드 (src/ext/meter.py, write_cascade_node). HTTP 는 목."""
import asyncio
import json
import math
from dataclasses import dataclass

import httpx
import pytest

from ext import graph_ext as G
from ext import meter as em


# --- PRICE, Meter ----------------------------------------------------------------

def test_price_table_models_and_order():
    assert set(em.PRICE) == {"gpt-4o-mini", "gpt-4o", "text-embedding-3-small"}
    for p_in, p_out in em.PRICE.values():
        assert p_in >= 0 and p_out >= 0
    assert em.PRICE["gpt-4o"][0] > em.PRICE["gpt-4o-mini"][0]   # 캐스케이드 전제: 저가 모델이 더 싸다


def test_meter_token_to_cost():
    m = em.Meter()
    m.add("gpt-4o-mini", 1000, 1000, "route")
    m.add("gpt-4o", 2000, 500, "write#1")
    m.add("gpt-4o", 0, 500, "write#2")
    assert m.tokens() == {"prompt": 3000, "completion": 2000}
    assert m.by_model["gpt-4o"] == {"prompt": 2000, "completion": 1000, "calls": 2}
    assert m.cost_usd() == pytest.approx(0.00015 + 0.0006 + 2 * 0.0025 + 1 * 0.01)
    assert [c["stage"] for c in m.calls] == ["route", "write#1", "write#2"]


def test_meter_embedding_cost_has_no_output_price():
    m = em.Meter()
    m.add("text-embedding-3-small", 5000, 0, "embed")
    assert m.cost_usd() == pytest.approx(0.0001)


def test_meter_unknown_model_cost_is_nan_not_zero():
    """단가표에 없는 모델(예: 로컬 qwen3:8b)은 0원으로 숨기지 않고 NaN 으로 드러낸다."""
    m = em.Meter()
    m.add("gpt-4o-mini", 100, 100, "route")
    m.add("qwen3:8b", 100, 100, "write#1")
    assert math.isnan(m.cost_usd())


def test_empty_meter():
    m = em.Meter()
    assert m.tokens() == {"prompt": 0, "completion": 0} and m.cost_usd() == 0.0


def test_start_meter_and_stage_contextvars():
    m = em.start_meter()
    assert em.current_meter() is m
    assert em._stage.get() == "-"
    with em.stage("judge"):
        assert em._stage.get() == "judge"
        with em.stage("embed"):
            assert em._stage.get() == "embed"
        assert em._stage.get() == "judge"
    assert em._stage.get() == "-"


# --- post_with_retry ----------------------------------------------------------

def _resp(code, body=None, headers=None):
    return httpx.Response(code, json=body or {}, headers=headers or {},
                          request=httpx.Request("POST", "http://mock/v1"))


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(em, "_wait_s", lambda resp, i: 0.0)
    monkeypatch.setattr(em, "RETRY_LOG", [])


def _scripted(monkeypatch, seq):
    seq = list(seq)
    seen = []

    def post(url, json=None, headers=None, timeout=None):
        seen.append(headers)
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    monkeypatch.setattr(em.httpx, "post", post)
    return seen


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_retry_on_transient_status(monkeypatch, no_wait, code):
    _scripted(monkeypatch, [_resp(code), _resp(200, {"ok": 1})])
    m = em.start_meter()
    assert em.post_with_retry("http://mock", {}, "k") == {"ok": 1}
    assert m.retries == 1 and em.RETRY_LOG == [{"reason": code, "try": 1}]


def test_no_retry_on_client_error(monkeypatch, no_wait):
    _scripted(monkeypatch, [_resp(400), _resp(200)])
    with pytest.raises(httpx.HTTPStatusError):
        em.post_with_retry("http://mock", {}, "k")
    assert em.RETRY_LOG == []


def test_retry_on_timeout_then_gives_up(monkeypatch, no_wait):
    _scripted(monkeypatch, [httpx.ReadTimeout("t")] * 3)
    with pytest.raises(httpx.ReadTimeout):
        em.post_with_retry("http://mock", {}, "k", tries=3)
    assert len(em.RETRY_LOG) == 2


def test_last_try_status_error_is_raised(monkeypatch, no_wait):
    _scripted(monkeypatch, [_resp(503), _resp(503)])
    with pytest.raises(httpx.HTTPStatusError):
        em.post_with_retry("http://mock", {}, "k", tries=2)


def test_auth_header(monkeypatch, no_wait):
    seen = _scripted(monkeypatch, [_resp(200)])
    em.post_with_retry("http://mock", {}, "sk-test")
    assert seen[0]["Authorization"] == "Bearer sk-test"


def test_wait_s_respects_retry_after_and_cap(monkeypatch):
    import random
    monkeypatch.setattr(random, "uniform", lambda a, b: 0.0)
    assert em._wait_s(_resp(429, headers={"retry-after": "3"}), 0) == 3.0
    assert em._wait_s(_resp(429, headers={"retry-after": "999"}), 0) == 60.0
    assert em._wait_s(_resp(429, headers={"retry-after": "soon"}), 1) == 4.0   # 숫자가 아니면 지수 대기
    assert em._wait_s(None, 2) == 8.0
    assert em._wait_s(None, 10) == 60.0


# --- MeteredChatMixin ---------------------------------------------------------

def test_metered_chat_records_usage_by_stage(monkeypatch):
    payloads = []

    def fake(url, payload, api_key, tries=7):
        payloads.append(payload)
        return {"choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}}
    monkeypatch.setattr(em, "post_with_retry", fake)
    llm = em.MeteredQualityLLM("gpt-4o", 0.005)
    m = em.start_meter()
    with em.stage("write#1"):
        content, usage = llm._chat("sys", "user", json_mode=True)
    assert content == "{}" and usage["tokens"] == 150
    assert payloads[0]["response_format"] == {"type": "json_object"} and payloads[0]["temperature"] == 0
    assert m.calls == [{"model": "gpt-4o", "stage": "write#1", "prompt": 120, "completion": 30}]


def test_metered_chat_without_key_raises(monkeypatch):
    llm = em.MeteredQualityLLM("gpt-4o", 0.005)
    llm.api_key = ""
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm._chat("s", "u")


# --- QueryCache ---------------------------------------------------------------

@pytest.mark.parametrize("a,b", [("DB 다운!", "db 다운"), ("  Disk   full.", "disk full"),
                                 ("CPU…높음?", "cpu 높음")])
def test_normalize_absorbs_case_space_punct(a, b):
    assert em.normalize(a) == em.normalize(b)


def test_normalize_keeps_different_wording_distinct():
    assert em.normalize("DB 다운") != em.normalize("DB 장애")


def test_cache_hit_miss_counts_and_kind_separation():
    c = em.QueryCache()
    m = em.start_meter()
    assert c.get("route", "q") is None
    c.put("route", "q", {"route": "incident"})
    assert c.get("route", "Q!") == {"route": "incident"}
    assert c.get("plan", "q") is None
    assert (m.cache_lookups, m.cache_hits) == (3, 1)


def test_cache_returns_deep_copies():
    c = em.QueryCache()
    v = {"tasks": [1]}
    c.put("plan", "q", v)
    v["tasks"].append(2)
    got = c.get("plan", "q")
    got["tasks"].append(3)
    assert c.get("plan", "q") == {"tasks": [1]}


def test_cache_ttl_expiry(monkeypatch):
    t = [100.0]
    monkeypatch.setattr(em.time, "monotonic", lambda: t[0])
    c = em.QueryCache(ttl_seconds=10)
    c.put("route", "q", 1)
    t[0] = 110.0
    assert c.get("route", "q") == 1
    t[0] = 110.01
    assert c.get("route", "q") is None


def test_metered_fast_llm_route_cache_skips_llm(monkeypatch):
    calls = []

    def fake_chat(self, system, user, json_mode=False):
        calls.append(user)
        return json.dumps({"route": "incident", "needs_analysis": False}), {"model": "m", "tokens": 10, "usd": 0.1}
    monkeypatch.setattr(em.MeteredFastLLM, "_chat", fake_chat)
    llm = em.MeteredFastLLM("gpt-4o-mini", 0.00015, cache=em.QueryCache())
    r1, u1 = llm.route("DB 다운")
    r2, u2 = llm.route("db 다운!")
    assert r1 == r2 and len(calls) == 1
    assert u2["tokens"] == 0 and u2["usd"] == 0.0


def test_metered_fast_llm_without_cache_always_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(em.MeteredFastLLM, "_chat", lambda self, s, u, json_mode=False: (
        calls.append(u) or json.dumps({"route": "chat", "needs_analysis": False}), {"tokens": 1}))
    llm = em.MeteredFastLLM("gpt-4o-mini", 0.00015)
    llm.route("a")
    llm.route("a")
    assert len(calls) == 2


def test_adapter_cache_per_config_name():
    import src.adapter as A
    A._CACHES.clear()
    assert A._cache_for({"name": "x", "cost": {"cache": False}}) is None
    c1 = A._cache_for({"name": "x", "cost": {"cache": True, "cache_ttl": 5}})
    assert c1 is A._cache_for({"name": "x", "cost": {"cache": True}}) and c1.ttl == 5
    assert A._cache_for({"name": "y", "cost": {"cache": True}}) is not c1
    A._CACHES.clear()


# --- 캐스케이드 (write_cascade_node) ------------------------------------------

@dataclass
class _Deps:
    quality_llm: object
    cheap_writer: object = None


class _Writer:
    def __init__(self, name):
        self.name = name


@pytest.fixture
def capture_writer(monkeypatch):
    used = []

    async def fake_write_node(state, deps):
        used.append(deps.quality_llm.name)
        return {"draft": "d", "events": [{"type": "DraftWritten"}]}
    monkeypatch.setattr(G, "write_node", fake_write_node)
    return used


@pytest.mark.parametrize("attempts_before,expected", [(0, "cheap"), (1, "quality"), (2, "quality")])
def test_cascade_first_draft_cheap_then_quality(capture_writer, attempts_before, expected):
    deps = _Deps(quality_llm=_Writer("quality"), cheap_writer=_Writer("cheap"))
    out = asyncio.run(G.write_cascade_node({"validation_attempts": attempts_before}, deps=deps))
    assert capture_writer == [expected] and out["events"][-1]["writer"] == expected


def test_cascade_without_cheap_writer_uses_quality(capture_writer):
    deps = _Deps(quality_llm=_Writer("quality"))
    asyncio.run(G.write_cascade_node({}, deps=deps))
    assert capture_writer == ["quality"]
