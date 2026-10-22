"""RAG 런북 선택 (src/ext/rag.py + replan_check_rag_node) — 임베더는 로컬 또는 목."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from ext import meter as em
from ext import rag as rg
from ext.graph_ext import replan_check_rag_node

ROOT = Path(__file__).resolve().parent.parent
RB = ROOT / "src/data/runbooks"
RUNBOOKS = sorted(p.stem for p in RB.glob("*.md"))


@pytest.fixture(autouse=True)
def fresh_index(monkeypatch):
    """런북 색인은 프로세스 전역(_INDEX)이다. 테스트끼리 섞이지 않게 비운다."""
    monkeypatch.setattr(rg, "_INDEX", {})


# --- select_feed: margin --------------------------------------------------------

def test_select_feed_margin_keeps_close_seconds():
    ranking = [("a", 0.80), ("b", 0.77), ("c", 0.60)]
    assert rg.select_feed(ranking, margin=0.05) == ["a", "b"]
    assert rg.select_feed(ranking, margin=0.0) == ["a"]
    assert rg.select_feed(ranking, margin=1.0) == ["a", "b", "c"]


def test_select_feed_empty():
    assert rg.select_feed([], margin=0.05) == []


# --- 로컬 임베더: 결정성 ----------------------------------------------------------

@pytest.mark.parametrize("make", [lambda: rg.LocalNgramEmbedder(), lambda: rg.LocalTfidfEmbedder(RB)])
def test_local_embedders_are_deterministic_unit_vectors(make):
    a = make().embed(["DB 프라이머리 다운", "디스크 95%"])
    b = make().embed(["DB 프라이머리 다운", "디스크 95%"])
    assert a == b
    for v in a:
        assert sum(x * x for x in v) == pytest.approx(1.0)


def test_ngram_embedder_ignores_case_and_whitespace():
    e = rg.LocalNgramEmbedder(dim=64)
    assert e.embed(["DB Down"]) == e.embed(["db   down"])
    assert len(e.embed(["x"])[0]) == 64


def test_tfidf_vocab_comes_only_from_runbooks():
    e = rg.LocalTfidfEmbedder(RB)
    v = e.embed(["ㅁㄴㅇㄹ 쿼크"])[0]          # 런북에 없는 글자 조합 → 영벡터
    assert set(v) == {0.0}
    assert len(v) == len(e.vocab)
    # 6개 런북 모두에 나오는 어구는 idf 가 가장 낮다
    assert min(e.idf.values()) == pytest.approx(0.0)


def test_unit_handles_zero_vector():
    assert rg._unit([0.0, 0.0]) == [0.0, 0.0]
    assert rg._unit([3.0, 4.0]) == pytest.approx([0.6, 0.8])


# --- RunbookRetriever: top-k, 캐시 ------------------------------------------------

def test_retriever_top_k_sorted_and_ids_are_runbooks():
    ret = rg.RunbookRetriever(RB, rg.LocalTfidfEmbedder(RB))
    r3 = ret.rank("디스크가 가득 찼습니다", top_k=3)
    assert len(r3) == 3 and [s for _, s in r3] == sorted((s for _, s in r3), reverse=True)
    assert {rid for rid, _ in r3} <= set(RUNBOOKS)
    assert len(ret.rank("디스크가 가득 찼습니다", top_k=10)) == len(RUNBOOKS)
    assert ret.rank("디스크가 가득 찼습니다", top_k=1)[0] == r3[0]


def test_retriever_index_built_once_per_embedder_name():
    calls = []

    class Counting(rg.LocalNgramEmbedder):
        name = "counting"

        def embed(self, texts, persist=False):
            calls.append(persist)
            return super().embed(texts, persist)

    rg.RunbookRetriever(RB, Counting()).rank("a", 1)
    rg.RunbookRetriever(RB, Counting()).rank("b", 1)
    assert calls.count(True) == 1          # 런북 색인은 1회만, 질의 임베딩은 매번
    assert calls.count(False) == 2


def test_retriever_uses_query_cache():
    cache = em.QueryCache()
    ret = rg.RunbookRetriever(RB, rg.LocalNgramEmbedder(), cache)
    m = em.start_meter()
    first = ret.rank("DB 다운", 2)
    second = ret.rank("db 다운!", 2)        # 정규화 키가 같다
    assert first == second and m.cache_lookups == 2 and m.cache_hits == 1


# --- OpenAIEmbedder (HTTP 목) -----------------------------------------------------

def _fake_openai(calls):
    def post(url, json=None, headers=None, timeout=None, **kw):
        calls.append(json)
        data = [{"embedding": [float(len(t)), 1.0]} for t in json["input"]]
        return httpx.Response(200, json={"data": data, "usage": {"prompt_tokens": 7}},
                              request=httpx.Request("POST", url))
    return post


def test_openai_embedder_requires_key(tmp_path):
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        rg.OpenAIEmbedder("text-embedding-3-small", "", tmp_path).embed(["q"])


def test_openai_embedder_persists_index_but_not_queries(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "post", _fake_openai(calls))
    e = rg.OpenAIEmbedder("text-embedding-3-small", "dummy", tmp_path)
    m = em.start_meter()
    e.embed(["런북1", "런북2"], persist=True)
    e.embed(["런북1"], persist=True)                 # 디스크 캐시 적중 → 호출 없음
    assert len(calls) == 1
    disk = json.loads((tmp_path / "emb_text-embedding-3-small.json").read_text())
    assert len(disk) == 2
    e.embed(["질의"])                                # 질의는 디스크에 남기지 않는다
    assert len(json.loads((tmp_path / "emb_text-embedding-3-small.json").read_text())) == 2
    assert m.by_model["text-embedding-3-small"] == {"prompt": 14, "completion": 0, "calls": 2}
    assert calls[0]["model"] == "text-embedding-3-small"


def test_ollama_embedder_cache_filename_sanitized(tmp_path):
    e = rg.OllamaEmbedder("library/bge-m3:latest", tmp_path)
    assert e.cache_path.name == "emb_ollama_library_bge-m3_latest.json"
    assert e.url == "http://127.0.0.1:11434/api/embed"


# --- replan_check_rag_node: min_score, margin, notices ------------------------------

class FixedRetriever:
    def __init__(self, ranking):
        self.ranking = ranking
        self.calls = []

    def rank(self, query, top_k):
        self.calls.append(top_k)
        return self.ranking[:top_k]


def replan(ranking, query="auth-service 가 느립니다", collected=None, rounds=0, **rag):
    deps = SimpleNamespace(cfg={"rag": rag}, retriever=FixedRetriever(ranking))
    state = {"query": query, "tasks": [], "events": [], "collected": collected or [],
             "replan_rounds": rounds}
    return asyncio.run(replan_check_rag_node(state, deps=deps)), deps.retriever


RANK = [("high-latency", 0.52), ("cpu-spike", 0.50), ("db-down", 0.31)]


def test_margin_feeds_close_runbooks_as_gap_tasks():
    out, ret = replan(RANK, top_k=3, margin=0.05)
    assert out["rag_fed"] == ["high-latency", "cpu-spike"]
    assert [t["target"] for t in out["tasks"]] == ["high-latency", "cpu-spike"]
    assert all(t["kind"] == "runbook" and t["status"] == "pending" for t in out["tasks"])
    assert out["events"][-1]["is_sufficient"] is False and out["replan_rounds"] == 1
    assert ret.calls == [3]


def test_default_top_k_and_margin():
    out, ret = replan(RANK)
    assert ret.calls == [3] and out["rag_fed"] == ["high-latency", "cpu-spike"]


def test_min_score_filters_low_scores():
    out, _ = replan(RANK, margin=0.05, min_score=0.51)
    assert out["rag_fed"] == ["high-latency"] and not out["notices"]


def test_min_score_no_runbook_case_adds_notice_and_no_tasks():
    out, _ = replan(RANK, margin=0.05, min_score=0.6)
    assert out["rag_fed"] == [] and out["tasks"] == []
    assert out["events"][-1]["is_sufficient"] is True       # 보충 조사 없이 analysis 로
    assert len(out["notices"]) == 1 and "일치하는 절차가 없음" in out["notices"][0]
    assert "0.520 < 기준 0.600" in out["notices"][0]
    assert out["collected"][-1] == {"source": "analysis", "data": out["notices"][0]}
    assert out["rag_ranking"] == RANK                        # 순위는 Recall 계산용으로 남긴다


def test_notice_when_query_has_no_known_system():
    out, _ = replan(RANK, query="서비스가 이상해요", notices=True)
    assert any("auth-service 를 기본으로 조회" in n for n in out["notices"])
    out2, _ = replan(RANK, query="web-01 이 이상해요", notices=True)
    assert out2["notices"] == []
    out3, _ = replan(RANK, query="서비스가 이상해요")          # notices 플래그 꺼짐
    assert out3["notices"] == []


def test_skips_when_runbook_already_collected_or_round_used():
    out, ret = replan(RANK, collected=[{"source": "runbook", "data": "x"}])
    assert out["events"][-1]["is_sufficient"] is True and "tasks" not in out and ret.calls == []
    out, ret = replan(RANK, rounds=1)
    assert out["events"][-1]["is_sufficient"] is True and ret.calls == []


def test_rag_with_local_tfidf_end_to_end_db_query():
    ret = rg.RunbookRetriever(RB, rg.LocalTfidfEmbedder(RB))
    deps = SimpleNamespace(cfg={"rag": {"top_k": 3, "margin": 0.05, "min_score": 0.0782}}, retriever=ret)
    state = {"query": "DB 프라이머리가 다운됐습니다. 대응 절차를 알려주세요.", "tasks": [], "events": [],
             "collected": [], "replan_rounds": 0}
    out = asyncio.run(replan_check_rag_node(state, deps=deps))
    assert out["rag_fed"][0] == "db-down" and len(out["rag_ranking"]) == 3
