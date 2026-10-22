"""실제 OpenAI 경로(HTTP 요청·응답 파싱·재시도·Meter) 를 로컬 모의 서버로 끝까지 돌린다. API 비용 0.

eval/mock_llm_bench.py 의 모의 OpenAI 서버(H)를 그대로 쓰고, 이 프로세스 안에서만 API 주소를
127.0.0.1 로 바꾼다. 임베딩 캐시는 tmp 폴더를 쓴다. 결과 파일은 쓰지 않는다.
"""
import copy
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

import agent.openai_llm as ol
import ext.meter as em
import ext.rag as rg
import src.adapter as adapter
from eval import mock_llm_bench as mb

ROOT = Path(__file__).resolve().parent.parent
QUERY = "auth-service 응답이 느립니다. p95 지연이 2초를 넘는데 어떻게 대응해야 하나요?"


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mb.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


@pytest.fixture
def mock_openai(server, monkeypatch, tmp_path):
    monkeypatch.setattr(ol, "OPENAI_URL", f"{server}/chat/completions")
    monkeypatch.setattr(em, "OPENAI_URL", f"{server}/chat/completions")
    monkeypatch.setattr(rg, "EMBED_URL", f"{server}/embeddings")
    monkeypatch.setattr(adapter, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(rg, "_INDEX", {})
    monkeypatch.setattr(em, "_wait_s", lambda resp, i: 0.0)      # 재시도 대기 없이
    adapter._CACHES.clear()
    monkeypatch.setitem(mb.SCEN, "delay", 0.0)
    for k in ("p503", "pbad", "phang"):
        monkeypatch.setitem(mb.SCEN, k, 0.0)
    mb._rng.seed(7)
    yield mb.SCEN
    adapter._CACHES.clear()


def cfg(name):
    c = copy.deepcopy(yaml.safe_load((ROOT / f"eval/configs/{name}.yaml").read_text()))
    c.setdefault("cost", {})["cache"] = False
    return c


@pytest.mark.parametrize("name", ["base", "final"])
def test_openai_code_path_completes_against_mock(mock_openai, name):
    out = adapter.run_once(QUERY, cfg(name))
    assert out["route"] == "incident" and out["answer"].startswith("1)")
    assert out["tokens"]["prompt"] > 0 and out["api_retries"] == 0
    assert out["cost_usd"] > 0 and out["cost_usd"] == out["cost_usd"]   # 단가표 모델만 써서 NaN 아님
    stages = {c["stage"] for c in out["llm_calls"]}
    assert {"route", "plan", "write#1"} <= stages
    if name == "final":
        assert "judge" in stages and out["judge_history"][0]["score"] == 1.0
        assert "embed" in stages and len(out["retrieved"]) == 3


def test_transient_503_is_retried_not_fatal(mock_openai):
    mock_openai["p503"] = 0.3
    out = adapter.run_once(QUERY, cfg("final"))
    assert out["answer"] and out["api_retries"] >= 1
